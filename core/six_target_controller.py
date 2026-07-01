"""SixTargetController —— 六目标训练模式核心控制中枢

职责：
    1. 维护 SixState 状态机，管理 6 个 FlyingTargetWidget 的并发显示；
    2. 驱动可配置时长的单局倒计时，命中/未命中实时计分并写入统计仓库；
    3. 对外暴露 start / pause / resume / request_quit，并通过
       sig_state_changed 通知 UI 层同步菜单文本；局终通过
       sig_round_finished 上报 {hits, misses, accuracy, score}；
    4. 通过 sig_stats_updated(hits, misses, remaining_ms) 驱动 HUD 实时刷新；
    5. 协调 HUD / MissDetector / ResultWidget 三个 view 层组件的显隐。

设计要点：
    - 所有状态转换方法先校验当前状态，非法转换静默 return；
    - 静止目标 + Aim Lab 风格：用户自由点击，命中目标球计 hit，
      点击空白区（由 MissDetectorWidget 捕获）计 miss；
    - 暂停续计：pause 记录本轮已用 ms，resume 续接剩余时间，
      而非重新计整轮；
    - FINISHED 非瞬态：局终停留在 FINISHED，弹出结算页，等外部
      重新调 start() 开始下一轮；
    - request_quit 清场后回 IDLE，确保模式切换后可重新 start()；
    - 依赖均通过构造函数注入，不在本文件 import view 层具体类，
      避免与 view / infra 层产生循环引用。
"""

from enum import Enum, auto

from PySide6.QtCore import QObject, Signal, QTimer, QElapsedTimer

from view.flying_target_widget import FlyingTargetWidget


# 局内飞行球数量
NUM_TARGETS = 6
# 单局倒计时（毫秒）默认值参考，实际使用 config.six_target_duration_ms
ROUND_DURATION_MS = 60_000


class SixState(Enum):
    """六目标训练状态枚举。"""
    IDLE = auto()      # 程序启动初始态 / 退出清场后回归态
    RUNNING = auto()   # 6 球并发显示 + 倒计时进行中
    PAUSED = auto()    # 暂停（托盘触发）
    FINISHED = auto()  # 单局结束（非瞬态，等待重新 start）
    EXITING = auto()   # 退出过渡态（清场中，不必长期停留）


class SixTargetController(QObject):
    """六目标训练模式控制中枢：状态机引擎 + 多球调度 + HUD/结算页协调。

    依赖通过构造函数注入（避免循环引用）：
        - config:         ConfigManager，提供 six_target_speed /
                          six_target_size_px / target_color_hex /
                          six_target_min_spacing_px / six_target_duration_ms
        - stats:          SixTargetStatsRepository，
                          record_six / update_best_score / get_best_score
        - hud:            HudWidget 实例（可选，None 时跳过 HUD 调用）
        - miss_detector:  MissDetectorWidget 实例（可选，None 时跳过 miss 检测显隐）
        - result_widget:  ResultWidget 实例（可选，None 时跳过结算页调用）
    """

    # 状态变更信号：参数为新的 SixState，供 TrayManager 更新菜单文本等
    sig_state_changed = Signal(object)
    # 单局结束信号：{"hits": int, "misses": int, "accuracy": float, "score": int}
    sig_round_finished = Signal(dict)
    # HUD 实时刷新信号：(hits, misses, remaining_ms)
    sig_stats_updated = Signal(int, int, int)

    def __init__(self, config, stats, hud=None, miss_detector=None,
                 result_widget=None, parent=None):
        super().__init__(parent)
        self._config = config
        self._stats = stats
        self._hud = hud
        self._miss_detector = miss_detector
        self._result = result_widget
        self._state = SixState.IDLE

        # 读取六目标专属配置（不用普通模式的 target_size_px）
        size = self._config.six_target_size_px
        color = self._config.target_color_hex

        # 预创建 6 个静止目标窗口，连接命中信号
        # （sig_arrived 已移除，静止目标无"到达"概念）
        self._targets = [
            FlyingTargetWidget(i, size, color) for i in range(NUM_TARGETS)
        ]
        for t in self._targets:
            t.sig_hit.connect(self._on_hit)

        # 若 miss 检测层存在，连接 sig_miss → _on_miss
        if self._miss_detector is not None:
            self._miss_detector.sig_miss.connect(self._on_miss)

        # 本局计分
        self._hits = 0
        self._misses = 0

        # 暂停续计：记录本轮已用时间（毫秒）
        self._elapsed_ms = 0
        self._round_elapsed = QElapsedTimer()

        # 单局倒计时定时器（单次触发）
        self._round_timer = QTimer(self)
        self._round_timer.setSingleShot(True)
        self._round_timer.timeout.connect(self._on_round_finished)

        # HUD 实时刷新定时器：100ms 触发一次，emit sig_stats_updated
        self._hud_tick_timer = QTimer(self)
        self._hud_tick_timer.setInterval(100)
        self._hud_tick_timer.timeout.connect(self._emit_stats)

    @property
    def state(self) -> SixState:
        """当前状态（只读）。"""
        return self._state

    # ---------- 对外控制接口（供 TrayManager 调用） ----------

    def start(self):
        """启动一局：IDLE -> RUNNING。

        仅在 IDLE 状态可启动，其他状态静默拒绝。
        """
        if self._state != SixState.IDLE:
            return  # 拒绝非 IDLE 启动
        self._begin_round()

    def pause(self):
        """暂停：RUNNING -> PAUSED。

        记录本轮已用时间并停止倒计时、HUD tick 与所有目标显示，
        便于 resume 续计。
        """
        if self._state != SixState.RUNNING:
            return
        # 记录本轮已用时间，供 resume 续接剩余时间
        self._elapsed_ms = self._round_elapsed.elapsed()
        self._round_timer.stop()
        self._hud_tick_timer.stop()
        for t in self._targets:
            t.despawn()
        if self._hud is not None:
            self._hud.hide_hud()
        if self._miss_detector is not None:
            self._miss_detector.hide()
        self._set_state(SixState.PAUSED)

    def resume(self):
        """恢复：PAUSED -> RUNNING。

        重新 spawn 6 球，倒计时续接剩余时间（不重新计整轮）。
        """
        if self._state != SixState.PAUSED:
            return
        self._spawn_all()
        remaining = max(self._round_duration_ms() - self._elapsed_ms, 0)
        # 重新启动 elapsed 计时，供下次暂停再续
        self._round_elapsed.start()
        self._round_timer.start(remaining)
        self._hud_tick_timer.start()
        if self._hud is not None:
            self._hud.show_hud()
        if self._miss_detector is not None:
            self._miss_detector.show_fullscreen()
        self._set_state(SixState.RUNNING)

    def request_quit(self):
        """请求退出：清场后回 IDLE，确保模式切换后可重新 start()。

        停止倒计时与 HUD tick，隐藏所有目标、HUD、miss 检测层与结算页，
        确保不留残影与悬挂定时器。
        """
        self._round_timer.stop()
        self._hud_tick_timer.stop()
        for t in self._targets:
            t.despawn()
        if self._hud is not None:
            self._hud.hide_hud()
        if self._miss_detector is not None:
            self._miss_detector.hide()
        if self._result is not None:
            self._result.hide()
        # 清场后回 IDLE，保证可重启
        self._set_state(SixState.IDLE)

    # ---------- 内部状态转换与调度 ----------

    def _round_duration_ms(self) -> int:
        """从 config 读取单局时长（毫秒）。"""
        return self._config.six_target_duration_ms

    def _begin_round(self):
        """开新一局：清零计分、显隐 view 层、spawn 6 球、启动倒计时。"""
        self._hits = 0
        self._misses = 0
        self._elapsed_ms = 0
        if self._hud is not None:
            self._hud.show_hud()
        if self._miss_detector is not None:
            self._miss_detector.show_fullscreen()
        self._spawn_all()
        self._round_elapsed.start()
        self._round_timer.start(self._round_duration_ms())
        self._hud_tick_timer.start()
        self._set_state(SixState.RUNNING)

    def _spawn_all(self):
        """按配置速度 spawn 全部 6 球（不含防重叠，防重叠在 _respawn 中处理）。

        spawn 后调 raise_() 确保目标球位于 miss_detector 之上。
        """
        speed = self._config.six_target_speed
        for t in self._targets:
            t.spawn(speed)
            t.raise_()

    def _respawn(self, target_id: int):
        """重置单个目标的位置（命中后调用），带防重叠。

        收集其他可见目标的球心坐标，调用 spawn_at_safe_position
        保证新位置与它们的最小间距 >= six_target_min_spacing_px。

        仅在 RUNNING 状态下重置，暂停/结束时忽略。
        """
        if self._state != SixState.RUNNING:
            return
        other_positions = [
            (t._cx, t._cy)
            for i, t in enumerate(self._targets)
            if i != target_id and t.isVisible()
        ]
        min_dist = float(self._config.six_target_min_spacing_px)
        self._targets[target_id].spawn_at_safe_position(
            self._config.six_target_speed, other_positions, min_dist
        )
        self._targets[target_id].raise_()

    def _on_hit(self, target_id: int, reaction_ms: int):
        """命中回调：计 hit 并记录统计，随即重置该球。"""
        if self._state != SixState.RUNNING:
            return
        self._hits += 1
        self._stats.record_six(hit=True, reaction_ms=reaction_ms)
        self._respawn(target_id)
        self._emit_stats()

    def _on_miss(self):
        """miss 回调（点击空白区）：计 miss 并记录统计。

        miss 不对应具体 target_id，不触发 respawn。
        """
        if self._state != SixState.RUNNING:
            return
        self._misses += 1
        self._stats.record_six(hit=False, reaction_ms=0)
        self._emit_stats()

    def _on_round_finished(self):
        """倒计时结束回调：清场、上报结算、弹结算页、置 FINISHED（非瞬态）。

        停留在 FINISHED 等待外部重新调 start() 开始下一轮，不自动回 IDLE。
        """
        for t in self._targets:
            t.despawn()
        self._hud_tick_timer.stop()
        if self._hud is not None:
            self._hud.hide_hud()
        if self._miss_detector is not None:
            self._miss_detector.hide()
        total = self._hits + self._misses
        accuracy = round(self._hits / total * 100, 1) if total > 0 else 0.0
        base_score = self._hits * 1500
        miss_penalty = self._misses * 300
        acc_multiplier = 0.5 + accuracy / 100
        score = max(0, int((base_score - miss_penalty) * acc_multiplier))
        self._stats.update_best_score(score)
        result = {
            "hits": self._hits,
            "misses": self._misses,
            "accuracy": accuracy,
            "score": score,
        }
        self.sig_round_finished.emit(result)
        # 弹出结算页
        if self._result is not None:
            best = self._stats.get_best_score()
            self._result.show_result(result, best)
        self._set_state(SixState.FINISHED)  # 不再回 IDLE

    def _emit_stats(self):
        """计算剩余时间并广播 sig_stats_updated，供 HUD 刷新。"""
        remaining = self._round_duration_ms() - self._round_elapsed.elapsed()
        self.sig_stats_updated.emit(self._hits, self._misses, max(remaining, 0))

    def _set_state(self, new_state: SixState):
        """更新内部状态并广播变更信号。"""
        self._state = new_state
        self.sig_state_changed.emit(new_state)

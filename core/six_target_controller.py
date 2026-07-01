"""SixTargetController —— 六目标训练模式核心控制中枢

职责：
    1. 维护 SixState 状态机，管理 6 个 FlyingTargetWidget 的并发飞行；
    2. 驱动 60 秒单局倒计时，命中/未命中实时计分并写入统计仓库；
    3. 对外暴露 start / pause / resume / request_quit，并通过
       sig_state_changed 通知 UI 层同步菜单文本；局终通过
       sig_round_finished 上报 {hits, misses, accuracy}。

设计要点：
    - 所有状态转换方法先校验当前状态，非法转换静默 return；
    - 不实现鼠标锁定：用户自由移动鼠标点击飞行球；
    - 暂停续计：pause 记录本轮已用 ms，resume 续接剩余时间，
      而非重新计整轮；
    - FINISHED 非瞬态：局终停留在 FINISHED，等外部重新调 start()
      开始下一轮；
    - request_quit 清场后回 IDLE，确保模式切换后可重新 start()；
    - 依赖均通过构造函数注入，不在本文件 import 具体类，
      避免与 view / infra 层产生循环引用。
"""

from enum import Enum, auto

from PySide6.QtCore import QObject, Signal, QTimer, QElapsedTimer

from view.flying_target_widget import FlyingTargetWidget


# 局内飞行球数量
NUM_TARGETS = 6
# 单局倒计时（毫秒），60 秒
ROUND_DURATION_MS = 60_000


class SixState(Enum):
    """六目标训练状态枚举。"""
    IDLE = auto()      # 程序启动初始态 / 退出清场后回归态
    RUNNING = auto()   # 6 球并发飞行 + 倒计时进行中
    PAUSED = auto()    # 暂停（托盘触发）
    FINISHED = auto()  # 单局结束（非瞬态，等待重新 start）
    EXITING = auto()   # 退出过渡态（清场中，不必长期停留）


class SixTargetController(QObject):
    """六目标训练模式控制中枢：状态机引擎 + 多球调度。

    依赖通过构造函数注入（避免循环引用）：
        - config:  ConfigManager，提供 six_target_speed /
                   six_target_size_px / target_color_hex 配置
        - stats:   SixTargetStatsRepository，记录命中/未命中样本
    """

    # 状态变更信号：参数为新的 SixState，供 TrayManager 更新菜单文本等
    sig_state_changed = Signal(object)
    # 单局结束信号：{"hits": int, "misses": int, "accuracy": float}
    sig_round_finished = Signal(dict)

    def __init__(self, config, stats, parent=None):
        super().__init__(parent)
        self._config = config
        self._stats = stats
        self._state = SixState.IDLE

        # 读取六目标专属配置（不用普通模式的 target_size_px）
        size = self._config.six_target_size_px
        color = self._config.target_color_hex

        # 预创建 6 个飞行目标窗口，连接命中 / 到达信号
        self._targets = [
            FlyingTargetWidget(i, size, color) for i in range(NUM_TARGETS)
        ]
        for t in self._targets:
            t.sig_hit.connect(self._on_hit)
            t.sig_arrived.connect(self._on_arrived)

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

        # 注意：不创建鼠标锁定相关资源（_mouse_lock_timer 等）

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

        记录本轮已用时间并停止倒计时与所有飞行球，便于 resume 续计。
        """
        if self._state != SixState.RUNNING:
            return
        # 记录本轮已用时间，供 resume 续接剩余时间
        self._elapsed_ms = self._round_elapsed.elapsed()
        self._round_timer.stop()
        for t in self._targets:
            t.despawn()
        self._set_state(SixState.PAUSED)

    def resume(self):
        """恢复：PAUSED -> RUNNING。

        重新 spawn 6 球，倒计时续接剩余时间（不重新计整轮）。
        """
        if self._state != SixState.PAUSED:
            return
        self._spawn_all()
        remaining = max(ROUND_DURATION_MS - self._elapsed_ms, 0)
        # 重新启动 elapsed 计时，供下次暂停再续
        self._round_elapsed.start()
        self._round_timer.start(remaining)
        self._set_state(SixState.RUNNING)

    def request_quit(self):
        """请求退出：清场后回 IDLE，确保模式切换后可重新 start()。

        停止倒计时并隐藏所有目标，确保不留残影与悬挂定时器。
        """
        self._round_timer.stop()
        for t in self._targets:
            t.despawn()
        # 清场后回 IDLE，保证可重启
        self._set_state(SixState.IDLE)

    # ---------- 内部状态转换与调度 ----------

    def _begin_round(self):
        """开新一局：清零计分、spawn 6 球、启动倒计时。"""
        self._hits = 0
        self._misses = 0
        self._elapsed_ms = 0
        self._spawn_all()
        self._round_elapsed.start()
        self._round_timer.start(ROUND_DURATION_MS)
        self._set_state(SixState.RUNNING)

    def _spawn_all(self):
        """按配置速度 spawn 全部 6 球。"""
        speed = self._config.six_target_speed
        for t in self._targets:
            t.spawn(speed)

    def _respawn(self, target_id: int):
        """重置单个目标的飞行（命中/到达后调用）。

        仅在 RUNNING 状态下重置，暂停/结束时忽略。
        """
        if self._state != SixState.RUNNING:
            return
        self._targets[target_id].spawn(self._config.six_target_speed)

    def _on_hit(self, target_id: int, reaction_ms: int):
        """命中回调：计 hit 并记录统计，随即重置该球。"""
        if self._state != SixState.RUNNING:
            return
        self._hits += 1
        self._stats.record_six(hit=True, reaction_ms=reaction_ms)
        self._respawn(target_id)

    def _on_arrived(self, target_id: int):
        """到达中心未点击回调：计 miss 并记录统计，随即重置该球。"""
        if self._state != SixState.RUNNING:
            return
        self._misses += 1
        self._stats.record_six(hit=False, reaction_ms=0)
        self._respawn(target_id)

    def _on_round_finished(self):
        """倒计时结束回调：清场、上报结算、置 FINISHED（非瞬态）。

        停留在 FINISHED 等待外部重新调 start() 开始下一轮，
        不自动回 IDLE。
        """
        for t in self._targets:
            t.despawn()
        total = self._hits + self._misses
        accuracy = round(self._hits / total * 100, 1) if total > 0 else 0.0
        result = {
            "hits": self._hits,
            "misses": self._misses,
            "accuracy": accuracy,
        }
        self.sig_round_finished.emit(result)
        self._set_state(SixState.FINISHED)  # 不再回 IDLE

    def _set_state(self, new_state: SixState):
        """更新内部状态并广播变更信号。"""
        self._state = new_state
        self.sig_state_changed.emit(new_state)

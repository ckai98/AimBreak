"""GameController —— 核心控制中枢（状态机引擎）

职责：
    1. 维护 GameState 状态机，拒绝所有非法状态转换；
    2. 连接 Scheduler / TargetWidget / StatsRepository / ConfigManager，
       将"定时触发 -> 显示目标 -> 命中/超时 -> 记录统计 -> 下一轮"
       串接成完整的训练循环；
    3. 对外暴露 start / pause / resume / request_quit 供 TrayManager 调用，
       并通过 sig_state_changed 通知 UI 层同步菜单文本。

设计要点：
    - 所有状态转换方法先校验当前状态，非法转换静默 return；
    - RESULT 为瞬态：命中或超时后立即记录并回到 WAITING，
      不需要外部触发；
    - 依赖均通过构造函数注入，不在本文件 import 具体类，
      避免与 view / infra 层产生循环引用。
"""

import random
from enum import Enum, auto

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication


class GameState(Enum):
    """训练状态枚举。"""
    IDLE = auto()      # 程序启动初始态
    WAITING = auto()   # 等待随机定时器触发
    ACTIVE = auto()    # 小球已显示，等待点击或超时
    RESULT = auto()    # 记录数据，准备下一轮（瞬态）
    PAUSED = auto()    # 暂停（托盘触发）
    EXITING = auto()   # 退出，清理资源


class GameController(QObject):
    """核心控制中枢：状态机引擎。

    依赖通过构造函数注入（避免循环引用）：
        - config:  ConfigManager，提供间隔/尺寸/颜色/存活时间等配置
        - stats:   StatsRepository，记录命中/超时样本
        - scheduler: Scheduler，按随机间隔触发 sig_triggered
        - target_widget: TargetWidget，负责绘制与命中/超时上报
    """

    # 状态变更信号：参数为新的 GameState，供 TrayManager 更新菜单文本等
    sig_state_changed = Signal(object)

    def __init__(self, config, stats, scheduler, target_widget, parent=None):
        super().__init__(parent)
        self._config = config
        self._stats = stats
        self._scheduler = scheduler
        self._target = target_widget
        self._state = GameState.IDLE

        # 用配置初始化调度器的随机间隔范围
        self._scheduler.set_interval_range(
            self._config.min_interval_ms,
            self._config.max_interval_ms,
        )

        # 连接底层信号：定时触发、命中、超时
        self._scheduler.sig_triggered.connect(self._on_triggered)
        self._target.sig_hit.connect(self._on_hit)
        self._target.sig_timeout.connect(self._on_timeout)

    @property
    def state(self) -> GameState:
        """当前状态（只读）。"""
        return self._state

    # ---------- 对外控制接口（供 TrayManager 调用） ----------

    def start(self):
        """启动训练循环：IDLE -> WAITING。

        仅在 IDLE 状态可启动，其他状态静默拒绝。
        """
        if self._state != GameState.IDLE:
            return  # 拒绝非 IDLE 启动
        self._enter_waiting()

    def pause(self):
        """暂停：IDLE/WAITING -> PAUSED。

        停止调度器定时；IDLE 下停止是 no-op，安全。
        """
        if self._state in (GameState.IDLE, GameState.WAITING):
            self._scheduler.stop()
            self._set_state(GameState.PAUSED)

    def resume(self):
        """恢复：PAUSED -> WAITING。"""
        if self._state == GameState.PAUSED:
            self._enter_waiting()

    def request_quit(self):
        """请求退出：清场后回 IDLE，便于模式切换后重启。

        停止调度器并隐藏目标，确保不留残影与悬挂定时器。
        """
        self._scheduler.stop()
        self._target.hide_target()
        self._set_state(GameState.EXITING)
        # 清场后回 IDLE，保证模式切换后可重新 start()
        self._set_state(GameState.IDLE)

    # ---------- 内部状态转换 ----------

    def _enter_waiting(self):
        """进入 WAITING：切换状态并启动调度器安排下一次触发。"""
        self._set_state(GameState.WAITING)
        self._scheduler.start()

    def _on_triggered(self):
        """Scheduler 触发回调：WAITING -> ACTIVE，显示小球。

        防御性校验：只在 WAITING 接受触发（避免暂停/退出后残余信号误触发）。
        """
        if self._state != GameState.WAITING:
            return
        self._set_state(GameState.ACTIVE)
        x, y = self._gen_safe_coord()
        self._target.show_target(
            x, y,
            self._config.target_size_px,
            self._config.target_color_hex,
            self._config.target_lifetime_ms,
        )

    def _on_hit(self, reaction_ms: int):
        """命中回调：ACTIVE -> RESULT -> WAITING。

        记录命中样本（含反应时间），随即进入下一轮等待。
        """
        if self._state != GameState.ACTIVE:
            return
        self._set_state(GameState.RESULT)
        self._stats.record(hit=True, reaction_ms=reaction_ms)
        self._enter_waiting()

    def _on_timeout(self):
        """超时回调：ACTIVE -> RESULT -> WAITING。

        记录超时样本（reaction_ms 计 0），随即进入下一轮等待。
        """
        if self._state != GameState.ACTIVE:
            return
        self._set_state(GameState.RESULT)
        self._stats.record(hit=False, reaction_ms=0)
        self._enter_waiting()

    def _set_state(self, new_state: GameState):
        """更新内部状态并广播变更信号。"""
        self._state = new_state
        self.sig_state_changed.emit(new_state)

    def _gen_safe_coord(self):
        """在主屏 availableGeometry 安全区随机生成小球左上角坐标。

        严格避开任务栏：
            x ∈ [geom.x, geom.right - size]
            y ∈ [geom.y, geom.bottom - size]
        Returns:
            (x, y) 元组，屏幕坐标系。
        """
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return 0, 0
        geom = screen.availableGeometry()
        size = self._config.target_size_px
        x = random.randint(geom.x(), geom.right() - size)
        y = random.randint(geom.y(), geom.bottom() - size)
        return x, y

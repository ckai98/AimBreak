"""随机定时调度器：按随机间隔触发信号，驱动 GameController 切换到 ACTIVE 状态。"""

import random

from PySide6.QtCore import QObject, Signal, QTimer


class Scheduler(QObject):
    """随机间隔调度器。

    工作流程：
      1. Controller 在进入 WAITING 状态时调用 start()，安排一次随机定时；
      2. 定时到达后发出 sig_triggered，Controller 收到后切换到 ACTIVE；
      3. Controller 在 RESULT 结束后再次调用 start()，安排下一轮。

    暂停/恢复语义：
      - stop()：停止当前定时器（不再触发）；
      - start()：重新按随机间隔安排下一次触发。
    """

    # 触发信号：到点通知 Controller 显示小球
    sig_triggered = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # 默认间隔范围：5s ~ 30s
        self._min_ms = 5000
        self._max_ms = 30000
        # 使用单次定时器：触发后不自动续接，由 Controller 决定何时安排下一轮
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)

    def set_interval_range(self, min_ms: int, max_ms: int):
        """设置随机间隔范围（毫秒）。

        要求 0 < min_ms <= max_ms，否则保持原值不变。
        注意：本方法只更新范围，不影响当前正在运行的定时器；
        新范围会在下一次 start() / _arm_next() 时生效。
        """
        if min_ms <= 0 or max_ms < min_ms:
            return
        self._min_ms = min_ms
        self._max_ms = max_ms

    def start(self):
        """启动调度：按随机间隔启动单次定时器。

        若当前已有定时器在运行，会被新的随机间隔覆盖。
        """
        self._arm_next()

    def stop(self):
        """停止调度（暂停）：取消当前定时器，不再触发 sig_triggered。"""
        self._timer.stop()

    def _arm_next(self):
        """按当前范围生成随机间隔并启动单次定时器。"""
        interval = random.randint(self._min_ms, self._max_ms)
        self._timer.start(interval)

    def _on_timeout(self):
        """定时到达回调：发出触发信号。

        不自动安排下一次：是否继续下一轮由 Controller 决定
        （Controller 会在 RESULT 状态结束后显式调用 start()）。
        """
        self.sig_triggered.emit()

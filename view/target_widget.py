"""
TargetWidget —— 目标小球表现层
================================

职责：
    1. 绘制小球（paintEvent）
    2. 管理 QRegion 椭圆蒙版，实现"小球可点击、透明区穿透"
    3. 捕获鼠标点击并上报命中（含反应时间，毫秒整数）
    4. 管理存活倒计时，超时上报 timeout

技术原理：
    - WA_TranslucentBackground：让整个窗口视觉透明（含 alpha 通道）
    - setMask(QRegion.Ellipse)：用蒙版裁剪窗口的"可命中区域"，
      蒙版外的鼠标事件不会派发给本窗口，而是穿透到下层窗口。

本模块仅负责绘制与事件捕获，业务逻辑由 GameController 处理。
"""

from PySide6.QtCore import Qt, Signal, QTimer, QElapsedTimer
from PySide6.QtGui import QPainter, QColor, QRegion, QPen
from PySide6.QtWidgets import QWidget


class TargetWidget(QWidget):
    """目标小球窗口：透明绘制 + 椭圆蒙版命中裁剪。"""

    # 命中：上报反应时间（毫秒整数）
    sig_hit = Signal(int)
    # 超时未点击
    sig_timeout = Signal()

    def __init__(self):
        super().__init__()

        # 1. 无边框 + 置顶 + Tool 类型（不显示在任务栏）
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )

        # 2. 全窗口透明（视觉透明由 paintEvent 自绘内容决定）
        self.setAttribute(Qt.WA_TranslucentBackground)

        # 视觉与尺寸参数（每次 show_target 会刷新）
        self._color = QColor("#FF3B30")
        self._size = 30
        self._lifetime_ms = 2000

        # 3. 存活倒计时：单次触发，超时上报 timeout
        self._lifetime_timer = QTimer(self)
        self._lifetime_timer.setSingleShot(True)
        self._lifetime_timer.timeout.connect(self._on_timeout)

        # 4. 反应时间计时器：从 show_target 起计时，命中时读取 elapsed
        self._elapsed = QElapsedTimer()

        # 注意：不在构造函数里 show()，显示由 show_target 触发

    def show_target(self, x: int, y: int, size: int, color_hex: str, lifetime_ms: int):
        """显示目标并设置可点击蒙版。

        Args:
            x: 目标左上角横坐标（屏幕坐标系）
            y: 目标左上角纵坐标（屏幕坐标系）
            size: 小球直径（像素）
            color_hex: 小球填充颜色（如 "#FF3B30"）
            lifetime_ms: 存活时间（毫秒），超时上报 timeout
        """
        self._size = size
        self._color = QColor(color_hex)
        self._lifetime_ms = lifetime_ms

        self.setGeometry(x, y, size, size)

        # 椭圆蒙版：仅区域内响应鼠标，区域外点击穿透到下层窗口
        self.setMask(QRegion(0, 0, size, size, QRegion.Ellipse))

        self.show()

        # 启动反应计时与存活倒计时
        self._elapsed.start()
        self._lifetime_timer.start(self._lifetime_ms)

    def hide_target(self):
        """隐藏目标并停止计时器。

        供 GameController 在 RESULT 状态主动隐藏时调用。
        clearMask() 在 hide() 之后调用，确保透明区恢复穿透。
        """
        self._lifetime_timer.stop()
        self.hide()
        self.clearMask()

    def paintEvent(self, event):
        """绘制椭圆小球：配置颜色填充 + 白色描边。"""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(self._color)
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.drawEllipse(0, 0, self._size, self._size)

    def mousePressEvent(self, event):
        """点击小球：计算反应时间并上报命中，然后隐藏。

        clearMask() 在 hide() 之后调用，确保透明区恢复穿透。
        """
        reaction_ms = int(self._elapsed.elapsed())
        self._lifetime_timer.stop()
        self.hide()
        self.clearMask()
        self.sig_hit.emit(reaction_ms)

    def _on_timeout(self):
        """存活倒计时触发：隐藏并上报 timeout。

        clearMask() 在 hide() 之后调用，确保透明区恢复穿透。
        """
        self.hide()
        self.clearMask()
        self.sig_timeout.emit()

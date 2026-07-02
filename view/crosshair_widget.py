"""CrosshairWidget —— 视角瞄准模式 v2 的屏幕中心十字准星
================================================

职责：
    1. 全屏透明覆盖层，仅在屏幕几何中心绘制白色十字准星
    2. 鼠标穿透：点击事件不影响下层目标球（WindowTransparentForInput）
    3. 仅由 Controller 在 RUNNING 状态下调用 show_crosshair / hide_crosshair

技术原理：
    - WA_TranslucentBackground：让整个窗口视觉透明（含 alpha 通道）
    - WindowTransparentForInput：让鼠标事件完全穿透到下层窗口，
      与 HudWidget 同方案——全局不接收任何输入，配合视角瞄准模式下
      鼠标锁定屏幕中心、准星固定屏幕中心的交互逻辑。
    - availableGeometry：覆盖主屏幕可用区（排除任务栏），避免遮挡。
    - Tool 类型：不显示在任务栏。

本模块仅负责显示，业务逻辑由 Controller 处理。
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPainter, QColor, QPen
from PySide6.QtWidgets import QWidget


class CrosshairWidget(QWidget):
    """屏幕中心十字准星：全屏透明、鼠标穿透、paintEvent 自绘白色十字。"""

    def __init__(self, parent=None):
        super().__init__(parent)

        # 1. 无边框 + 置顶 + Tool（不显示在任务栏）+ 鼠标穿透
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
        )

        # 2. 全窗口透明（仅 paintEvent 绘制的十字线可见）
        self.setAttribute(Qt.WA_TranslucentBackground)

        self._resize_to_screen()

        # 注意：不在构造函数里 show()，显示由 show_crosshair 触发

    def _resize_to_screen(self):
        """覆盖主屏幕 availableGeometry（排除任务栏区域）。"""
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.setGeometry(screen)

    def paintEvent(self, event):
        """在窗口几何中心绘制白色十字准星。

        水平线 + 垂直线各长 20px、线宽 2px、白色，开启抗锯齿。
        中心点 = (self.width()/2, self.height()/2)。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 白色细线，线宽 2px
        pen = QPen(QColor(255, 255, 255))
        pen.setWidth(2)
        painter.setPen(pen)

        # 几何中心
        cx = self.width() / 2
        cy = self.height() / 2

        # 十字线长 20px：左右 / 上下各延伸 10px
        half = 10
        painter.drawLine(int(cx - half), int(cy), int(cx + half), int(cy))  # 水平线
        painter.drawLine(int(cx), int(cy - half), int(cx), int(cy + half))  # 垂直线

    def show_crosshair(self):
        """显示准星：重新对齐屏幕尺寸后 show。

        show 前重新 resize 是为多显示器/分辨率变更场景兜底。
        """
        self._resize_to_screen()
        self.show()

    def hide_crosshair(self):
        """隐藏准星。"""
        self.hide()

"""MissDetectorWidget —— 六目标训练模式 miss 检测层。

全屏透明背景层，捕获点击非目标区域的事件并发射 sig_miss。
位于目标球之下：目标球用 QRegion.Ellipse 蒙版使椭圆外区域点击穿透到本层，
椭圆内点击由目标球 mousePressEvent 处理（命中），不会触发本层的 miss。

技术原理：
    - WA_TranslucentBackground：让整个窗口视觉透明（含 alpha 通道）
    - 不设 setMask：整个窗口接收点击事件
    - 配合目标球的椭圆蒙版：目标球蒙版外区域点击会穿透到本层，
      蒙版内点击由目标球处理（命中）

z-order：
    本 widget 与目标球均有 WindowStaysOnTopHint，后 show 的会浮在上面。
    main.py 中先 show 本 widget 再 show 目标球即可（或目标球 raise_()）。
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget


class MissDetectorWidget(QWidget):
    """全屏透明 miss 检测层。"""

    sig_miss = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        # 不设 setMask：整个窗口接收点击

    def show_fullscreen(self):
        """覆盖主屏幕并显示。"""
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.setGeometry(screen)
        self.show()

    def mousePressEvent(self, event):
        """点击空白区域 = miss，发射 sig_miss。"""
        self.sig_miss.emit()

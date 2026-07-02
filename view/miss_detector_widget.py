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

视角瞄准模式 v2：
    视角模式下由 ViewportController 统一接管点击命中/miss 判定（鼠标锁定屏幕中心，
    viewport 用自己的全屏透明捕获窗口判断屏幕中心准星是否落在目标渲染椭圆内）。
    通过 set_viewport 注入 viewport 引用后，本层 mousePressEvent 会停用自身的
    sig_miss 上报（避免重复上报），改由 viewport 唯一上报 miss。
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
        # 视角模式 v2：注入 viewport 后由 viewport 统一判定 miss，本层停用自身上报
        self._viewport = None

    def set_viewport(self, viewport):
        """注入 ViewportController 引用。

        注入后视角模式下由 viewport 统一判定 miss，本层 mousePressEvent 不再 emit sig_miss。
        """
        self._viewport = viewport

    def show_fullscreen(self):
        """覆盖主屏幕并显示。"""
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.setGeometry(screen)
        self.show()

    def mousePressEvent(self, event):
        """点击空白区域 = miss，发射 sig_miss。

        视角模式 v2：若已注入 viewport，则由 viewport 统一判定 miss，本层不重复上报。
        """
        if self._viewport is not None:
            return
        self.sig_miss.emit()

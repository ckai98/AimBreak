"""CountdownWidget —— 3-2-1-GO 倒计时开始画面
========================================

职责：
    1. 单局开始前显示 3 秒倒计时（3-2-1-GO），让玩家有准备时间；
    2. 倒计时结束 emit sig_finished，由 SixTargetController 触发 _begin_round；
    3. ESC 取消 emit sig_cancelled，由 SixTargetController 触发 request_quit。

技术要点：
    - 全屏透明覆盖层（WA_TranslucentBackground + FramelessWindowHint + StaysOnTop + Tool）
    - setFocusPolicy(Qt.StrongFocus) + setFocus() + activateWindow() 确保接收键盘事件
    - 无 WindowTransparentForInput：倒计时期间需捕获点击避免误操作，且确保键盘焦点
    - 1s 间隔 QTimer 驱动 3→2→1→GO! 序列
"""

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QPainter, QColor, QFont, QGuiApplication
from PySide6.QtWidgets import QWidget


class CountdownWidget(QWidget):
    """3-2-1-GO 倒计时全屏覆盖层。"""

    # 倒计时完成（GO! 显示后）
    sig_finished = Signal()
    # 倒计时被 ESC 取消
    sig_cancelled = Signal()

    _SEQUENCE = ["3", "2", "1", "GO!"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._screen_rect = None
        self._index = 0

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_tick)

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)

    def set_screen_rect(self, screen_rect):
        """供 SixTargetController 指定训练屏幕（多屏适配）。"""
        self._screen_rect = screen_rect

    def _resize_to_screen(self, screen_rect=None):
        if screen_rect is None:
            if self._screen_rect is not None:
                screen_rect = self._screen_rect
            else:
                screen_rect = QGuiApplication.primaryScreen().availableGeometry()
        self.setGeometry(screen_rect)

    def start_countdown(self, screen_rect=None):
        """开始倒计时：显示 3→2→1→GO!（每数字 1s），结束后 emit sig_finished。"""
        self._resize_to_screen(screen_rect)
        self._index = 0
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self.update()  # 首帧绘制 "3"
        self._timer.start()

    def stop_countdown(self):
        """停止倒计时并隐藏（供 request_quit 在非 ESC 退出时调用）。"""
        self._timer.stop()
        self.hide()

    def _on_tick(self):
        self._index += 1
        if self._index >= len(self._SEQUENCE):
            self._timer.stop()
            self.hide()
            self.sig_finished.emit()
        else:
            self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._timer.stop()
            self.hide()
            self.sig_cancelled.emit()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        if self._index >= len(self._SEQUENCE):
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        text = self._SEQUENCE[self._index]
        font = QFont("Arial", 120, QFont.Bold)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255))
        p.drawText(self.rect(), Qt.AlignCenter, text)

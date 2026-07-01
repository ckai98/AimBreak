"""ResultWidget —— 六目标训练模式局终结算页。

倒计时结束后弹出，展示本轮分数 / 等级 / 命中 / 失误 / 准确率 / 历史最高。
点击或按键关闭，发射 sig_closed，由 main.py/Controller 决定后续（重开下一局）。
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout,
)


def _grade_of(score: int) -> tuple[str, str]:
    """返回 (等级文本, 颜色 hex)。

    Aim Lab 社区标准：
        - score <  80000  : 不及格（灰）
        - score >= 80000  : 及格（绿）
        - score >= 100000 : 优秀（蓝）
        - score >= 130000 : 神仙（金）
    """
    if score >= 130000:
        return "神仙", "#FFD700"
    if score >= 100000:
        return "优秀", "#4A90E2"
    if score >= 80000:
        return "及格", "#34C759"
    return "不及格", "#8E8E93"


class ResultWidget(QWidget):
    """六目标局终结算页：居中无边框卡片，点击/按键关闭后发射 sig_closed。

    复用策略：关闭时仅 hide() 不 destroy，便于下局直接 show_result() 重显。
    """

    sig_closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setFixedSize(440, 380)
        self.setStyleSheet("background: rgba(20,20,30,235); border-radius: 16px;")

        self._title = QLabel("本轮结算")
        self._score = QLabel("0")
        self._grade = QLabel("不及格")
        self._hits = QLabel("命中: 0")
        self._misses = QLabel("失误: 0")
        self._acc = QLabel("准确: -")
        self._best = QLabel("历史最高: 0")
        self._hint = QLabel("点击任意处或按任意键关闭")

        # 样式
        self._title.setStyleSheet("color:white; font-size:20px; font-weight:bold;")
        self._score.setStyleSheet("color:white; font-size:56px; font-weight:bold;")
        self._grade.setStyleSheet("color:#8E8E93; font-size:24px; font-weight:bold;")
        for lbl in (self._hits, self._misses, self._acc):
            lbl.setStyleSheet("color:#CCCCCC; font-size:16px;")
        self._best.setStyleSheet("color:#FFD700; font-size:16px;")
        self._hint.setStyleSheet("color:#888888; font-size:13px;")

        self._title.setAlignment(Qt.AlignCenter)
        self._score.setAlignment(Qt.AlignCenter)
        self._grade.setAlignment(Qt.AlignCenter)
        self._best.setAlignment(Qt.AlignCenter)
        self._hint.setAlignment(Qt.AlignCenter)

        row = QHBoxLayout()
        row.addWidget(self._hits, alignment=Qt.AlignCenter)
        row.addWidget(self._misses, alignment=Qt.AlignCenter)
        row.addWidget(self._acc, alignment=Qt.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 24, 30, 24)
        layout.setSpacing(10)
        layout.addWidget(self._title, alignment=Qt.AlignCenter)
        layout.addWidget(self._score, alignment=Qt.AlignCenter)
        layout.addWidget(self._grade, alignment=Qt.AlignCenter)
        layout.addLayout(row)
        layout.addWidget(self._best, alignment=Qt.AlignCenter)
        layout.addStretch()
        layout.addWidget(self._hint, alignment=Qt.AlignCenter)

    def show_result(self, result: dict, best_score: int):
        """填充并显示结算页。

        Args:
            result: {"hits": int, "misses": int, "accuracy": float, "score": int}
            best_score: 历史最高分（跨日全局），用于展示"历史最高"
        """
        hits = result.get("hits", 0)
        misses = result.get("misses", 0)
        acc = result.get("accuracy", 0.0)
        score = result.get("score", 0)
        grade, color = _grade_of(score)

        self._score.setText(str(score))
        self._grade.setText(grade)
        self._grade.setStyleSheet(f"color:{color}; font-size:24px; font-weight:bold;")
        self._hits.setText(f"命中: {hits}")
        self._misses.setText(f"失误: {misses}")
        self._acc.setText(f"准确: {acc}%")
        self._best.setText(f"历史最高: {best_score}")

        self._center_on_screen()
        self.show()
        self.raise_()

    def _center_on_screen(self):
        """将窗口移动到主屏幕可用区中心。"""
        screen = QGuiApplication.primaryScreen().availableGeometry()
        x = screen.x() + (screen.width() - self.width()) // 2
        y = screen.y() + (screen.height() - self.height()) // 2
        self.move(x, y)

    def mousePressEvent(self, event):
        """点击任意处：隐藏并发射 sig_closed（不 destroy，便于复用）。"""
        self.hide()
        self.sig_closed.emit()

    def keyPressEvent(self, event):
        """按任意键：隐藏并发射 sig_closed。"""
        self.hide()
        self.sig_closed.emit()

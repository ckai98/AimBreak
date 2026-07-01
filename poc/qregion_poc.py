"""
QRegion 蒙版 + WA_TranslucentBackground 穿透方案 POC
====================================================

验证目标：
    在 Windows 上通过 Qt 的 WA_TranslucentBackground + setMask(QRegion)
    实现"透明区域穿透、小球区域可点击"的命中裁剪效果。

技术原理：
    - WA_TranslucentBackground：让整个窗口视觉透明（含 alpha 通道）
    - setMask(QRegion.Ellipse)：用蒙版裁剪窗口的"可命中区域"，
      蒙版外的鼠标事件不会派发给本窗口，而是穿透到下层窗口。

运行方式：
    python poc/qregion_poc.py
"""

import sys

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QGuiApplication, QPainter, QColor, QRegion, QPen
from PySide6.QtWidgets import QWidget, QApplication


class PocBall(QWidget):
    """可点击的红色椭圆小球窗口。"""

    # 退出阈值：点击小球达到此次数后自动关闭
    AUTO_EXIT_HIT_COUNT = 5

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

        # 小球尺寸
        self.size = 60
        self.setGeometry(100, 100, self.size, self.size)

        # 3. 椭圆蒙版：只有小球区域内响应鼠标，其余区域穿透到下层窗口
        self.setMask(QRegion(0, 0, self.size, self.size, QRegion.Ellipse))

        # 让窗口可接收键盘事件（用于 Esc 退出）
        self.setFocusPolicy(Qt.StrongFocus)

        # 视觉状态
        self.hit_color = QColor("#FF3B30")  # 初始红色
        self.hit_count = 0  # 命中计数

        self.show()

    def paintEvent(self, event):
        """绘制椭圆小球：红色填充 + 白色描边。"""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(self.hit_color)
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.drawEllipse(0, 0, self.size, self.size)

    def mousePressEvent(self, event):
        """点击小球：打印坐标、切换颜色、累计计数达到阈值则退出。"""
        pos = event.position()
        self.hit_count += 1
        print(f"命中！点击坐标: ({pos.x():.1f}, {pos.y():.1f})  累计命中: {self.hit_count}/{self.AUTO_EXIT_HIT_COUNT}")

        # 切换颜色作为视觉反馈
        self.hit_color = (
            QColor("#34C759") if self.hit_color.red() > 128 else QColor("#FF3B30")
        )
        self.update()

        # 达到命中阈值后自动退出
        if self.hit_count >= self.AUTO_EXIT_HIT_COUNT:
            print(f"已命中 {self.hit_count} 次，POC 自动退出。")
            self.close()

    def keyPressEvent(self, event):
        """按 Esc 退出。"""
        if event.key() == Qt.Key_Escape:
            print("收到 Esc，POC 退出。")
            self.close()


def main():
    # 高 DPI 处理：PassThrough 保证非整数缩放下坐标精确
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    ball = PocBall()

    print("=" * 60)
    print("QRegion 蒙版 + WA_TranslucentBackground POC 已启动")
    print("=" * 60)
    print("验证步骤：")
    print("  1. 屏幕左上角应出现一个红色椭圆小球（直径 60px）。")
    print("  2. 点击小球：控制台打印坐标，小球颜色在红/绿之间切换。")
    print("  3. 打开记事本/浏览器放到小球下方，验证小球外的透明区域")
    print("     点击能否穿透到下层窗口（这是本次验证重点）。")
    print("  4. 退出方式：按 Esc，或点击小球满 5 次后自动退出。")
    print("=" * 60)
    print("提示：若透明区域点击未穿透，说明 setMask 未生效，")
    print("      需检查是否被全屏其它置顶窗口遮挡或被 Win32 透明样式干扰。")
    print("=" * 60)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

"""ViewportController —— 视角瞄准模式 v2 的视角驱动与点击判定层
================================================

职责：
    1. 全屏透明覆盖层（捕获点击，不穿透），RUNNING 状态下锁定鼠标到屏幕中心；
    2. 每 8ms tick 读取鼠标相对屏幕中心的 delta，反向累积为视角偏移
       (view_dx, view_dy)，并立即把鼠标重置回屏幕中心；
    3. 驱动所有可见目标的 move_to_render_pos，让目标球按"逻辑坐标 + 偏移"渲染；
    4. 点击时统一判定屏幕中心准星是否落在某目标渲染椭圆内：
       命中则 emit sig_crosshair_hit(target_id, reaction_ms)，
       否则 emit sig_crosshair_miss。

技术原理：
    - WA_TranslucentBackground：视觉透明（含 alpha 通道）
    - 不设 WindowTransparentForInput：本窗口必须捕获点击做统一判定
    - ctypes.windll.user32.GetCursorPos / SetCursorPos：读取并重置鼠标位置，
      仅 Windows 可用（与项目目标平台一致）
    - availableGeometry：覆盖主屏幕可用区（排除任务栏），中心点即锁定点
    - 反向累积：场景反向跟随鼠标，模拟"视角移动 = 世界反向平移"

z-order：
    与目标球、CrosshairWidget 均有 WindowStaysOnTopHint，靠 raise_ 维持最上层。
    start() 时把准星与自身提到最上层；bring_to_front() 供 controller 在目标
    raise 后重新把 viewport/准星提到最上层，确保点击始终由 viewport 接管。
"""

import ctypes
from ctypes import wintypes

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget


class ViewportController(QWidget):
    """视角瞄准模式 v2 控制层：鼠标锁定 + 视角偏移 + 中心准星命中判定。"""

    # 命中：(target_id, reaction_ms)
    sig_crosshair_hit = Signal(int, int)
    # 未命中
    sig_crosshair_miss = Signal()

    def __init__(self, targets, crosshair=None, parent=None):
        super().__init__(parent)

        # 受控目标列表（FlyingTargetWidget）
        self._targets = targets
        # 屏幕中心准星（CrosshairWidget），可空
        self._crosshair = crosshair

        # 视角偏移（像素）：逻辑坐标 + 偏移 = 渲染坐标
        self._view_dx = 0.0
        self._view_dy = 0.0

        # tick / 点击守卫：仅在 start 后置 True，stop 后置 False
        self._active = False

        # 1. 无边框 + 置顶 + Tool（不显示在任务栏）；
        #    不加 WindowTransparentForInput：本窗口要捕获点击做统一判定
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )

        # 2. 全窗口透明（视觉透明，点击仍由本窗口接收）
        self.setAttribute(Qt.WA_TranslucentBackground)

        # 3. 8ms tick 定时器：读鼠标 delta、重置鼠标、驱动目标渲染
        self._timer = QTimer(self)
        self._timer.setInterval(8)
        self._timer.timeout.connect(self._tick)

        self._resize_to_screen()
        # 注意：不在构造函数里 show()，显示由 start 触发

    # ---------- 只读属性 ----------

    @property
    def view_dx(self) -> float:
        """当前视角水平偏移（像素）。"""
        return self._view_dx

    @property
    def view_dy(self) -> float:
        """当前视角垂直偏移（像素）。"""
        return self._view_dy

    # ---------- 内部工具 ----------

    def _resize_to_screen(self):
        """覆盖主屏幕 availableGeometry（排除任务栏区域）。"""
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.setGeometry(screen)

    def _tick(self):
        """8ms 核心：读鼠标 delta、反向累积、重置鼠标回中心、驱动目标渲染。

        反向累积：场景反向跟随鼠标，模拟视角移动 = 世界反向平移。
        """
        screen = QGuiApplication.primaryScreen().availableGeometry()
        cx = screen.center().x()
        cy = screen.center().y()

        # 读取鼠标当前位置（屏幕坐标）
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        dx = pt.x - cx
        dy = pt.y - cy

        # 反向累积视角偏移
        self._view_dx -= dx
        self._view_dy -= dy

        # 重置鼠标回屏幕中心，实现"锁定"
        ctypes.windll.user32.SetCursorPos(cx, cy)

        # 驱动所有可见目标按偏移重新渲染
        for t in self._targets:
            if t.isVisible():
                t.move_to_render_pos(self._view_dx, self._view_dy)

    # ---------- 点击判定 ----------

    def mousePressEvent(self, event):
        """统一判定屏幕中心准星是否落在某目标渲染椭圆内。

        遍历可见目标，计算其渲染球心（逻辑坐标 + 偏移）与屏幕中心的距离，
        若落在半径内则计命中并上报反应时间；遍历完无命中则上报 miss。
        """
        if not self._active:
            return

        screen = QGuiApplication.primaryScreen().availableGeometry()
        scx = screen.center().x()
        scy = screen.center().y()

        for t in self._targets:
            if not t.isVisible():
                continue
            # 渲染球心 = 逻辑球心 + 视角偏移
            rcx = t._cx + self._view_dx
            rcy = t._cy + self._view_dy
            r = t._size / 2
            # 圆形命中判定（椭圆蒙版的球即圆形）
            if (scx - rcx) ** 2 + (scy - rcy) ** 2 <= r ** 2:
                reaction_ms = int(t._elapsed.elapsed())
                self.sig_crosshair_hit.emit(t._target_id, reaction_ms)
                return

        # 遍历完无命中
        self.sig_crosshair_miss.emit()

    # ---------- 生命周期 ----------

    def start(self):
        """开始视角瞄准：重置偏移、对齐屏幕、显示并置顶、启动 tick。"""
        self.reset()
        self._resize_to_screen()
        self.show()
        self.raise_()
        if self._crosshair is not None:
            self._crosshair.show_crosshair()
            self._crosshair.raise_()
        self._active = True
        self._timer.start()

    def stop(self):
        """停止视角瞄准：停 tick、隐藏准星与自身、重置偏移。

        重置偏移确保退出/局终/暂停后视角状态干净；resume 会再走 start()
        （内部 reset）重新开始，行为一致。
        """
        self._timer.stop()
        self._active = False
        if self._crosshair is not None:
            self._crosshair.hide_crosshair()
        self.hide()
        self.reset()

    def reset(self):
        """重置视角偏移为零。"""
        self._view_dx = 0.0
        self._view_dy = 0.0

    def bring_to_front(self):
        """把 viewport 与准星提到最上层（供 controller 在目标 raise 后调用）。"""
        self.raise_()
        if self._crosshair is not None:
            self._crosshair.raise_()

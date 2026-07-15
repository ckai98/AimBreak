"""ViewportController —— 视角瞄准模式 v2 的视角驱动与点击判定层
================================================

职责：
    1. 全屏透明覆盖层（捕获点击，不穿透），RUNNING 状态下锁定鼠标到屏幕中心；
    2. 每 8ms tick 读取鼠标相对屏幕中心的 delta，反向累积为视角角度
       (angle_x, angle_y)（弧度），并立即把鼠标重置回屏幕中心；
    3. 驱动所有可见目标的 move_to_render_pos，让目标球按 3D 透视公式渲染；
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
import math
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
    # ESC 键按下：供 controller 退出当前局
    sig_escape_pressed = Signal()

    def __init__(self, targets, crosshair=None, parent=None):
        super().__init__(parent)

        # 受控目标列表（FlyingTargetWidget）
        self._targets = targets
        # 屏幕中心准星（CrosshairWidget），可空
        self._crosshair = crosshair

        # 视角角度（弧度）：逻辑坐标 + 3D 透视偏移 = 渲染坐标
        self._angle_x = 0.0
        self._angle_y = 0.0
        # 焦距（像素）：默认 = 屏幕宽 × 0.8
        self._focal_length = 0.0
        # 屏幕中心与限位角缓存（_resize_to_screen 时更新）
        self._screen_cx = 0
        self._screen_cy = 0
        self._max_angle_x = 0.0
        self._max_angle_y = 0.0
        # 多屏适配：缓存当前训练屏幕区，None 时 _resize_to_screen fallback 主屏
        self._screen_rect = None

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
    def angle_x(self) -> float:
        return self._angle_x

    @property
    def angle_y(self) -> float:
        return self._angle_y

    @property
    def focal_length(self) -> float:
        return self._focal_length

    @property
    def screen_cx(self) -> int:
        return self._screen_cx

    @property
    def screen_cy(self) -> int:
        return self._screen_cy

    # ---------- 内部工具 ----------

    def _resize_to_screen(self, screen_rect=None):
        """覆盖指定屏幕 availableGeometry（排除任务栏区域）。

        screen_rect 为 None 时用缓存（多屏适配），缓存也为 None 时 fallback 主屏。
        """
        if screen_rect is None:
            screen_rect = self._screen_rect
        if screen_rect is None:
            screen_rect = QGuiApplication.primaryScreen().availableGeometry()
        self._screen_rect = screen_rect
        self.setGeometry(screen_rect)
        self._screen_cx = screen_rect.center().x()
        self._screen_cy = screen_rect.center().y()
        self._focal_length = screen_rect.width() * 0.8
        self._max_angle_x = math.atan((screen_rect.width() / 2) * 0.85 / self._focal_length)
        self._max_angle_y = math.atan((screen_rect.height() / 2) * 0.85 / self._focal_length)

    def set_screen_rect(self, screen_rect):
        """供 SixTargetController 在 _begin_round 时指定训练屏幕。

        内部会转发给 crosshair，确保准星跟随同一屏幕。
        """
        self._resize_to_screen(screen_rect)
        if self._crosshair is not None:
            self._crosshair.set_screen_rect(screen_rect)

    def compute_render_pos(self, cx: float, cy: float):
        """计算逻辑坐标 (cx, cy) 在当前视角下的渲染坐标。

        3D 透视公式：render = screen_center + (logical - screen_center) - focal × tan(angle)
        距屏幕中心越远的球偏移越大，产生 FPS 透视感。
        本方法是渲染与命中判定的唯一公式来源，确保两者完全一致。
        """
        rcx = self._screen_cx + (cx - self._screen_cx) - self._focal_length * math.tan(self._angle_x)
        rcy = self._screen_cy + (cy - self._screen_cy) - self._focal_length * math.tan(self._angle_y)
        return rcx, rcy

    def _tick(self):
        """8ms 核心：读鼠标 delta → 角度累积 → clamp 限位 → 重置鼠标 → 驱动目标渲染。

        健壮性（B2）：ctypes 鼠标调用各自保护，且整体包一层异常兜底，
        任何失败均解除模态并隐藏覆盖层，提供独立 kill 路径，杜绝视角模式软锁。
        """
        try:
            cx = self._screen_cx
            cy = self._screen_cy

            pt = wintypes.POINT()
            try:
                ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            except (AttributeError, OSError):
                # 鼠标读取失败：解除模态、隐藏覆盖层，提供独立退出路径
                self.stop()
                return
            dx = pt.x - cx
            dy = pt.y - cy

            # 1px 死区过滤：避免 SetCursorPos 重置后下一帧残留 1-2px 误差导致轻微漂移
            if abs(dx) <= 1 and abs(dy) <= 1:
                return

            # 鼠标 delta 转角度 delta（弧度），反向累积模拟视角反向平移
            d_angle_x = dx / self._focal_length
            d_angle_y = dy / self._focal_length
            self._angle_x -= d_angle_x
            self._angle_y -= d_angle_y

            # 限位：视角不超过 max_angle，防止球移出屏幕
            self._angle_x = max(-self._max_angle_x, min(self._max_angle_x, self._angle_x))
            self._angle_y = max(-self._max_angle_y, min(self._max_angle_y, self._angle_y))

            try:
                ctypes.windll.user32.SetCursorPos(cx, cy)
            except (AttributeError, OSError):
                # 鼠标重置失败：解除模态、隐藏覆盖层，提供独立退出路径
                self.stop()
                return

            # 驱动所有可见目标按 3D 透视公式重新渲染
            for t in self._targets:
                if t.isVisible():
                    rcx, rcy = self.compute_render_pos(t._cx, t._cy)
                    t.move_to_render_pos(rcx, rcy)
        except Exception:
            # 未预期异常（如焦距为 0 的除零、渲染计算异常等）：
            # 解除模态、隐藏覆盖层，作为独立 kill 路径，防止事件循环卡死/软锁
            self.stop()
            return

    # ---------- 点击判定 ----------

    def mousePressEvent(self, event):
        """统一判定屏幕中心准星是否落在某目标渲染椭圆内。

        遍历可见目标，通过 compute_render_pos 计算其渲染球心与屏幕中心的距离，
        若落在半径内则计命中并上报反应时间；遍历完无命中则上报 miss。
        """
        if not self._active:
            return

        scx = self._screen_cx
        scy = self._screen_cy

        for t in self._targets:
            if not t.isVisible():
                continue
            rcx, rcy = self.compute_render_pos(t._cx, t._cy)
            r = t._size / 2
            # 圆形命中判定（椭圆蒙版的球即圆形）
            if (scx - rcx) ** 2 + (scy - rcy) ** 2 <= r ** 2:
                reaction_ms = int(t._elapsed.elapsed())
                self.sig_crosshair_hit.emit(t._target_id, reaction_ms)
                return

        # 遍历完无命中
        self.sig_crosshair_miss.emit()

    def keyPressEvent(self, event):
        """监听 ESC 键，emit sig_escape_pressed 供 controller 退出当前局。"""
        if event.key() == Qt.Key_Escape:
            self.sig_escape_pressed.emit()
            return
        super().keyPressEvent(event)

    # ---------- 生命周期 ----------

    def start(self):
        """开始视角瞄准：对齐屏幕、显示并置顶、启动 tick。

        注意：本方法不再调用 reset()。偏移重置由调用方在 _begin_round 显式触发，
        以保证 pause/resume 之间视角偏移可续接（暂停不归零，仅在新局开始时归零）。
        """
        self._resize_to_screen()
        self.show()
        self.raise_()
        if self._crosshair is not None:
            self._crosshair.show_crosshair()
            self._crosshair.raise_()
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFocus()
        self.setWindowModality(Qt.ApplicationModal)
        self._active = True
        self._timer.start()

    def stop(self):
        """停止视角瞄准：停 tick、隐藏准星与自身。

        幂等：若已停止则直接返回，避免重复 hide / 重复 emit 副作用。
        不重置偏移：保证 resume 时视角可续接暂停前的状态；下一局 _begin_round
        会显式调用 reset() 归零。
        """
        if not self._active:
            return
        self.setWindowModality(Qt.NonModal)
        self._timer.stop()
        self._active = False
        if self._crosshair is not None:
            self._crosshair.hide_crosshair()
        self.hide()

    def reset(self):
        """重置视角角度为零。"""
        self._angle_x = 0.0
        self._angle_y = 0.0

    def bring_to_front(self):
        """把 viewport 与准星提到最上层（供 controller 在目标 raise 后调用）。"""
        self.raise_()
        if self._crosshair is not None:
            self._crosshair.raise_()

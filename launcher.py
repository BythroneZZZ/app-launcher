# -*- coding: utf-8 -*-
"""
桌面启动器 · Steam 大屏幕风格
  · 半屏主视觉：256px 大图标 + 焦点主色辉光 + 44px 标题
  · 深色玻璃卡片：主色只出现在图标辉光 / 标题色条 / 悬停晕染（S≤0.45）
  · 货架 = 底部横滑轨道（滚轮平滑惯性 + 边缘渐隐）
扫描开始菜单 / 桌面快捷方式与 UWP/商店应用（多线程并行提取图标，冷启动快）：
  · 左键点击卡片      → 启动应用（启动后自动收进托盘）
  · 右键卡片 / 空白处  → 启动·移除·隐藏 / 添加·管理
  · Esc 最小化（管理模式先退出）· 方向键移动焦点 · Enter 启动
  · 托盘常驻 · Ctrl+Q / Alt+F4 退出
用法:
  python launcher.py              全屏启动
  python launcher.py --windowed   窗口模式（调试）
  python launcher.py --autostart  写入开机自启快捷方式
依赖: pip install PySide6 pywin32
"""
import ctypes
import html
import logging
import math
import os
import random
import shutil
import sys
import time
from datetime import datetime

from store import (load_custom_store, save_custom_store, prune_recent,
                   CACHE_DIR)
from PySide6.QtCore import (Qt, QTimer, QEvent, Property, QPoint, QPointF,
                            QRectF, QEasingCurve, QPropertyAnimation, QParallelAnimationGroup,
)
from PySide6.QtGui import (QColor, QFont, QIcon, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QRadialGradient, QBrush)
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QScrollArea, QSystemTrayIcon, QVBoxLayout, QWidget,
                               QGraphicsOpacityEffect, QMenu, QFileDialog)
from PySide6.QtNetwork import QLocalServer, QLocalSocket

# 扫描逻辑在 scan.py（独立模块，可单独测试）；以下为 launcher 需要的 re-export
from scan import (ScanWorker, AddWorker, build_uwp_app, enumerate_uwp_apps, uwp_icon_image,      # noqa: F401
                  resolve_lnk, JUNK, UWP_ENABLED, UWP_CAT,   # noqa: F401
                  muted_tint, _trim_icon_border,             # noqa: F401
                  ICON_DIR)                                  # noqa: F401

try:
    import pythoncom
    import win32com.client
    HAVE_COM = True
except Exception:
    HAVE_COM = False

# ============================================================
# 日志（滚动文件 + 未捕获异常钩子；pythonw 自启时控制台输出会丢失，这是唯一排障通道）
# ============================================================
def _setup_logging():
    try:
        log_dir = os.path.join(CACHE_DIR, 'logs')
        os.makedirs(log_dir, exist_ok=True)
        from logging.handlers import RotatingFileHandler
        handler = RotatingFileHandler(os.path.join(log_dir, 'app.log'),
                                      maxBytes=512 * 1024, backupCount=2, encoding='utf-8')
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                            handlers=[handler])
    except Exception:
        logging.basicConfig(level=logging.INFO)

    def _hook(t, v, tb):
        logging.critical('未捕获异常: %s: %s', t.__name__, v, exc_info=(t, v, tb))
        sys.__excepthook__(t, v, tb)
    sys.excepthook = _hook

_setup_logging()
SINGLETON_KEY = 'AppLauncher.SingleInstance'      # 本地 IPC 名（唤起已有实例）
_SINGLETON_MUTEX = 'Local\\AppLauncher.SingleInstance'

def _acquire_single_instance():
    """命名互斥锁：进程存活期间持有。返回 False = 已有实例在运行。"""
    ctypes.windll.kernel32.CreateMutexW(None, False, _SINGLETON_MUTEX)
    return ctypes.windll.kernel32.GetLastError() != 183   # ERROR_ALREADY_EXISTS

def _activate_running_instance():
    """连接已运行实例的本地 IPC，发送 show 指令唤起其窗口。"""
    try:
        sock = QLocalSocket()
        sock.connectToServer(SINGLETON_KEY)
        ok = sock.waitForConnected(300)
        logging.info('IPC client: connected=%s state=%s', ok, sock.state())
        if not ok:
            return False
        sock.write(b'show\n')
        sock.flush()
        sock.waitForBytesWritten(300)
        # 不能立刻断开：管道里未读数据会随断开丢弃。
        # 生产几何下服务端进程有独立事件循环，会自行读取并断开
        deadline = time.time() + 1.0
        while sock.state() == QLocalSocket.ConnectedState and time.time() < deadline:
            sock.waitForReadyRead(50)
        sock.disconnectFromServer()
        return True
    except Exception:
        return False

# ============================================================
# 日志（滚动文件 + 未捕获异常钩子；pythonw 自启时控制台输出会丢失，这是唯一排障通道）
# ============================================================
from theme import (CW, CH, GUTTER, GAP, PAD, BAR_H,
                   DUR_FAST, DUR_BASE, DUR_SLOW,
                   CLICK_DEDUPE, HOVER_CONFIRM,
                   R_SM, R_MD, R_XL, ACCENT,
                   FONT_UI, FONT_MONO,
                   FS_POSTER, FS_TRAY, FS_HERO, FS_CLOCK, FS_SUB, FS_BODY,
                   FS_HINT, FS_META, FS_BADGE, FS_CHIP,
                   ACCENT2, BG_BASE, BG_TOP, CARD_TOP, CARD_BOT, POSTER_BG,
                   HERO_TOP, HERO_BOT, INK,
                   TEXT, TEXT_SOFT, DIM, NAV_TEXT, EMPTY_TEXT, HIGH_BLUE,
                   CHIP_BG, SKEL_BG, RED, RED_SOFT, KB_BG, KB_BORDER, WHITE, BLACK,
                   FOCUS_RING,
                   ACCENT_RGB, WHITE_RGB, HERO_RGB, HERO_RGB_B,
                   TOAST_RGB, RED_RGB, rgba)
_ANIMS = {}


def qc(hex_color, alpha=255):
    """色板 token 的带透明度变体：qc(INK, 150) -> QColor('#090c12',150)"""
    c = QColor(hex_color)
    c.setAlpha(alpha)
    return c


def _client_area_animation_enabled():
    """Windows「减少动画」辅助功能开关（SPI_GETCLIENTAREAANIMATION）"""
    try:
        enabled = ctypes.c_int(1)
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0)
        return bool(enabled.value)
    except Exception:
        return True


ANIM_ENABLED = _client_area_animation_enabled()
AL_QML = os.environ.get('AL_QML', '0') == '1'      # QML GPU 背景层（实验性）
if not ANIM_ENABLED:               # 尊重系统设置：动效时长归零（仅保留必要的活动指示）
    DUR_FAST = DUR_BASE = DUR_SLOW = 0

def stop_card_anim(card):
    a = _ANIMS.pop(card, None)
    if a:
        a.stop()
        a.deleteLater()

def move_card(card, x, y, rot, delay, dur, ease, scale=None):
    stop_card_anim(card)
    grp = QParallelAnimationGroup(card)
    a1 = QPropertyAnimation(card, b'pos')
    a1.setDuration(dur)
    a1.setStartValue(card.pos())
    a1.setEndValue(QPoint(int(x), int(y)))
    a1.setEasingCurve(ease)
    grp.addAnimation(a1)
    a2 = QPropertyAnimation(card, b'rotation')
    a2.setDuration(dur)
    a2.setStartValue(card.rotation)
    a2.setEndValue(float(rot))
    a2.setEasingCurve(QEasingCurve.OutCubic)
    grp.addAnimation(a2)
    if scale is not None:
        a3 = QPropertyAnimation(card, b'card_scale')
        a3.setDuration(dur)
        a3.setStartValue(card.card_scale)
        a3.setEndValue(float(scale))
        a3.setEasingCurve(QEasingCurve.OutCubic)
        grp.addAnimation(a3)
    _ANIMS[card] = grp

    def _cleanup():
        if _ANIMS.get(card) is grp:
            _ANIMS.pop(card, None)
        grp.deleteLater()

    def _start():
        if _ANIMS.get(card) is grp:
            grp.finished.connect(_cleanup)
            grp.start()

    # 一律经事件循环启动：避免在信号调用栈内启动动画被挂起的布局处理冻结
    QTimer.singleShot(delay, _start)

# ============================================================
# 细噪点 tile（背景质感用，预生成一次）
# ============================================================
_NOISE_TILE = None
def noise_tile():
    global _NOISE_TILE
    if _NOISE_TILE is None:
        n = 256                                   # 256²：大屏平铺不易察觉重复纹理
        buf = bytearray(n * n * 4)                # bytearray 直填，避免 65536 次 setPixel
        r = random.Random(20261108)
        i = 0
        for _ in range(n * n):
            if r.random() < 0.42:
                v = r.randint(90, 220)
                buf[i] = v; buf[i + 1] = v; buf[i + 2] = v; buf[i + 3] = 10
            i += 4
        img = QImage(bytes(buf), n, n, n * 4, QImage.Format_ARGB32)
        _NOISE_TILE = QPixmap.fromImage(img)
    return _NOISE_TILE

# ============================================================
# 卡片（深色玻璃 + 克制主色）
# ============================================================
class Card(QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setFixedSize(CW, CH)
        self.setCursor(Qt.PointingHandCursor)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setFocusPolicy(Qt.NoFocus)
        self._hover = False
        self._rot = 0.0
        self._scale = 1.0
        self._scale_anim = None
        self._launching = False
        self._spin = 0
        self.focused = False
        self._recent = False
        self._face = None
        self._last_click = 0.0
        self._icon_scale = 1.0
        self._chip_hover = False
        self._icon_anim = None
        self._edit_selected = False          # 管理模式多选标记
        self.setMouseTracking(True)        # 无按键也接收移动事件 → 图标区悬停动效
        tm = muted_tint(app['tint'])
        self.tintm = tm.name()

    def get_rot(self):
        return self._rot

    def set_rot(self, v):
        self._rot = v
        self.update()

    rotation = Property(float, get_rot, set_rot)

    def get_scale(self):
        return self._scale

    def set_scale(self, v):
        self._scale = v
        self.update()

    card_scale = Property(float, get_scale, set_scale)

    def get_icon_scale(self):
        return self._icon_scale

    def set_icon_scale(self, v):
        self._icon_scale = v
        self.update()               # 图标在 paintEvent 叠加绘制，无需重渲染整张卡面

    icon_scale = Property(float, get_icon_scale, set_icon_scale)

    def _animate_icon_scale(self, target):
        if abs(self._icon_scale - target) < 0.003:
            return
        if not ANIM_ENABLED or DUR_FAST <= 0:
            self.set_icon_scale(target)
            return
        if self._icon_anim is None:
            self._icon_anim = QPropertyAnimation(self, b'icon_scale', self)
            self._icon_anim.setDuration(DUR_FAST)
            self._icon_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._icon_anim.stop()
        self._icon_anim.setStartValue(self._icon_scale)
        self._icon_anim.setEndValue(float(target))
        self._icon_anim.start()

    def mouseMoveEvent(self, e):
        over = QRectF(11, 11, 48, 48).contains(e.position())
        if over != self._chip_hover:
            self._chip_hover = over
            self._animate_icon_scale(1.16 if over else 1.0)
            self._face = None
            self.update()
        super().mouseMoveEvent(e)

    def animate_scale(self, target):
        """180ms 档缩放过渡（焦点/悬停反馈），复用同一动画实例"""
        if abs(self._scale - target) < 0.003:
            return
        if self._scale_anim is None:
            self._scale_anim = QPropertyAnimation(self, b'card_scale', self)
            self._scale_anim.setDuration(DUR_FAST)
            self._scale_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._scale_anim.stop()
        self._scale_anim.setStartValue(self._scale)
        self._scale_anim.setEndValue(float(target))
        self._scale_anim.start()

    def enterEvent(self, e):
        self._hover = True
        w = self.window()
        if hasattr(w, 'on_card_hover'):
            w.on_card_hover(self)
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        if self._chip_hover:               # 鼠标快速划出时补一次复位
            self._chip_hover = False
            self._animate_icon_scale(1.0)
            self._face = None
        w = self.window()
        if hasattr(w, 'on_card_leave'):
            w.on_card_leave(self)
        self.update()
        super().leaveEvent(e)

    def set_launching(self, on):
        self._launching = on
        w = self.window()
        if hasattr(w, 'on_card_launching'):
            w.on_card_launching(self, on)
        self.update()

    def set_recent(self, on):
        if self._recent != on:
            self._recent = on
            self.update()

    def release_face(self):
        self._face = None

    def mouseReleaseEvent(self, e):
        win = self.window()
        if getattr(win, 'edit_mode', False):
            if QRectF(self.width() - 30, 5, 24, 24).contains(e.position()):
                if hasattr(win, 'remove_card'):
                    win.remove_card(self)
                e.accept()
                return
            # 管理模式：点击卡片主体 → 切换选中态（批量操作基础）
            self._edit_selected = not self._edit_selected
            self.update()
            if hasattr(win, '_on_edit_selection_changed'):
                win._on_edit_selection_changed()
            e.accept()
            return
        e.ignore()

    def _render_face(self):
        dpr = self.devicePixelRatioF()
        pm = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        w, h = self.width(), self.height()
        fh = h - 8                      # 底部预留 8px 阴影带
        rect = QRectF(0.5, 0.5, w - 1, fh - 0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, R_MD, R_MD)
        p.setClipPath(path)

        # 深色玻璃底
        g = QLinearGradient(0, 0, 0, fh)
        g.setColorAt(0.0, QColor(CARD_TOP))
        g.setColorAt(1.0, QColor(CARD_BOT))
        p.fillPath(path, QBrush(g))
        hg = QLinearGradient(0, 0, w * 0.7, fh * 0.5)
        hg.setColorAt(0.0, qc(WHITE, 14))
        hg.setColorAt(1.0, qc(WHITE, 0))
        p.fillRect(QRectF(0, 0, w, fh), QBrush(hg))

        # 图标辉光（主色去处 1）：悬停图标区时增强
        chip_cx, chip_cy = 11 + 24, 11 + 24
        rg = QRadialGradient(chip_cx, chip_cy, 40 if not self._chip_hover else 56)
        rg.setColorAt(0.0, QColor(self.tintm))
        c = QColor(self.tintm)
        c.setAlpha(150 if self._chip_hover else 95)
        rg.setColorAt(0.55, c)
        c.setAlpha(0)
        rg.setColorAt(1.0, c)
        p.save()
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.setClipPath(path)
        p.fillRect(QRectF(0, 0, 120, 120), QBrush(rg))
        p.restore()

        # 图标芯片（48px：作为启动器，图标是主角）
        chip = QRectF(11, 11, 48, 48)
        cpath = QPainterPath()
        cpath.addRoundedRect(chip, R_SM + 1, R_SM + 1)
        p.fillPath(cpath, QColor(CHIP_BG))
        p.setPen(QPen(qc(WHITE, 28), 1))
        p.drawPath(cpath)
        # 图标/首字母改由 paintEvent 叠加绘制（_icon_scale 缩放不再触发整卡面重渲染）
        # 名称 + 主色小条（主色去处 2）+ 元信息（锚定卡面底部 fh）
        f = QFont(FONT_UI)
        f.setPixelSize(FS_BODY)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor(TEXT))
        fm = p.fontMetrics()
        name = fm.elidedText(self.app['name'], Qt.ElideRight, w - 24)
        p.drawText(QRectF(12, fh - 38, w - 24, 20), Qt.AlignLeft | Qt.AlignVCenter, name)
        bar = QPainterPath()
        bar.addRoundedRect(QRectF(13, fh - 12.5, 22, 3), 1.5, 1.5)
        p.fillPath(bar, QColor(self.tintm))
        f2 = QFont(FONT_UI)
        f2.setPixelSize(FS_META)
        p.setFont(f2)
        p.setPen(QColor(DIM))
        meta = self.app['cat'] + (' · ' + self.app['mtime'] if self.app.get('mtime') else '')
        p.drawText(QRectF(42, fh - 18, w - 54, 14), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(meta, Qt.ElideRight, w - 54))
        p.end()
        self._face = pm

    def _draw_icon_glyph(self, p):
        """在卡面上叠加图标/首字母（paintEvent 调用，受 _icon_scale 缩放控制）"""
        pm32 = self.app.get('pm_small')
        if pm32 is not None and not pm32.isNull():
            isz = 40.0 * self._icon_scale
            iw, ih = pm32.width(), pm32.height()
            dw, dh = isz * iw / 40.0, isz * ih / 40.0
            dx = 11 + (48 - dw) / 2.0
            dy = 11 + (48 - dh) / 2.0
            p.drawPixmap(int(round(dx)), int(round(dy)),
                         max(1, int(round(dw))), max(1, int(round(dh))), pm32)
        else:
            f3 = QFont(FONT_UI)
            f3.setPixelSize(int(FS_CHIP * self._icon_scale))
            f3.setBold(True)
            p.setFont(f3)
            p.setPen(QColor(self.tintm))
            p.drawText(QRectF(11, 11, 48, 48), Qt.AlignCenter,
                       (self.app['name'] or '?')[0].upper())

    def _tick_spin(self):
        self._spin = (self._spin + 9) % 360
        if self._launching:
            self.update()

    def paintEvent(self, _ev):
        if self._face is None:
            self._render_face()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        sc = self._scale
        lift = 4.0 * max(0.0, min(1.0, (sc - 1.0) / 0.06))
        p.translate(self.width() / 2, self.height() / 2)
        p.rotate(self._rot)
        p.scale(sc, sc)
        p.translate(-self.width() / 2, -self.height() / 2)

        # 动态阴影：随缩放加深、下移（实体卡质感）
        sh_alpha = max(42, min(150, int(42 + 1900 * (sc - 1.0))))
        sh = QPainterPath()
        sh.addRoundedRect(QRectF(2, 5 + 2.5 * (sc - 1.0) / 0.06, self.width() - 4, self.height() - 3), R_MD, R_MD)
        p.fillPath(sh, qc(BLACK, sh_alpha))
        if self._hover and not self._launching:
            p.translate(0, -lift)
        p.drawPixmap(0, 0, self._face)
        self._draw_icon_glyph(p)       # 图标层独立叠加（_icon_scale 变化不再触发整卡面重渲染）

        w, h = self.width(), self.height()
        fh = h - 8
        rect = QRectF(0.5, 0.5, w - 1, fh - 0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, R_MD, R_MD)
        if self.focused:
            # 主色外柔光 + 白描边（6px：减少向卡内侵蚀，不再压住图标辉光边缘）
            p.setPen(QPen(QColor(self.tintm), 6))
            p.drawRoundedRect(rect, R_MD, R_MD)
            p.setPen(QPen(qc(FOCUS_RING, 235), 2))
            p.drawRoundedRect(rect, R_MD, R_MD)
        win = self.window()
        if getattr(win, 'edit_mode', False) and self._edit_selected:
            # 管理模式选中态：主色描边
            p.setPen(QPen(QColor(ACCENT), 3))
            p.drawRoundedRect(rect, R_MD, R_MD)
        elif self._hover:
            # 悬停晕染（主色去处 3）：12% 主色罩 + 同色描边
            p.setOpacity(0.12)
            p.fillPath(path, QColor(self.tintm))
            p.setOpacity(1.0)
            p.setPen(QPen(QColor(self.tintm), 1))
            p.drawRoundedRect(rect, R_MD, R_MD)
        else:
            p.setPen(QPen(qc(WHITE, 16), 1))
            p.drawRoundedRect(rect, R_MD, R_MD)
        win = self.window()
        if getattr(win, 'edit_mode', False):
            xb = QRectF(w - 30, 5, 24, 24)
            xcircle = QPainterPath()
            xcircle.addEllipse(xb)
            p.fillPath(xcircle, QColor(RED))
            p.setPen(QPen(QColor(WHITE), 2))
            cx, cy = w - 18, 17
            p.drawLine(QPointF(cx - 4.5, cy - 4.5), QPointF(cx + 4.5, cy + 4.5))
            p.drawLine(QPointF(cx - 4.5, cy + 4.5), QPointF(cx + 4.5, cy - 4.5))

        if self._recent and not getattr(win, 'edit_mode', False):
            tag = QPainterPath()
            tag.addRoundedRect(QRectF(w - 46, 9, 36, 17), 8, 8)
            p.fillPath(tag, QColor(self.tintm))
            p.setPen(QColor(CHIP_BG))
            f4 = QFont(FONT_UI)
            f4.setPixelSize(FS_BADGE)
            f4.setBold(True)
            p.setFont(f4)
            p.drawText(QRectF(w - 46, 9, 36, 17), Qt.AlignCenter, '最近')
        if self._launching:
            p.setClipping(True)
            p.setClipPath(path)
            p.fillPath(path, qc(INK, 150))
            p.setPen(QPen(qc(WHITE, 40), 2.4))
            r = 11.0
            cx, cy = w / 2, h / 2
            p.drawArc(QRectF(cx - r, cy - r, 2 * r, 2 * r), self._spin * 16, 100 * 16)

# ============================================================
# 骨架加载卡（扫描期 shimmer 占位）
# ============================================================
class SkeletonCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(CW, CH)
        self._t = 0.0

    def tick(self):
        self._t = (self._t + 0.06) % 1.0
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), R_MD, R_MD)
        p.setClipPath(path)
        p.fillPath(path, QColor(SKEL_BG))
        band_x = -w * 0.4 + (w * 1.8) * self._t
        g = QLinearGradient(band_x - 60, 0, band_x + 60, 0)
        g.setColorAt(0.0, qc(WHITE, 0))
        g.setColorAt(0.5, qc(WHITE, 16))
        g.setColorAt(1.0, qc(WHITE, 0))
        p.fillRect(self.rect(), QBrush(g))
        p.setPen(Qt.NoPen)
        p.setBrush(qc(WHITE, 14))
        p.drawRoundedRect(QRectF(11, 11, 34, 34), 9, 9)
        p.drawRoundedRect(QRectF(12, h - 40, w * 0.55, 12), 4, 4)
        p.drawRoundedRect(QRectF(12, h - 22, w * 0.38, 9), 4, 4)

# ============================================================
# 货架画布（底部横滑轨道）
# ============================================================
class Canvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.cards = []
        self.setStyleSheet('background:transparent;')

    def add_cards(self, cards):
        for c in cards:
            c.setParent(self)
            if not c.isHidden():       # 尊重筛选时预设的可见性
                c.show()
            self.cards.append(c)
        self.reflow(animate=False)

    def visible_cards(self):
        return [c for c in self.cards if not c.isHidden()]

    def reflow(self, animate=True):
        vis = self.visible_cards()
        n = len(vis)
        self.setFixedSize(PAD + n * (CW + GAP) + GAP, CH + PAD * 2)
        vp = self.window().shelf.viewport().width() if hasattr(self.window(), 'shelf') else self.width()
        sx = self.window().shelf.horizontalScrollBar().value() if hasattr(self.window(), 'shelf') else 0
        for i, card in enumerate(vis):
            x = PAD + i * (CW + GAP)
            # 视口外 ±1 屏之外的卡释放预渲染卡面（滚回时惰性重建）
            if x + CW < sx - CW * 4 or x > sx + vp + CW * 4:
                card.release_face()
            if animate:
                move_card(card, x, PAD, 0, min(i * 6, 180), DUR_BASE, QEasingCurve.OutCubic, scale=1.0)
            else:
                stop_card_anim(card)
                card.set_rot(0)
                card.set_scale(1.0)
                card.move(int(x), PAD)
        self.update()
        w = self.window()
        if hasattr(w, '_update_edge_fades'):
            w._update_edge_fades()

# ============================================================
# Hero 主视觉（半屏）与海报
# ============================================================
class HeroPoster(QWidget):
    def __init__(self):
        super().__init__()
        self.app = None
        self._fade = 1.0
        self._fade_anim = None

    def get_fade(self):
        return self._fade

    def set_fade(self, v):
        self._fade = v
        self.update()

    poster_fade = Property(float, get_fade, set_fade)

    def set_app(self, app):
        if app is self.app:
            return
        self.app = app
        if not ANIM_ENABLED or DUR_BASE <= 0:
            self._fade = 1.0               # 零时长动画不会触发赋值，直接置终值
            self.update()
            return
        if self._fade_anim is None:
            self._fade_anim = QPropertyAnimation(self, b'poster_fade', self)
            self._fade_anim.setDuration(DUR_BASE)
            self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._fade_anim.stop()
        self._fade_anim.setStartValue(0.25)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        w, h = self.width(), self.height()
        tm = muted_tint(QColor(self.app['tint'])) if self.app else QColor(ACCENT)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), R_XL, R_XL)
        p.fillPath(path, qc(POSTER_BG, 235))
        # 主色径向光晕（画在深色底之上，裁剪进圆角）
        p.save()
        p.setClipPath(path)
        rg = QRadialGradient(w / 2, h / 2, w * 0.62)
        c = QColor(tm)
        c.setAlpha(95)
        rg.setColorAt(0.0, c)
        c2 = QColor(tm)
        c2.setAlpha(0)
        rg.setColorAt(1.0, c2)
        p.fillRect(self.rect(), QBrush(rg))
        p.restore()
        p.setPen(QPen(qc(WHITE, 26), 1))
        p.drawPath(path)
        pm_big = self.app.get('pm_big') if self.app else None
        p.setOpacity(max(0.2, self._fade))
        if pm_big is not None and not pm_big.isNull():
            s = 156
            p.drawPixmap(int((w - s) / 2), int((h - s) / 2), s, s, pm_big)
        else:
            p.setPen(QColor(tm))
            f = QFont(FONT_UI)
            f.setPixelSize(FS_POSTER)
            f.setBold(True)
            p.setFont(f)
            nm = (self.app['name'] or '?') if self.app else '?'
            p.drawText(self.rect(), Qt.AlignCenter, nm[0].upper())

class Hero(QWidget):
    def __init__(self):
        super().__init__()
        self.app = None
        self.setStyleSheet('background:transparent;')

    def set_app(self, app):
        if app is self.app:
            return
        self.app = app
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        w, h = self.width(), self.height()
        # 底部与整体融合的渐变（压暗取半：避免多层叠加把画面压灰）
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0.0, qc(HERO_TOP, 0))
        g.setColorAt(0.35, qc(HERO_TOP, 75))
        g.setColorAt(1.0, qc(HERO_BOT, 118))
        p.fillRect(self.rect(), QBrush(g))
        if self.app is None:
            return
        tm = muted_tint(QColor(self.app['tint']))
        # 焦点主色大辉光（左侧海报之后）
        rg = QRadialGradient(w * 0.24, h * 0.52, h * 1.15)
        c = QColor(tm)
        c.setAlpha(46)
        rg.setColorAt(0.0, c)
        c.setAlpha(0)
        rg.setColorAt(1.0, c)
        p.fillRect(self.rect(), QBrush(rg))
        # 左侧文字区压暗
        lg = QLinearGradient(0, 0, w, 0)
        lg.setColorAt(0.0, qc(HERO_TOP, 75))
        lg.setColorAt(0.45, qc(HERO_TOP, 20))
        lg.setColorAt(1.0, qc(HERO_TOP, 0))
        p.fillRect(self.rect(), QBrush(lg))
        fg = QLinearGradient(0, h * 0.55, 0, h)
        fg.setColorAt(0.0, qc(INK, 0))
        fg.setColorAt(1.0, qc(INK, 95))
        p.fillRect(QRectF(0, h * 0.55, w, h * 0.45), QBrush(fg))

# ============================================================
# 货架边缘渐隐（提示「右边还有」）
# ============================================================
class EdgeFade(QWidget):
    """贴在货架视口左右边缘的渐变遮罩，按滚动位置显隐"""
    def __init__(self, parent, from_left):
        super().__init__(parent)
        self.from_left = from_left
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFixedWidth(48)

    def paintEvent(self, _ev):
        p = QPainter(self)
        g = QLinearGradient(0, 0, self.width(), 0)
        if self.from_left:
            g.setColorAt(0.0, qc(BG_BASE, 225))
            g.setColorAt(1.0, qc(BG_BASE, 0))
        else:
            g.setColorAt(0.0, qc(BG_BASE, 0))
            g.setColorAt(1.0, qc(BG_BASE, 225))
        p.fillRect(self.rect(), QBrush(g))

# ============================================================
# 横滑货架
# ============================================================
class HScrollArea(QScrollArea):
    def __init__(self, v_align=Qt.AlignVCenter):
        super().__init__()
        self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setAlignment(Qt.AlignHCenter | v_align)
        self._scroll_target = None
        self._scroll_anim = None
        self.setStyleSheet('QScrollArea{border:none;background:transparent;}'
                           'QScrollBar:horizontal{background:transparent;height:8px;margin:2px 10px;}'
                           'QScrollBar::handle:horizontal{background:%s;border-radius:4px;}'
                           'QScrollBar::add-line,QScrollBar::sub-line{width:0;height:0;}'
                           'QScrollBar::add-page,QScrollBar::sub-page{background:transparent;}' % rgba(WHITE_RGB, 38))

    def wheelEvent(self, e):
        dy = e.angleDelta().y()
        if not dy:
            return super().wheelEvent(e)
        sb = self.horizontalScrollBar()
        step = -dy * 1.6                     # 一档 ≈ 一个卡距（194px）
        if not ANIM_ENABLED:
            sb.setValue(max(sb.minimum(), min(sb.maximum(), sb.value() + int(step))))
            e.accept()
            return
        if self._scroll_anim is None:
            self._scroll_anim = QPropertyAnimation(sb, b'value', self)
            self._scroll_anim.setDuration(200)
            self._scroll_anim.setEasingCurve(QEasingCurve.OutCubic)
        if self._scroll_anim.state() != QPropertyAnimation.State.Running:
            self._scroll_target = None       # 被外部拖动过则以当前位置为基准
        base = sb.value() if self._scroll_target is None else self._scroll_target
        end = int(max(sb.minimum(), min(sb.maximum(), base + step)))
        self._scroll_target = end
        self._scroll_anim.stop()
        self._scroll_anim.setStartValue(sb.value())
        self._scroll_anim.setEndValue(end)
        self._scroll_anim.start()
        e.accept()

# ============================================================
# 底栏按键徽章
# ============================================================
def make_hint(parent, badge, text):
    host = QWidget(parent)
    l = QHBoxLayout(host)
    l.setContentsMargins(0, 0, 0, 0)
    l.setSpacing(7)
    kb = QLabel(badge)
    kb.setAlignment(Qt.AlignCenter)
    kb.setFixedHeight(22)
    kb.setStyleSheet('background:%s;border:1px solid %s;border-radius:11px;'
                     'color:%s;font-size:%dpx;font-weight:700;padding:0 7px;' % (
                         KB_BG, KB_BORDER, TEXT_SOFT, FS_BADGE))
    if len(badge) == 1:
        kb.setFixedWidth(22)
        kb.setStyleSheet(kb.styleSheet().replace('padding:0 7px;', 'padding:0;'))
    txt = QLabel(text)
    txt.setStyleSheet('color:%s;font-size:%dpx;' % (DIM, FS_BODY))
    l.addWidget(kb)
    l.addWidget(txt)
    return host

# ============================================================
# 主窗口
# ============================================================

# ============================================================
# 底部菜单栏（Steam 大屏幕式）QSS
# ============================================================
MENU_QSS = ('QPushButton{background:transparent;border:0;color:%s;font-size:%dpx;'
            'padding:7px 16px;border-radius:8px;}'
            'QPushButton:hover{color:%s;background:%s;}'
            'QPushButton:checked{color:%s;background:%s;font-weight:600;}' % (
                NAV_TEXT, FS_BODY, TEXT, rgba(WHITE_RGB, 30),
                WHITE, rgba(ACCENT_RGB, 48)))
MENU_ACT_QSS = ('QPushButton{background:%s;color:%s;font-size:%dpx;'
                'font-weight:600;padding:7px 16px;border-radius:8px;}'
                'QPushButton:hover{background:%s;}'
                'QPushButton:disabled{background:%s;color:%s;}' % (
                    rgba(ACCENT_RGB, 44), TEXT, FS_BODY,
                    rgba(ACCENT_RGB, 72), rgba(WHITE_RGB, 18), DIM))
MENU_MANAGE_QSS = ('QPushButton{background:%s;color:%s;'
                   'font-size:%dpx;padding:7px 16px;border-radius:8px;}'
                   'QPushButton:hover{color:%s;background:%s;}'
                   'QPushButton:checked{color:%s;background:%s;}' % (
                       rgba(WHITE_RGB, 20), TEXT_SOFT, FS_BODY,
                       TEXT, rgba(WHITE_RGB, 46), RED_SOFT, rgba(RED_RGB, 52)))

class LauncherWindow(QWidget):
    def __init__(self, windowed=False):
        super().__init__()
        self.focus_idx = -1
        self._focused_card = None
        self._press_global = None
        self._press_global_r = None
        self._top_h = 64
        self.cat = '全部'
        self.query = ''
        self.toasts = []
        self._launching_cards = []
        self._cat_buttons = {}
        self._bg = None
        self.glow = QColor(ACCENT)
        self._glow_t = 1.0
        self._glow_from_pm = None
        self._glow_to_pm = None
        self.edit_mode = False
        self._edit_phase = 0
        self._pending_adds = []
        self._edit_timer = QTimer(self)
        self._edit_timer.timeout.connect(self._tick_edit)
        self._pending_hover_card = None
        self._hover_timer = QTimer(self)          # 悬停确认：横扫货架不逐卡刷新 Hero
        self._hover_timer.setSingleShot(True)
        self._hover_timer.timeout.connect(self._apply_hover_focus)
        self.setAcceptDrops(True)


        self.setContextMenuPolicy(Qt.NoContextMenu)
        self.setWindowTitle('桌面启动器')
        self.setMinimumWidth(900)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)

        self._build_ui()
        if windowed:
            self.resize(1400, 780)
            self.move(120, 26)

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(10000)
        self._tick_clock()

        self._launch_timer = QTimer(self)
        self._launch_timer.timeout.connect(self._tick_launching)   # 按需启停（见 on_card_launching）

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._apply_filter)

        self._glow_timer = QTimer(self)
        self._glow_timer.timeout.connect(self._tick_glow)

        store = load_custom_store()
        self._hidden_paths = set(store['hidden'])
        self._customs_set = set(store['customs'])   # 右键菜单判「移除/隐藏」用，免每次读盘
        self._removed_paths = set()
        self._big_order = []               # 当前持有 pm_big 的 app（≤2 张）
        self._recent = dict(store.get('recent', {}))
        self._frequent = dict(store.get('frequent', {}))
        self._sort_mode = store.get('sort_mode', 'recent')
        self._scan_enabled = store['scan_enabled']
        self._scan_gen = 0                 # 扫描代数：迟到事件按代数丢弃（见 _on_batch）
        self._retiring_workers = []        # 超时未退出的旧扫描线程（引用保活防销毁崩溃）
        self._undo_stack = []              # remove_card 撤销栈（最多 10 条）
        self._pending_qml_glow = None      # QML 未就绪时暂存辉光色
        self._adder = None

        self.tray = self._make_tray()
        self.tray.show()
        if AL_QML:
            self._start_qml_background()
        # 高 DPI 感知：显示器变更时全部位图缓存失效
        scr = self.screen()
        if scr:
            scr.geometryChanged.connect(self._on_screen_changed)

        self.spot_title.setText('正在扫描开始菜单 / 桌面…')
        self.spot_sub.setText('正在提取图标（有缓存时秒开）')
        self._skeletons = []
        self._skel_timer = QTimer(self)
        self._skel_timer.timeout.connect(self._tick_skeletons)
        self._show_skeletons()
        self._start_worker(self._scan_enabled)
        self._start_ipc_server()

    def _show_skeletons(self):
        vp = self.shelf.viewport()
        self._hide_skeletons()
        for i in range(8):
            s = SkeletonCard(vp)
            s.move(20 + i * (CW + GAP), 16)
            s.show()
            self._skeletons.append(s)
        if ANIM_ENABLED:
            self._skel_timer.start(50)     # 减少动画：骨架静止显示

    def _hide_skeletons(self):
        self._skel_timer.stop()
        for s in self._skeletons:
            s.deleteLater()
        self._skeletons = []

    def _tick_skeletons(self):
        for s in self._skeletons:
            s.tick()

    # ---------- UI ----------
    def _make_tray(self):
        pm = QPixmap(64, 64)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(QRectF(2, 2, 60, 60), 16, 16)
        g = QLinearGradient(0, 0, 64, 64)
        g.setColorAt(0.0, QColor(ACCENT))
        g.setColorAt(1.0, QColor(ACCENT2))
        p.fillPath(path, QBrush(g))
        p.setPen(QColor(WHITE))
        f = QFont(FONT_UI)
        f.setPixelSize(FS_TRAY)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(0, 0, 64, 64), Qt.AlignCenter, '启')
        p.end()
        tray = QSystemTrayIcon(QIcon(pm), self)
        menu = QMenu()
        menu.setStyleSheet(QMENU_QSS)
        menu.setAttribute(Qt.WA_TranslucentBackground, True)
        act_show = menu.addAction('显示启动器')
        act_solo = menu.addAction('仅显示我添加的应用')
        act_solo.setCheckable(True)
        act_solo.setChecked(not self._scan_enabled)
        act_solo.toggled.connect(lambda on: self.set_scan_mode(not on))
        act_restore = menu.addAction('恢复全部隐藏的应用')
        act_restore.triggered.connect(self.restore_hidden)
        act_freq = menu.addAction('按最常用排序')
        act_freq.setCheckable(True)
        act_freq.setChecked(self._sort_mode == 'frequent')
        act_freq.toggled.connect(lambda on: self.set_sort_mode('frequent' if on else 'recent'))
        menu.addSeparator()
        act_quit = menu.addAction('退出')
        act_show.triggered.connect(self.show_from_tray)
        act_quit.triggered.connect(self.close)
        tray.setContextMenu(menu)
        tray.setToolTip('桌面启动器（左键：显示 / 收起）')
        tray.activated.connect(self._on_tray_activated)
        return tray

    def set_scan_mode(self, enabled):
        """切换 自动全量扫描 / 仅手动添加（重启扫描线程）"""
        if enabled == self._scan_enabled:
            return
        self._scan_enabled = enabled
        store = load_custom_store()
        store['scan_enabled'] = enabled
        save_custom_store(store)
        if self._adder is not None and self._adder.isRunning():
            self._adder.wait(1500)
        self._restart_worker(enabled)
        self.toast('已切换为「' + ('自动扫描 + 手动添加' if enabled else '仅手动添加') + '」模式')

    def _restart_worker(self, scan_enabled):
        # 先无条件断开旧 worker 信号：即使它刚结束，队列里未消费的 batch 事件
        # 也可能在画布清空之后才送达 → 卡片翻倍（探针实测 79→158）
        try:
            self.worker.batch.disconnect()
            self.worker.done.disconnect()
        except Exception:
            pass
        if self.worker.isRunning():
            self.worker.cancel()
            if not self.worker.wait(2000):
                # 限时 wait 不保证线程结束（Qt 文档）：保留引用至自然结束，
                # 避免替换引用导致 QThread 在运行中被销毁（Fatal）
                self._retiring_workers.append(self.worker)
                self.worker.finished.connect(
                    lambda w=self.worker: self._retiring_workers.remove(w))
                logging.warning('扫描线程超时未退出，已转入后台等待')
        self.focus_idx = -1
        self._focused_card = None
        for c in self.canvas.cards:
            stop_card_anim(c)
            c.deleteLater()
        self.canvas.cards = []
        self._launching_cards = []         # 已删卡片不可残留在启动动画队列（33ms 定时器会反复炸）
        self._big_order.clear()
        for b in self._cat_buttons.values():
            b.deleteLater()
        self._cat_buttons = {}
        self._add_nav_button('全部')
        self.canvas.setFixedSize(PAD + GAP, CH + PAD * 2)
        store = load_custom_store()
        self._hidden_paths = set(store['hidden'])
        self._customs_set = set(store['customs'])
        self._removed_paths.clear()
        self.spot_title.setText('正在刷新应用列表…')
        self.spot_sub.setText('')
        self._show_skeletons()
        self._start_worker(scan_enabled)

    def _start_worker(self, scan_enabled):
        """创建扫描线程并把当前代数绑定进信号闭包：
           被取消 worker 已入队的迟到事件会带着旧代数送达，据此丢弃。"""
        self._scan_gen += 1
        gen = self._scan_gen
        store = load_custom_store()
        self._hidden_paths = set(store['hidden'])
        self._customs_set = set(store['customs'])
        self._removed_paths.clear()
        self.worker = ScanWorker(store['customs'], store['hidden'], scan_enabled)
        self.worker.batch.connect(lambda apps, g=gen: self._on_batch(apps, g))
        self.worker.done.connect(lambda c, e, g=gen: self._on_done(c, e, g))
        self.worker.start()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶栏（时钟 + 搜索）
        top = QWidget()
        self._top_host = top
        tl = QHBoxLayout(top)
        tl.setContentsMargins(GUTTER, 16, GUTTER, 8)
        tl.setSpacing(14)
        cbox = QVBoxLayout()
        cbox.setSpacing(1)
        self.clock = QLabel('--:--')
        self.clock.setStyleSheet('color:%s; font-size:%dpx; font-weight:600; font-family:%s,"Segoe UI";' % (
            TEXT, FS_CLOCK, FONT_MONO))
        self.date = QLabel('')
        self.date.setStyleSheet('color:%s; font-size:%dpx;' % (DIM, FS_META))
        cbox.addWidget(self.clock)
        cbox.addWidget(self.date)
        tl.addLayout(cbox)

        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索应用…')
        self.search.setFixedWidth(240)
        self.search.setStyleSheet(SEARCH_QSS)
        self.search.textChanged.connect(lambda _t: self._search_timer.start(150))
        self.search.returnPressed.connect(self._search_launch)   # 回车：立即落筛再启动，防抖竞态不再漏筛
        self.search.installEventFilter(self)                     # Esc 清空搜索
        tl.addWidget(self.search)

        # 窗口操作按钮（无边框窗口的系统控制替代）
        btn_row = QHBoxLayout()
        btn_row.setSpacing(0)
        for label, handler, tip, hover_bg in (
            ('\u2500', self.showMinimized, '最小化', rgba(WHITE_RGB, 25)),
            ('\u25a1', self._toggle_maximized, '最大化 / 还原', rgba(WHITE_RGB, 25)),
            ('\u2715', self.close, '关闭', rgba(RED_RGB, 180)),
        ):
            b = QPushButton(label)
            b.setFixedSize(32, 26)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(tip)
            b.setStyleSheet(
                'QPushButton{background:transparent;border:0;color:%s;font-size:14px;'
                'border-radius:6px;padding:0;}'
                'QPushButton:hover{background:%s;color:%s;}'
                'QPushButton:pressed{background:%s;}' % (
                    DIM, hover_bg, TEXT, rgba(RED_RGB, 120) if label == '\u2715' else rgba(WHITE_RGB, 40)))
            b.clicked.connect(handler)
            btn_row.addWidget(b)
        tl.addLayout(btn_row)

        root.addWidget(top)
        self._top_h = max(56, top.sizeHint().height())

        # 半屏主视觉
        self.hero = Hero()
        self.hero_l = QHBoxLayout(self.hero)
        self.hero_l.setContentsMargins(GUTTER, 24, GUTTER, 30)
        self.hero_l.setSpacing(44)
        self.poster = HeroPoster()
        self.poster.setFixedSize(256, 256)
        self.hero_l.addWidget(self.poster, 0, Qt.AlignVCenter)
        meta = QVBoxLayout()
        meta.setSpacing(12)
        self.spot_title = QLabel('—')
        self.spot_title.setTextFormat(Qt.RichText)
        self.spot_title.setStyleSheet('color:%s; font-size:%dpx; font-weight:700; letter-spacing:0.5px;' % (
            TEXT, FS_HERO))
        self.spot_sub = QLabel('')
        self.spot_sub.setTextFormat(Qt.RichText)
        self.spot_sub.setStyleSheet('color:%s; font-size:%dpx;' % (DIM, FS_SUB))
        acts = QHBoxLayout()
        acts.setSpacing(10)
        self.btn_launch = QPushButton('启 动')
        self.btn_launch.setCursor(Qt.PointingHandCursor)
        self.btn_launch.setStyleSheet(PRIMARY_QSS)
        self.btn_launch.clicked.connect(self.launch_focused)
        self.btn_info = QPushButton('详情')
        self.btn_info.setCursor(Qt.PointingHandCursor)
        self.btn_info.setStyleSheet(GHOST_QSS)
        self.btn_info.clicked.connect(self.show_info)
        for b in (self.btn_launch, self.btn_info):
            acts.addWidget(b)
        acts.addStretch(1)
        meta.addWidget(self.spot_title)
        meta.addWidget(self.spot_sub)
        meta.addLayout(acts)
        meta.addStretch(1)
        self.hero_l.addLayout(meta, 1)
        root.addWidget(self.hero)

        # 货架（底部横滑）
        shelf_wrap = QWidget()
        sv = QVBoxLayout(shelf_wrap)
        sv.setContentsMargins(GUTTER, 2, GUTTER, 10)
        sv.setSpacing(8)
        self.rowtitle = QLabel('全部应用')
        self.rowtitle.setStyleSheet('color:%s; font-size:%dpx; letter-spacing:1.5px;' % (DIM, FS_HINT))
        self.shelf = HScrollArea(Qt.AlignTop)   # 卡片锚定货架上沿，不再在剩余空间里垂直悬空
        self.shelf.setStyleSheet(self.shelf.styleSheet())
        self.canvas = Canvas()
        self.shelf.setWidget(self.canvas)
        self.shelf.viewport().setAutoFillBackground(False)
        self.shelf.viewport().setStyleSheet('background:transparent;')
        sv.addWidget(self.rowtitle)
        sv.addWidget(self.shelf, 1)
        root.addWidget(shelf_wrap, 1)

        # 菜单栏（Steam 大屏幕式：分类 chips + 添加 / 管理）
        menu_dock = QWidget()
        menu_dock.setStyleSheet('background:%s;'
                                'border:1px solid %s;border-radius:14px;' % (
                                    rgba(HERO_RGB_B, 205), rgba(WHITE_RGB, 22)))
        ml = QHBoxLayout(menu_dock)
        ml.setContentsMargins(14, 7, 14, 7)
        ml.setSpacing(8)
        self.menu_scroll = HScrollArea()
        self.menu_scroll.setStyleSheet('QScrollArea{border:none;background:transparent;}'
                                       'QScrollBar:horizontal{height:0px;background:transparent;}')
        self.menu_host = QWidget()
        self.menu_host.setStyleSheet('background:transparent;')
        self.menu_l = QHBoxLayout(self.menu_host)
        self.menu_l.setContentsMargins(4, 2, 4, 2)
        self.menu_l.setSpacing(6)
        self._add_nav_button('全部')       # 常驻复位 chip：任何分类/搜索状态一键回全量
        self.menu_scroll.setWidget(self.menu_host)
        self.menu_scroll.setMinimumWidth(240)
        ml.addWidget(self.menu_scroll, 1)
        self.btn_add = QPushButton('＋ 添加')
        self.btn_add.setCursor(Qt.PointingHandCursor)
        self.btn_add.setEnabled(False)
        self.btn_add.setToolTip('添加应用：选择程序 (.exe) 或快捷方式 (.lnk)')
        self.btn_add.setStyleSheet(MENU_ACT_QSS)
        self.btn_add.clicked.connect(self.add_custom_app)
        ml.addWidget(self.btn_add)
        self.btn_manage = QPushButton('管理')
        self.btn_manage.setCheckable(True)
        self.btn_manage.setCursor(Qt.PointingHandCursor)
        self.btn_manage.setStyleSheet(MENU_MANAGE_QSS)
        self.btn_manage.clicked.connect(self.toggle_edit_mode)
        ml.addWidget(self.btn_manage)
        self.btn_batch = QPushButton('移除选中')
        self.btn_batch.setCursor(Qt.PointingHandCursor)
        self.btn_batch.setStyleSheet(MENU_MANAGE_QSS)
        self.btn_batch.clicked.connect(self._batch_remove_selected)
        self.btn_batch.hide()
        ml.addWidget(self.btn_batch)
        root.addWidget(menu_dock)

        # 底栏（悬浮浮岛，去掉硬边线）
        bar_dock = QWidget()
        bar_dock.setStyleSheet('background:transparent;')
        bd = QVBoxLayout(bar_dock)
        bd.setContentsMargins(GUTTER, 2, GUTTER, 10)
        bar = QWidget()
        bar.setFixedHeight(44)
        bar.setStyleSheet('background:%s;'
                          'border:1px solid %s;border-radius:14px;' % (
                              rgba(HERO_RGB_B, 205), rgba(WHITE_RGB, 22)))
        bd.addWidget(bar)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(22, 0, 22, 0)
        bl.setSpacing(10)
        self.brand = QLabel('桌面启动器 · 扫描中…')
        self.brand.setStyleSheet('color:%s; font-size:%dpx; font-weight:600;' % (TEXT, FS_BODY))
        bl.addWidget(self.brand)
        bl.addStretch(1)
        self.hint_normal = QWidget()
        hn = QHBoxLayout(self.hint_normal)
        hn.setContentsMargins(0, 0, 0, 0)
        hn.setSpacing(22)
        hn.addWidget(make_hint(self.hint_normal, '左键', '启动'))
        hn.addWidget(make_hint(self.hint_normal, '右键', '菜单'))
        hn.addWidget(make_hint(self.hint_normal, 'Esc', '收起'))
        bl.addWidget(self.hint_normal)
        root.addWidget(bar_dock)

        # 货架空态（真·空货架 → 引导添加；筛选落空 → 一键清筛选）
        self.empty_state = QPushButton()
        self.empty_state.setCursor(Qt.PointingHandCursor)
        self.empty_state.setStyleSheet(
            'QPushButton{background:%s;border:2px dashed %s;'
            'border-radius:18px;color:%s;font-size:%dpx;padding:28px;}'
            'QPushButton:hover{color:%s;border-color:%s;}' % (
                rgba(WHITE_RGB, 10), rgba(WHITE_RGB, 44), EMPTY_TEXT, FS_SUB,
                TEXT, rgba(WHITE_RGB, 84)))
        self.empty_state.clicked.connect(self._on_empty_clicked)
        self.empty_state.setParent(self.shelf.viewport())
        self.empty_state.hide()
        # 货架边缘渐隐（提示「左边/右边还有」）
        self._fade_l = EdgeFade(self.shelf.viewport(), True)
        self._fade_r = EdgeFade(self.shelf.viewport(), False)
        self._fade_l.hide()
        self._fade_r.hide()
        self.shelf.horizontalScrollBar().valueChanged.connect(self._update_edge_fades)

    def _add_nav_button(self, cat):
        if cat in self._cat_buttons:
            return
        b = QPushButton(cat)
        b.setCheckable(True)
        b.setChecked(cat == self.cat)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(MENU_QSS)
        b.clicked.connect(lambda _=False, cc=cat: self.set_category(cc))
        self.menu_l.addWidget(b)
        self._cat_buttons[cat] = b

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._bg = None
        self._glow_from_pm = None
        self._glow_to_pm = None
        if getattr(self, '_bg_layer', None) is not None:
            self._bg_layer.setGeometry(0, 0, self.width(), self.height())
        hero_h = max(300, min(480, int(self.height() * 0.42)))
        self.hero.setFixedHeight(hero_h)
        if hasattr(self, 'canvas'):
            self.canvas.reflow(animate=False)
            if 0 <= self.focus_idx < len(self.visible_cards()):
                self.set_focus(self.focus_idx, from_hover=True)
        if hasattr(self, 'empty_state'):
            self._update_empty_state()
        if hasattr(self, '_fade_l'):
            self._update_edge_fades()

    def showEvent(self, e):
        if not getattr(self, '_rounded', False):
            self._rounded = True
            self._apply_win11_rounding()
        super().showEvent(e)

    def _apply_win11_rounding(self):
        """Win11：给无边框窗口找回系统圆角（阴影/Mica 成本高，暂不做）"""
        try:
            hwnd = int(self.winId())
            pref = ctypes.c_int(2)                 # DWMWA_WINDOW_CORNER_PREFERENCE=33, DWMWCP_ROUND=2
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref))
        except Exception:
            pass

    def _update_edge_fades(self):
        if not hasattr(self, 'shelf'):
            return
        sb = self.shelf.horizontalScrollBar()
        vp = self.shelf.viewport()
        h = vp.height()
        sx = sb.value()
        vw = vp.width()
        for c in self.canvas.cards:        # 滚动也管理卡面缓存（此前只在 reflow 释放）
            if c.isHidden():
                continue
            x = c.x()
            if x + CW < sx - CW * 3 or x > sx + vw + CW * 3:
                c.release_face()
        self._fade_l.setGeometry(0, 0, 48, h)
        self._fade_r.setGeometry(vp.width() - 48, 0, 48, h)
        has_cards = bool(self.canvas.visible_cards())
        self._fade_l.setVisible(has_cards and sb.value() > 0)
        self._fade_r.setVisible(has_cards and sb.maximum() > 0
                                and sb.value() < sb.maximum())

    def paintEvent(self, _ev):
        if getattr(self, '_bg_layer', None) is not None:
            return          # QML 背景层已渲染（GPU），跳过 CPU 绘制
        if self._bg is None or self._bg_size != self.size():
            self._rebuild_bg()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.drawPixmap(0, 0, self._bg)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if self._glow_to_pm is None:
            self._glow_to_pm = self._render_glow_pm(self.glow)
        if self._glow_t < 1.0 and self._glow_from_pm is not None:
            p.drawPixmap(self.rect(), self._glow_from_pm)
            p.setOpacity(max(0.0, self._glow_t))
            p.drawPixmap(self.rect(), self._glow_to_pm)
            p.setOpacity(1.0)
        else:
            p.drawPixmap(self.rect(), self._glow_to_pm)

    def _rebuild_bg(self):
        dpr = self.devicePixelRatioF()
        self._bg_size = self.size()
        pm = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
        pm.setDevicePixelRatio(dpr)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(pm.rect(), QColor(BG_BASE))
        g = QLinearGradient(0, 0, self.width() * 0.9, self.height())
        g.setColorAt(0.0, QColor(BG_TOP))
        g.setColorAt(1.0, QColor(HERO_BOT))
        p.fillRect(self.rect(), QBrush(g))
        # 细噪点（预生成 tile 平铺）
        p.setOpacity(0.5)
        p.drawTiledPixmap(self.rect(), noise_tile())
        p.setOpacity(1.0)
        # 四角 vignette
        vg = QRadialGradient(self.width() / 2, self.height() / 2,
                             math.hypot(self.width(), self.height()) / 2)
        vg.setColorAt(0.60, qc(BLACK, 0))
        vg.setColorAt(1.00, qc(BLACK, 46))
        p.fillRect(self.rect(), QBrush(vg))
        p.end()
        self._bg = pm

    # ---------- 辉光补间 ----------
    def _render_glow_pm(self, color):
        w = max(80, int(self.width() / 4))
        h = max(60, int(self.height() / 4))
        pm = QPixmap(w, h)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        for radius, alpha in ((0.92, 20), (0.55, 36)):
            rg = QRadialGradient(w / 2, h * 1.02, w * radius)
            c = QColor(color)
            c.setAlpha(alpha)
            rg.setColorAt(0.0, c)
            rg.setColorAt(1.0, qc(BLACK, 0))
            p.fillRect(pm.rect(), QBrush(rg))
        p.end()
        return pm

    def set_glow(self, color):
        if color == self.glow:
            return
        prev = QColor(self.glow)           # 旧色留档：from 帧用旧色渲染（修复首切无过渡）
        self.glow = QColor(color)
        if not ANIM_ENABLED or DUR_SLOW <= 0:
            self._glow_from_pm = None      # 零时长：直接置终值，不启补间
            self._glow_to_pm = self._render_glow_pm(color)
            self._glow_t = 1.0
            self.update()
            return
        self._set_qml_glow(color.name())
        self._glow_from_pm = self._render_glow_pm(prev)
        self._glow_to_pm = self._render_glow_pm(color)
        self._glow_t0 = time.time()
        self._glow_t = 0.0
        if not self._glow_timer.isActive():
            self._glow_timer.start(16)

    def _tick_glow(self):
        t = (time.time() - self._glow_t0) / max(0.001, DUR_SLOW / 1000.0)
        self._glow_t = min(1.0, t)
        if t >= 1.0:
            self._glow_timer.stop()
            self._glow_from_pm = None
        self.update()

    # ---------- 时钟 ----------
    def _tick_clock(self):
        d = datetime.now()
        self.clock.setText(d.strftime('%H:%M'))
        self.date.setText(f'{d.year}年{d.month}月{d.day}日 星期{"一二三四五六日"[d.weekday()]}')

    # ---------- 扫描 ----------
    def _on_batch(self, apps, gen=None):
        if gen is not None and gen != self._scan_gen:
            return                     # 被取消 worker 已入队的迟到事件（按代数丢弃）
        if self._skeletons:
            self._hide_skeletons()
        cards = []
        for app in apps:
            if app['lnk'] in self._hidden_paths or app['lnk'] in self._removed_paths:
                continue
            img = app.get('img')
            if img is not None and not img.isNull():
                # 命中缩略图时已是 40px 直接用；冷路径的大图则缩到 40
                if img.width() > 40 or img.height() > 40:
                    img = img.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                app['pm_small'] = QPixmap.fromImage(img)
            else:
                app['pm_small'] = QPixmap()
            app['img'] = None          # 派生完毕，释放引用
            card = Card(app, self.canvas)
            ok = (self.cat == '全部' or app['cat'] == self.cat) and \
                 (not self.query or self.query in app['name'].lower()
                  or self.query in app['cat'].lower())
            card.setVisible(ok)        # 重启/扫描期间保留当前筛选
            if not ok:
                card.release_face()
            card.customContextMenuRequested.connect(
                lambda pos, cc=card: self._show_card_menu(cc, cc.mapToGlobal(pos)))
            cards.append(card)
        self.canvas.add_cards(cards)
        for app in apps:
            if app['lnk'] in self._hidden_paths or app['lnk'] in self._removed_paths:
                continue
            self._add_nav_button(app['cat'])
        if self.focus_idx < 0 and self.canvas.visible_cards():
            self.set_focus(0)

    def _on_done(self, count, elapsed, gen=None):
        if gen is not None and gen != self._scan_gen:
            return                     # 同上：迟到事件不触发收尾
        self._hide_skeletons()
        self.btn_add.setEnabled(True)
        self._update_empty_state()
        self._drain_pending_adds()
        self._update_rowtitle()
        if len(self.canvas.cards) == 0:
            self.spot_title.setText('还没有应用')
            self.spot_sub.setText('点击底部菜单岛的「＋ 添加」选择程序或快捷方式'
                                  if not self._scan_enabled else
                                  '未在开始菜单与桌面发现 .lnk 快捷方式')
            return
        self._apply_recent_flags()
        self._apply_recent_order()
        if self.focus_idx < 0:
            self.set_focus(0)

    def _update_rowtitle(self):
        n = len(self.canvas.visible_cards())
        self.rowtitle.setText(f'{self.cat} · {n} 个应用')
        self.brand.setText(f'桌面启动器 · {n} 个应用')   # 与货架可见数一致，避免同屏两个数字

    # ---------- 焦点 ----------
    def visible_cards(self):
        return self.canvas.visible_cards()

    def on_card_hover(self, card):
        vis = self.visible_cards()
        if card not in vis:
            return
        card.animate_scale(1.06)
        if card is not self._focused_card:
            # 悬停确认延迟：横扫货架时不逐卡刷新 Hero（防海报闪烁/辉光重建）
            self._pending_hover_card = card
            self._hover_timer.start(HOVER_CONFIRM)

    def on_card_leave(self, card):
        if self._pending_hover_card is card:
            self._pending_hover_card = None
        if not card.focused:
            card.animate_scale(1.0)

    def _apply_hover_focus(self):
        card, self._pending_hover_card = self._pending_hover_card, None
        if card is not None and not card.isHidden():
            vis = self.visible_cards()
            if card in vis:
                self.set_focus(vis.index(card), from_hover=True)

    # ---------- 最近使用 ----------
    def set_sort_mode(self, mode):
        """切换排序模式（recent / frequent）"""
        if mode == self._sort_mode:
            return
        self._sort_mode = mode
        store = load_custom_store()
        store['sort_mode'] = mode
        save_custom_store(store)
        self._apply_recent_order()
        self.toast('已切换为「' + ('最常用' if mode == 'frequent' else '最近使用') + '」排序')

    def _record_recent(self, path):
        self._recent[path] = time.time()
        self._frequent[path] = self._frequent.get(path, 0) + 1
        self._recent = prune_recent(self._recent)
        store = load_custom_store()
        store['recent'] = self._recent
        store['frequent'] = self._frequent
        if not save_custom_store(store):
            self.toast('配置保存失败，数据可能不会持久化')
        self._apply_recent_flags()
        self._apply_recent_order()
        if self._focused_card is not None and self._focused_card.app['lnk'] == path:
            self._render_spot_sub(self._focused_card.app)   # 「上次启动 · 刚刚」即时更新

    def _apply_recent_flags(self):
        now = time.time()
        for c in self.canvas.cards:
            ts = self._recent.get(c.app['lnk'], 0)
            c.set_recent(ts > 0 and now - ts < 48 * 3600)

    def _apply_recent_order(self, animate=True):
        """按排序模式排货架（recent=最近使用 / frequent=最常用）。
           可见性变化必须 reflow；顺序变化时同步 focus_idx。"""
        vis = self.canvas.visible_cards()
        if self._sort_mode == 'frequent':
            vis.sort(key=lambda c: (-self._frequent.get(c.app['lnk'], 0), c.app['name']))
        else:
            vis.sort(key=lambda c: (-self._recent.get(c.app['lnk'], 0.0), c.app['name']))
        vis_ids = {id(c) for c in vis}
        rest = [c for c in self.canvas.cards if id(c) not in vis_ids]
        order_changed = [id(c) for c in self.canvas.cards] != \
            [id(c) for c in vis] + [id(c) for c in rest]
        self.canvas.cards = vis + rest
        self.canvas.reflow(animate=animate and ANIM_ENABLED)
        self._apply_recent_flags()
        if order_changed:
            self._sync_focus_index()

    def _ensure_pm_big(self, app):
        """Hero 大图惰性生成：仅焦点 app 常驻 pm_big（≤2 张），按需从主图 PNG 解码"""
        if app.get('pm_big') is not None:
            if app in self._big_order:
                self._big_order.remove(app)
                self._big_order.append(app)
            return
        img = None
        if app.get('icon_file'):
            img = QImage(os.path.join(ICON_DIR, app['icon_file']))
            if img.isNull():
                img = None
        if img is not None:
            if img.width() > 160 or img.height() > 160:
                img = img.scaled(160, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            app['pm_big'] = QPixmap.fromImage(img)
        else:
            app['pm_big'] = QPixmap()
        self._big_order.append(app)
        while len(self._big_order) > 2:
            old = self._big_order.pop(0)
            if old is not app:
                old.pop('pm_big', None)

    def set_focus(self, idx, from_hover=False):
        vis = self.visible_cards()
        if not vis:
            self.focus_idx = -1
            return
        n = len(vis)
        i = ((idx % n) + n) % n
        self.focus_idx = i
        card = vis[i]
        if card is self._focused_card:
            return
        prev = self._focused_card
        if prev is not None and prev is not card and prev.focused:
            prev.focused = False
            prev.update()
        if not card.focused:
            card.focused = True
        card.update()
        self._focused_card = card
        # 焦点缩放联动（键盘/初始焦点同样放大）
        card.animate_scale(1.06)
        if prev is not None and prev is not card and not prev.underMouse():
            prev.animate_scale(1.0)
        app = card.app
        self._ensure_pm_big(app)
        self.spot_title.setText(html.escape(app['name']))
        self._render_spot_sub(app)
        self.poster.set_app(app)
        self.hero.set_app(app)
        self.set_glow(muted_tint(QColor(app['tint'])))
        if not from_hover and card.parent() is self.canvas:
            self.shelf.ensureWidgetVisible(card)

    def _render_spot_sub(self, app):
        """副标题：上次启动（相对时间）替代低价值的 mtime；修改时间移入「详情」"""
        tgt = os.path.basename(app['target'] or app['lnk'])
        ts = self._recent.get(app['lnk'])
        if ts:
            d = time.time() - ts
            if d < 60:
                rel = '刚刚'
            elif d < 3600:
                rel = '%d 分钟前' % (d // 60)
            elif d < 86400:
                rel = '%d 小时前' % (d // 3600)
            else:
                rel = '%d 天前' % max(1, int(d // 86400))
            when = '上次启动 · ' + rel
        else:
            when = '未启动过'
        self.spot_sub.setText(
            f'<span style="color:{HIGH_BLUE};font-weight:600;">▶ {when}</span>'
            f'&nbsp;·&nbsp;<span>{html.escape(app["cat"])} · {html.escape(tgt)}</span>')

    # ---------- 启动 ----------
    def _sync_focus_index(self):
        """重排后按焦点卡片对象回算索引，保证 Hero 展示与回车启动一致"""
        vis = self.visible_cards()
        if self._focused_card is not None and self._focused_card in vis:
            self.focus_idx = vis.index(self._focused_card)

    def _search_launch(self):
        """搜索框回车：立即落筛（不等 150ms 防抖），再启动焦点应用"""
        self._search_timer.stop()
        self._apply_filter()
        self.launch_focused()

    def _search_escape(self):
        """搜索框 Esc：有内容先清空；空则传播到窗口（最小化）"""
        if self.search.text():
            self.search.clear()
        else:
            self.showMinimized()

    def launch_focused(self):
        vis = self.visible_cards()
        card = self._focused_card if (self._focused_card is not None
                                      and self._focused_card in vis) else None
        if card is None and 0 <= self.focus_idx < len(vis):
            card = vis[self.focus_idx]
        if card is not None:
            self.launch_card(card)

    # ---------- 手动添加 / 移除 ----------
    def add_custom_app(self):
        if self.worker.isRunning():
            self.toast('正在扫描，请稍候…')
            return
        path, _f = QFileDialog.getOpenFileName(
            self, '添加应用', '',
            '程序与快捷方式 (*.exe *.lnk *.url);;所有文件 (*.*)')
        if path:
            self.add_custom_path(path)

    def add_custom_path(self, path):
        if self.worker.isRunning():
            self.toast('正在扫描，请稍候…')
            return
        if self._adder is not None and self._adder.isRunning():
            self.toast('正在添加，请稍候…')     # 右键菜单/空态入口不受 btn_add 禁用保护
            return
        if self._adder is not None and self._adder.isRunning():
            self.toast('正在添加，请稍候…')     # 右键菜单/空态入口不受 btn_add 禁用保护
            return
        if any(c.app['lnk'].lower() == path.lower() for c in self.canvas.cards):
            self.toast('这个应用已经在启动器里了')
            return
        self.btn_add.setEnabled(False)
        self.toast(f'正在添加 <b>{html.escape(os.path.basename(path))}</b> …')
        self._adder = AddWorker(path)
        self._adder.ready.connect(self._on_custom_added)
        self._adder.failed.connect(self._on_custom_failed)
        self._adder.finished.connect(self._drain_pending_adds)   # 竞态兜底：线程结束再调度下一项
        self._adder.start()

    def _on_custom_failed(self, msg):
        self.btn_add.setEnabled(True)
        self.toast(f'添加失败：<span style="color:{DIM}">{html.escape(msg)}</span>', 3000)
        self._drain_pending_adds()

    def _on_custom_added(self, app):
        self.btn_add.setEnabled(True)
        self._customs_set.add(app['lnk'])
        self._hidden_paths.discard(app['lnk'])     # 会话内同步取消隐藏（磁盘侧 AddWorker 已处理）
        self._removed_paths.discard(app['lnk'])
        self._on_batch([app])
        self._update_rowtitle()
        vis = self.visible_cards()
        if app and vis:
            try:
                self.set_focus(vis.index(vis[-1]), from_hover=True)
            except ValueError:
                pass
        self.toast(f'已添加 <b>{html.escape(app["name"])}</b>')
        self._drain_pending_adds()

    def _undo_last_remove(self):
        """撤销上次移除/隐藏（Ctrl+Z）：恢复 custom.json 状态并重启扫描"""
        if not self._undo_stack:
            self.toast('没有可撤销的操作')
            return
        action = self._undo_stack.pop()
        path = action['lnk']
        store = load_custom_store()
        if path in store['hidden']:
            store['hidden'].remove(path)
        if action['was_custom'] and path not in store['customs']:
            store['customs'].append(path)
        save_custom_store(store)
        self._hidden_paths.discard(path)
        self._removed_paths.discard(path)
        if action['was_custom']:
            self._customs_set.add(path)
        self._restart_worker(self._scan_enabled)
        self.toast(f'已撤销上次移除（{os.path.basename(path)}）')

    def _batch_remove_selected(self):
        """管理模式批量移除所有选中的卡片"""
        selected = [c for c in self.canvas.cards if c._edit_selected and not c.isHidden()]
        if not selected:
            self.toast('未选中任何卡片')
            return
        for card in selected:
            self.remove_card(card)
        self.toast(f'已移除 {len(selected)} 张选中的卡片')

    def _on_edit_selection_changed(self):
        """管理模式选中数变化 → 更新批量按钮文案"""
        n = sum(1 for c in self.canvas.cards if c._edit_selected and not c.isHidden())
        self.btn_batch.setText(f'移除选中 ({n})' if n > 0 else '移除选中')

    def _show_card_menu(self, card, gpos):
        menu = QMenu()
        menu.setStyleSheet(QMENU_QSS)
        menu.setAttribute(Qt.WA_TranslucentBackground, True)
        act_launch = menu.addAction('启动')
        menu.addSeparator()
        is_custom = card.app['lnk'] in self._customs_set
        act_remove = menu.addAction('移除' if is_custom else '从启动器隐藏')
        chosen = menu.exec(gpos)
        if chosen is act_launch:
            self.launch_card(card)
        elif chosen is act_remove:
            self.remove_card(card)

    def remove_card(self, card):
        path = card.app['lnk']
        was_custom = path in self._customs_set
        store = load_custom_store()
        if path in store['customs']:
            store['customs'].remove(path)
            self._customs_set.discard(path)
        elif path not in store['hidden']:
            store['hidden'].append(path)
        save_custom_store(store)
        self._hidden_paths.add(path)
        self._removed_paths.add(path)
        self._undo_stack.append({'lnk': path, 'was_custom': was_custom})
        if len(self._undo_stack) > 10:
            self._undo_stack.pop(0)
        if card is self._focused_card:
            self._focused_card = None
            self.focus_idx = -1
        if card in self._launching_cards:
            self._launching_cards.remove(card)
        stop_card_anim(card)
        if card in self.canvas.cards:
            self.canvas.cards.remove(card)
        card.deleteLater()
        self.canvas.reflow(animate=True)
        self._update_rowtitle()
        if self.canvas.visible_cards():
            self.set_focus(0)
        self.toast(f'已移除 <b>{html.escape(card.app["name"])}</b>')
        self._update_empty_state()

    # ---------- 拖拽添加 / 右键菜单 / 管理模式 ----------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        paths = [p for p in paths if p.lower().endswith(('.lnk', '.exe', '.url'))]
        for p in paths:
            if p.lower() in [c.app['lnk'].lower() for c in self.canvas.cards]:
                continue
            self._pending_adds.append(p)
        if paths:
            self._drain_pending_adds()

    def _drain_pending_adds(self):
        if self.worker.isRunning():
            return
        if self._adder is not None and self._adder.isRunning():
            return
        if self._pending_adds:
            self.add_custom_path(self._pending_adds.pop(0))

    def _window_menu(self, gpos):
        menu = QMenu()
        menu.setStyleSheet(QMENU_QSS)
        menu.setAttribute(Qt.WA_TranslucentBackground, True)
        act_add = menu.addAction('＋ 添加应用')
        act_manage = menu.addAction('完成管理' if self.edit_mode else '管理卡片（可移除）')
        chosen = menu.exec(gpos)
        if chosen is act_add:
            self.add_custom_app()
        elif chosen is act_manage:
            self.toggle_edit_mode()

    def toggle_edit_mode(self):
        self.set_edit_mode(not self.edit_mode)

    def set_edit_mode(self, on):
        if on == self.edit_mode:
            return
        self.edit_mode = on
        self.btn_manage.setText('完成' if on else '管理')
        self.btn_manage.setChecked(on)
        if on:
            self._edit_phase = 0
            self._edit_seeds = []
            if ANIM_ENABLED:
                self._edit_timer.start(130)
            self.btn_batch.show()
            self.toast('管理模式 · 点击卡片主体选中 / 取消，点 × 移除，点「完成」退出')
        else:
            self._edit_timer.stop()
            self.btn_batch.hide()
            for c in self.canvas.cards:
                c._edit_selected = False
                c.set_rot(0.0)
            self.toast('已退出管理模式')
        for c in self.canvas.cards:
            c.update()

    def _tick_edit(self):
        """果冻式抖动：每卡随机相位 + 1.2°–1.8° 随机幅度（不再整排军训式同步）"""
        self._edit_phase += 1
        cards = self.canvas.cards
        if len(getattr(self, '_edit_seeds', [])) != len(cards):
            self._edit_seeds = [(random.uniform(0, math.tau), random.uniform(1.2, 1.8))
                                for _ in cards]
        for c, (ph, amp) in zip(cards, self._edit_seeds):
            if not c.isHidden() and not c.visibleRegion().isEmpty():
                c.set_rot(round(amp * math.sin(ph + self._edit_phase * 1.15), 2))

    def _update_empty_state(self):
        if not hasattr(self, 'empty_state'):
            return
        vis = self.canvas.visible_cards()
        empty = not vis
        self.empty_state.setVisible(empty)
        self.btn_launch.setEnabled(not empty)     # 空态禁用启动/详情，Hero 不再残留旧应用
        self.btn_info.setEnabled(not empty)
        if empty:
            filtered = bool(self.query) or self.cat != '全部'
            self.empty_state.setText('没有找到匹配的应用\n\n换个关键词，或点击这里清空筛选' if filtered else
                                     '货架空空如也\n\n拖入 .lnk / .exe 文件\n或点击这里添加第一个应用')
            if filtered:
                self.spot_title.setText('没有匹配的应用')
                self.spot_sub.setText('换个关键词，或点击这里清空筛选')
            vp = self.shelf.viewport()
            self.empty_state.setGeometry(24, 8, vp.width() - 48, vp.height() - 18)

    def _on_empty_clicked(self):
        """空态点击：筛选落空 → 一键清筛选回「全部」；真空货架 → 引导添加"""
        if bool(self.query) or self.cat != '全部':
            self.search.clear()
            self.set_category('全部')
        else:
            self.add_custom_app()

    def restore_hidden(self):
        store = load_custom_store()
        n = len(store['hidden'])
        store['hidden'] = []
        save_custom_store(store)
        self._hidden_paths.clear()
        self._removed_paths.clear()
        if n:
            self._restart_worker(self._scan_enabled)
            self._update_empty_state()
        self.toast(f'已恢复 {n} 个隐藏的应用' if n else '没有需要恢复的应用')

    def show_info(self):
        vis = self.visible_cards()
        if 0 <= self.focus_idx < len(vis):
            app = vis[self.focus_idx].app
            self.toast(f"<b>{html.escape(app['name'])}</b><br>"
                       f"<span style='color:{DIM}'>{html.escape(app['target'] or app['lnk'])}</span><br>"
                       f"<span style='color:{DIM}'>修改于 {app.get('mtime') or '—'} · "
                       f"{html.escape(app['cat'])}</span>", 3800)

    def on_card_click(self, card):
        if self.edit_mode:
            return
        now = time.time()
        if now - getattr(card, '_last_click', 0.0) < CLICK_DEDUPE:
            return
        card._last_click = now
        self.launch_card(card)

    def launch_card(self, card):
        app = card.app
        try:
            # UWP：AUMID 经 shell:AppsFolder 启动；桌面应用仍走 lnk 本体
            tgt = 'shell:AppsFolder\\' + app['target'] \
                if app['lnk'].startswith('uwp:') else app['lnk']
            os.startfile(tgt)
        except Exception as ex:
            self.toast(f'启动失败：<b>{html.escape(app["name"])}</b><br>'
                       f"<span style='color:{DIM}'>{html.escape(str(ex))}</span>", 3000)
            return
        card.set_launching(True)
        self._record_recent(app['lnk'])
        self.toast(f'正在启动 <b>{html.escape(app["name"])}</b> …')
        QTimer.singleShot(700, lambda: self._finish_launching(card))
        QTimer.singleShot(450, self.hide_to_tray)

    def _finish_launching(self, card):
        try:
            card.set_launching(False)
        except RuntimeError:
            return                      # 700ms 内卡片被移除：已删对象不可再碰
        self.toast(f'<b>{html.escape(card.app["name"])}</b> 已启动')

    def on_card_launching(self, card, on):
        if on and card not in self._launching_cards:
            self._launching_cards.append(card)
            if not self._launch_timer.isActive():
                self._launch_timer.start(33)         # 有转圈才跑定时器
        elif not on and card in self._launching_cards:
            self._launching_cards.remove(card)
            if not self._launching_cards:
                self._launch_timer.stop()

    def _tick_launching(self):
        for c in list(self._launching_cards):
            try:
                c._tick_spin()
            except RuntimeError:        # 卡片已被销毁但未出列（重启扫描竞态兜底）
                self._launching_cards.remove(c)

    # ---------- 鼠标（窗口层处理，卡片点击在此派发） ----------

    def eventFilter(self, obj, e):
        """搜索框 Esc：有内容先清空；空则传播到窗口（最小化）"""
        if obj is self.search and e.type() == QEvent.KeyPress and e.key() == Qt.Key_Escape:
            self._search_escape()
            return True
        return super().eventFilter(obj, e)

    def mousePressEvent(self, e):
        # 无边框窗口拖拽：顶栏空白区域（非搜索框/按钮）startSystemMove
        if e.button() == Qt.LeftButton and e.position().y() < self._top_h:
            child = self.childAt(e.position().toPoint())
            if child is None or child in (self._top_host, self.clock, self.date):
                wh = self.windowHandle()
                if wh:
                    wh.startSystemMove()
                return
        if e.button() == Qt.LeftButton:
            self._press_global = e.globalPosition().toPoint()
        elif e.button() == Qt.RightButton:
            self._press_global_r = e.globalPosition().toPoint()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        btn = e.button()
        if btn == Qt.LeftButton and self._press_global is not None:
            pos = self.canvas.mapFromGlobal(self._press_global)
            card = self.canvas.childAt(pos)
            if isinstance(card, Card):
                self.on_card_click(card)
        elif btn == Qt.RightButton and self._press_global_r is not None:
            # 右键空白处弹菜单
            pos = self.canvas.mapFromGlobal(self._press_global_r)
            if not isinstance(self.canvas.childAt(pos), Card):
                self._window_menu(self._press_global_r)
        self._press_global = None
        self._press_global_r = None
        super().mouseReleaseEvent(e)

    # ---------- 筛选 ----------
    def set_category(self, cat):
        self.cat = cat
        for c, b in self._cat_buttons.items():
            b.setChecked(c == cat)
        self._apply_filter()

    def _apply_filter(self):
        self.query = self.search.text().strip().lower()
        for card in self.canvas.cards:
            a = card.app
            ok = (self.cat == '全部' or a['cat'] == self.cat) and \
                 (not self.query or self.query in a['name'].lower()
                  or self.query in a['cat'].lower())
            card.setVisible(ok)
            if not ok:
                card.release_face()
        self._apply_recent_order(animate=False)
        self._update_rowtitle()
        self._update_empty_state()
        self._update_edge_fades()
        self.set_focus(0)

    # ---------- 托盘 / 生命周期 ----------
    def hide_to_tray(self):
        if self.isVisible():
            self.hide()
            self.tray.showMessage('桌面启动器',
                                  '应用已启动，启动器已收起（点击托盘图标恢复）',
                                  QSystemTrayIcon.Information, 1500)

    def _toggle_maximized(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def show_from_tray(self):
        if getattr(self, '_was_fullscreen', True):
            self.showFullScreen()
        else:
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:       # 左键单击：显示 / 收起
            if self.isVisible():
                self.hide()
            else:
                self.show_from_tray()

    def _on_screen_changed(self, geo):
        """显示器变更（DPI / 分辨率）→ 全部位图缓存失效重建"""
        self._bg = None
        self._glow_from_pm = None
        self._glow_to_pm = None
        for c in self.canvas.cards:
            c.release_face()
        self.update()

    def _start_ipc_server(self):
        """单实例 IPC：第二个进程启动时经此唤起本窗口"""
        QLocalServer.removeServer(SINGLETON_KEY)    # 清理崩溃残留
        self._ipc_server = QLocalServer(self)
        self._ipc_server.listen(SINGLETON_KEY)
        logging.info('IPC: server listening on %s', SINGLETON_KEY)
        self._ipc_server.newConnection.connect(self._on_ipc_connection)

    def _start_qml_background(self):
        """GPU 加速背景层（QQuickWidget），替代 paintEvent 的 CPU 位图绘制"""
        try:
            from PySide6.QtQuickWidgets import QQuickWidget
            from PySide6.QtCore import QUrl
            qml_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'background.qml')
            if not os.path.exists(qml_path):
                return
            noise_path = os.path.join(CACHE_DIR, 'noise_tile.png')
            os.makedirs(CACHE_DIR, exist_ok=True)
            noise_tile().toImage().save(noise_path, 'PNG')

            self._bg_layer = QQuickWidget(self)
            self._bg_layer.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
            self._bg_layer.setClearColor(Qt.transparent)
            self._bg_layer.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self._bg_layer.rootContext().setContextProperty(
                'noisePath', QUrl.fromLocalFile(noise_path).toString())
            self._bg_layer.setSource(QUrl.fromLocalFile(qml_path))
            # glowAnimMs 用 rootObject().setProperty 注入（root property 而非 context property）
            root = self._bg_layer.rootObject()
            if root:
                root.setProperty('glowAnimMs', 400 if ANIM_ENABLED else 0)
            if self._bg_layer.status() == QQuickWidget.Status.Error:
                for err in self._bg_layer.errors():
                    logging.warning('QML error: %s', err.toString())
                self._bg_layer = None
                return
            # 补发 QML 加载前暂存的辉光色
            pending = getattr(self, '_pending_qml_glow', None)
            if pending:
                root = self._bg_layer.rootObject()
                if root:
                    root.setProperty('gllowColor' if False else 'glowColor', pending)
            self._bg_layer.setGeometry(0, 0, self.width(), self.height())
            self._bg_layer.show()
            self._bg_layer.lower()
        except Exception:
            logging.exception('QML 背景层初始化失败，回退 CPU 绘制')
            self._bg_layer = None

    def _set_qml_glow(self, color_hex):
        """通知 QML 层更新辉光颜色（root object property，绑定会自动重评估）"""
        layer = getattr(self, '_bg_layer', None)
        if layer is not None and layer.rootObject():
            layer.rootObject().setProperty('glowColor', color_hex)
        elif layer is not None:
            self._pending_qml_glow = color_hex   # QML 未就绪：暂存，加载完成后补发

    def _on_ipc_connection(self):
        logging.info('IPC: newConnection')
        while self._ipc_server.hasPendingConnections():
            sock = self._ipc_server.nextPendingConnection()
            if sock is None:
                return
            sock.readyRead.connect(lambda s=sock: self._on_ipc_data(s))
            if sock.bytesAvailable() > 0:
                self._on_ipc_data(sock)     # 数据可能先于信号连接到达

    def _on_ipc_data(self, sock):
        try:
            data = bytes(sock.readAll())
            logging.info('IPC: data=%r', data)
            if b'show' in data:
                self.show_from_tray()
            sock.disconnectFromServer()
        except Exception:
            pass

    def closeEvent(self, e):
        for t in (self._clock_timer, self._glow_timer, self._search_timer,
                  self._launch_timer, self._hover_timer, self._edit_timer):
            t.stop()
        if self._adder is not None and self._adder.isRunning():
            self._adder.wait(1500)
        if self.worker.isRunning():
            self.worker.cancel()
            try:
                self.worker.batch.disconnect()
                self.worker.done.disconnect()
            except Exception:
                pass
            self.worker.wait(2500)
            if self.worker.isRunning():
                logging.warning('退出时扫描线程未按时结束，进程将强制回收')
        if self.tray.isVisible():
            self.tray.hide()
        super().closeEvent(e)
        QApplication.instance().quit()

    # ---------- toast ----------
    def toast(self, html_text, dur=2200):
        box = QLabel(self)
        box.setTextFormat(Qt.RichText)
        box.setText(html_text)
        box.setStyleSheet(TOAST_QSS)
        box.adjustSize()
        y = self.height() - BAR_H - 46 - sum(b.height() + 8 for b in self.toasts)
        ex, ey = self.width() - box.width() - 26, max(8, y)
        if ANIM_ENABLED:
            box.move(ex + 26, ey)                # 从右侧 26px 滑入
        else:
            box.move(ex, ey)                     # 减少动画：直接就位
        box.show()
        box.raise_()
        if ANIM_ENABLED:
            slide = QPropertyAnimation(box, b'pos', box)
            slide.setDuration(DUR_FAST + 20)
            slide.setStartValue(box.pos())
            slide.setEndValue(QPoint(ex, ey))
            slide.setEasingCurve(QEasingCurve.OutCubic)
            slide.start()
            eff = QGraphicsOpacityEffect(box)
            box.setGraphicsEffect(eff)
            eff.setOpacity(1.0)
        self.toasts.append(box)

        def fade():
            if box in self.toasts:
                self.toasts.remove(box)
            if ANIM_ENABLED and box.graphicsEffect() is not None:
                anim = QPropertyAnimation(box.graphicsEffect(), b'opacity', box)
                anim.setDuration(DUR_BASE)
                anim.setStartValue(1.0)
                anim.setEndValue(0.0)
                anim.finished.connect(box.deleteLater)
                anim.start()
            else:
                box.deleteLater()
            self._reflow_toasts()
        QTimer.singleShot(dur, fade)

    def _reflow_toasts(self):
        """toast 消失后其余回填空位（自下而上重新堆叠）"""
        y = self.height() - BAR_H - 46
        for b in self.toasts:
            if not b.isHidden():
                b.move(b.x(), max(8, y))
                y -= b.height() + 8

    # ---------- 键盘 ----------
    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key_Q and (e.modifiers() & Qt.ControlModifier):
            self.close()
        elif k == Qt.Key_Z and (e.modifiers() & Qt.ControlModifier):
            self._undo_last_remove()
        elif k == Qt.Key_Escape:
            if self.edit_mode:
                self.set_edit_mode(False)
            else:
                self.showMinimized()
        elif k in (Qt.Key_Right, Qt.Key_Down):
            self.set_focus(self.focus_idx + 1)
        elif k in (Qt.Key_Left, Qt.Key_Up):
            self.set_focus(self.focus_idx - 1)
        elif k in (Qt.Key_Return, Qt.Key_Enter):
            self.launch_focused()
        elif (not (e.modifiers() & ~Qt.ShiftModifier)) and e.text() and e.text().isprintable():
            # 键盘直达：任意可打印字符直接落入搜索框（启动器的效率灵魂）
            # 注意：PySide6 6.12 起 IntFlag == int 比较恒 False，须用真值判断
            self.search.setFocus()
            cur = self.search.text() + e.text()
            self.search.setText(cur)
            self.search.setCursorPosition(len(cur))
        else:
            super().keyPressEvent(e)

# ============================================================
# 样式（全部由 theme.py token 拼装）
# ============================================================
SEARCH_QSS = ('QLineEdit{background:%s;border:1px solid %s;'
              'color:%s;font-size:%dpx;padding:8px 14px;border-radius:999px;}'
              'QLineEdit:focus{border-color:%s;background:%s;}' % (
                  rgba(WHITE_RGB, 15), rgba(WHITE_RGB, 26), TEXT, FS_BODY,
                  rgba(ACCENT_RGB, 165), rgba(ACCENT_RGB, 20)))
PRIMARY_QSS = ('QPushButton{background:%s;border:0;color:%s;font-size:%dpx;'
               'font-weight:600;padding:9px 26px;border-radius:10px;}'
               'QPushButton:hover{background:%s;}' % (TEXT, BG_BASE, FS_BODY, WHITE))
GHOST_QSS = ('QPushButton{background:transparent;border:1px solid %s;'
             'color:%s;font-size:%dpx;padding:9px 22px;border-radius:10px;}'
             'QPushButton:hover{color:%s;background:%s;}' % (
                 rgba(WHITE_RGB, 30), DIM, FS_BODY, TEXT, rgba(WHITE_RGB, 18)))
TOAST_QSS = ('QLabel{background:%s;border:1px solid %s;'
             'color:%s;font-size:%dpx;padding:10px 16px;border-radius:12px;}'
             'QLabel b{color:%s;}' % (
                 rgba(TOAST_RGB, 217), rgba(WHITE_RGB, 30), TEXT, FS_BODY, HIGH_BLUE))
QMENU_QSS = ('QMenu{background:%s;border:1px solid %s;border-radius:10px;padding:6px;}'
             'QMenu::item{color:%s;font-size:%dpx;padding:7px 26px 7px 16px;border-radius:6px;}'
             'QMenu::item:selected{background:%s;color:%s;}'
             'QMenu::separator{height:1px;background:%s;margin:5px 8px;}' % (
                 rgba(HERO_RGB, 242), rgba(WHITE_RGB, 26), TEXT, FS_BODY,
                 rgba(ACCENT_RGB, 60), WHITE, rgba(WHITE_RGB, 26)))

# ============================================================
# 入口
# ============================================================
def _autostart_targets():
    """自启目标：打包环境指向 exe 本体；脚本环境指向 pythonw + 脚本"""
    if getattr(sys, 'frozen', False):
        return sys.executable, ''
    pyw = sys.executable.replace('python.exe', 'pythonw.exe')
    script = os.path.abspath(__file__)
    return pyw, '"%s"' % script

def autostart():
    try:
        target, args = _autostart_targets()
        startup = os.path.expandvars(r'%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup')
        lnk_path = os.path.join(startup, '桌面启动器.lnk')
        if not HAVE_COM:
            print('[autostart] 需要 pywin32：pip install pywin32')
            return
        pythoncom.CoInitialize()
        ws = win32com.client.Dispatch('WScript.Shell')
        s = ws.CreateShortCut(lnk_path)
        s.TargetPath = target
        s.Arguments = args
        s.WorkingDirectory = os.path.dirname(target)
        s.Save()
        print('[autostart] 已创建 ->', lnk_path)
        logging.info('autostart: %s -> %s %s', lnk_path, target, args)
    except Exception as ex:
        print('[autostart] 失败：', ex)
        logging.exception('autostart failed')

def uninstall():
    """--uninstall：移除开机自启；缓存数据一并清除（--keep-cache 可保留；日志保留）"""
    keep_cache = '--keep-cache' in sys.argv[1:]
    lnk_path = os.path.join(os.path.expandvars(
        r'%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup'), '桌面启动器.lnk')
    if os.path.exists(lnk_path):
        os.remove(lnk_path)
        print('[uninstall] 已删除开机自启:', lnk_path)
    else:
        print('[uninstall] 未发现开机自启')
    if keep_cache:
        print('[uninstall] 缓存保留（--keep-cache）')
    elif os.path.isdir(CACHE_DIR):
        for entry in os.listdir(CACHE_DIR):
            if entry == 'logs':
                continue                    # 日志保留，便于事后排查
            p = os.path.join(CACHE_DIR, entry)
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    os.remove(p)
                except OSError:
                    pass
        print('[uninstall] 已清除缓存数据（日志保留）:', CACHE_DIR)
    else:
        print('[uninstall] 无缓存')
    logging.info('uninstall: keep_cache=%s', keep_cache)

def main():
    args = sys.argv[1:]
    if '--autostart' in args:
        autostart()
        return
    if '--uninstall' in args:
        uninstall()
        return
    app = QApplication(sys.argv)
    app.setApplicationName('桌面启动器')
    app.setQuitOnLastWindowClosed(False)
    f = QFont(FONT_UI)
    f.setPixelSize(FS_BODY)
    app.setFont(f)
    if not _acquire_single_instance():
        logging.info('单实例：已有实例在运行，唤起后退出')
        _activate_running_instance()
        return
    win = LauncherWindow(windowed='--windowed' in args)
    win._was_fullscreen = '--windowed' not in args
    if '--windowed' in args:
        win.show()
    else:
        win.showFullScreen()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()

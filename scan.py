# -*- coding: utf-8 -*-
"""scan.py — 扫描与图标提取（纯逻辑模块，可独立测试）
   UI 类在 launcher.py；本模块不导入 QtWidgets。"""
import ctypes
import ctypes.wintypes as wt
import hashlib
import logging
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime

from store import (ICON_DIR, load_meta, save_meta, merge_meta,
                   load_custom_store, save_custom_store)
from theme import ACCENT
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QImage

try:
    import pythoncom
    import win32com.client
    HAVE_COM = True
except Exception:
    HAVE_COM = False
_shell_tls = threading.local()

def resolve_lnk(path):
    if not HAVE_COM:
        return '', '', ''
    try:
        shell = getattr(_shell_tls, 'shell', None)
        if shell is None:
            pythoncom.CoInitialize()
            shell = win32com.client.Dispatch('WScript.Shell')
            _shell_tls.shell = shell
        s = shell.CreateShortCut(path)
        return (s.Targetpath or '', s.Arguments or '', s.WorkingDirectory or '')
    except Exception:
        return '', '', ''

# ============================================================
# 图标提取（ctypes: SHGetFileInfo + 共享 ImageList → QImage）
# ============================================================
_user32 = ctypes.windll.user32
_gdi32 = ctypes.windll.gdi32
_shell32 = ctypes.windll.shell32
_comctl32 = ctypes.windll.comctl32

# Win32 原生调用签名：防 64 位截断与参数错位（ctypes 默认返回 c_int）
_VP = ctypes.c_void_p
_shell32.SHParseDisplayName.argtypes = [ctypes.c_wchar_p, _VP, ctypes.POINTER(_VP),
                                        ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
_shell32.SHCreateItemFromIDList.argtypes = [_VP, ctypes.POINTER(ctypes.c_ubyte * 16),
                                            ctypes.POINTER(_VP)]
_shell32.SHGetImageList.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_ubyte * 16),
                                    ctypes.POINTER(_VP)]
_shell32.SHGetFileInfoW.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
                                    ctypes.c_uint32, ctypes.c_uint32]   # 首参兼容路径与 PIDL
_comctl32.ImageList_GetIcon.argtypes = [_VP, ctypes.c_int, ctypes.c_uint]
_comctl32.ImageList_GetIcon.restype = _VP
_user32.DrawIconEx.argtypes = [_VP, ctypes.c_int, ctypes.c_int, _VP,
                               ctypes.c_int, ctypes.c_int, ctypes.c_uint, _VP, ctypes.c_uint]
_user32.DestroyIcon.argtypes = [_VP]
_gdi32.GetObjectW.argtypes = [_VP, ctypes.c_int, ctypes.c_void_p]
_gdi32.CreateDIBSection.argtypes = [_VP, ctypes.c_void_p, ctypes.c_uint,
                                    ctypes.POINTER(_VP), _VP, ctypes.c_uint32]
_gdi32.DeleteObject.argtypes = [_VP]
ctypes.windll.kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                                ctypes.c_wchar_p]

class SHFILEINFOW(ctypes.Structure):
    _fields_ = [('hIcon', wt.HICON), ('iIcon', ctypes.c_int), ('dwAttributes', ctypes.c_uint),
                ('szDisplayName', ctypes.c_wchar * 260), ('szTypeName', ctypes.c_wchar * 80)]

SHGFI_SYSICONINDEX = 0x4000
SHIL_EXTRALARGE = 0x2
SHIL_JUMBO = 0x4
ILD_NORMAL = 0x0
DI_NORMAL = 0x3
IID_IIMAGELIST = (ctypes.c_ubyte * 16)(0x26, 0x59, 0xEB, 0x46, 0x2E, 0x58, 0x17, 0x40,
                                       0x9F, 0xDF, 0xE8, 0x99, 0x8D, 0xAA, 0x09, 0x50)

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [('biSize', ctypes.c_uint32), ('biWidth', ctypes.c_int32), ('biHeight', ctypes.c_int32),
                ('biPlanes', ctypes.c_uint16), ('biBitCount', ctypes.c_uint16), ('biCompression', ctypes.c_uint32),
                ('biSizeImage', ctypes.c_uint32), ('biXPelsPerMeter', ctypes.c_int32),
                ('biYPelsPerMeter', ctypes.c_int32), ('biClrUsed', ctypes.c_uint32), ('biClrImportant', ctypes.c_uint32)]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [('bmiHeader', BITMAPINFOHEADER), ('bmiColors', ctypes.c_uint32 * 3)]

def _has_alpha(img):
    try:
        buf = img.constBits()
        return any(buf[3::4])
    except Exception:
        for y in range(0, img.height(), 4):
            for x in range(0, img.width(), 4):
                if (img.pixel(x, y) >> 24) & 0xFF:
                    return True
    return False

def _hicon_to_qimage(hicon, size):
    img = None
    hdc = _user32.GetDC(None)
    mem = None
    dib = None
    try:
        mem = _gdi32.CreateCompatibleDC(hdc)
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = size
        bmi.bmiHeader.biHeight = -size
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0
        bits = ctypes.c_void_p()
        dib = _gdi32.CreateDIBSection(hdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        if dib and bits:
            old = _gdi32.SelectObject(mem, dib)
            _user32.DrawIconEx(mem, 0, 0, hicon, size, size, 0, None, DI_NORMAL)
            _gdi32.SelectObject(mem, old)
            buf = ctypes.string_at(bits, size * size * 4)
            qimg = QImage(buf, size, size, size * 4, QImage.Format_ARGB32)
            img = qimg.copy()
            if not _has_alpha(img):
                img = img.convertToFormat(QImage.Format_RGB32)
    finally:
        if dib:
            _gdi32.DeleteObject(dib)
        if mem:
            _gdi32.DeleteDC(mem)
        _user32.ReleaseDC(None, hdc)
    return img

def extract_icon(path, size=256, _il_cache={}, _il_lock=threading.Lock()):
    try:
        shfi = SHFILEINFOW()
        ok = _shell32.SHGetFileInfoW(ctypes.c_wchar_p(path), 0, ctypes.byref(shfi), ctypes.sizeof(SHFILEINFOW),
                                     SHGFI_SYSICONINDEX)
        if not ok:
            return None
        for shil in (SHIL_JUMBO, SHIL_EXTRALARGE):
            with _il_lock:                 # 并行提取线程共享此缓存：加锁防双重初始化
                il = _il_cache.get(shil)
                if not il:
                    il = ctypes.c_void_p()
                    hr = _shell32.SHGetImageList(shil, ctypes.byref(IID_IIMAGELIST), ctypes.byref(il))
                    if hr != 0 or not il:
                        continue
                    _il_cache[shil] = il
            hicon = _comctl32.ImageList_GetIcon(il, shfi.iIcon, ILD_NORMAL)
            if not hicon:
                continue
            img = _hicon_to_qimage(hicon, size)
            _user32.DestroyIcon(hicon)
            if img and not img.isNull():
                return img
    except Exception:
        pass
    return None

def icon_for_path(path, size=256):
    img = extract_icon(path, size)
    if img:
        return img
    try:
        from PySide6.QtWidgets import QFileIconProvider
        from PySide6.QtCore import QFileInfo
        ic = QFileIconProvider().icon(QFileInfo(path))
        if not ic.isNull():
            pm = ic.pixmap(size, size)
            if not pm.isNull():
                return pm.toImage()
    except Exception:
        pass
    return None

# ============================================================
# UWP / 商店应用（shell:AppsFolder 枚举 + IShellItemImageFactory 图标）
# ============================================================
UWP_ENABLED = os.environ.get('AL_UWP', '1') != '0'   # AL_UWP=0 可关闭（部分测试用）
UWP_CAT = '商店应用'
IID_ISHELLITEMIMAGEFACTORY = (ctypes.c_ubyte * 16).from_buffer_copy(
    uuid.UUID('{bcc18b79-ba16-442f-80c4-8a59c30c463b}').bytes_le)   # 实测对照 win32metadata 修正

class _SIZE(ctypes.Structure):
    _fields_ = [('cx', ctypes.c_long), ('cy', ctypes.c_long)]

class _BITMAP(ctypes.Structure):
    _fields_ = [('bmType', ctypes.c_long), ('bmWidth', ctypes.c_long),
                ('bmHeight', ctypes.c_long), ('bmWidthBytes', ctypes.c_long),
                ('bmPlanes', ctypes.c_uint16), ('bmBitsPixel', ctypes.c_uint16),
                ('bmBits', ctypes.c_void_p)]

def _hbitmap_to_qimage(hbmp):
    """GDI HBITMAP(32bpp) → QImage（GetImage 返回预乘 ARGB，底朝上时翻转）"""
    try:
        bm = _BITMAP()
        if not _gdi32.GetObjectW(hbmp, ctypes.sizeof(_BITMAP), ctypes.byref(bm)):
            return None
        w, h = bm.bmWidth, abs(bm.bmHeight)
        if w <= 0 or h <= 0 or bm.bmBitsPixel != 32 or not bm.bmBits:
            return None
        buf = ctypes.string_at(bm.bmBits, bm.bmWidthBytes * h)
        img = QImage(buf, w, h, bm.bmWidthBytes, QImage.Format_ARGB32_Premultiplied)
        img = img.copy()
        if bm.bmHeight > 0:
            img = img.mirrored(False, True)
        return img.convertToFormat(QImage.Format_ARGB32)
    except Exception:
        return None

def uwp_icon_image(aumid, size=256):
    """UWP 应用图标。
       路线 1：IShellItemImageFactory::GetImage（256px 高清，正常 Windows 可用）；
       路线 2：SHGetFileInfoW(PIDL, SHGFI_ICON) → hIcon —— 对 COM 环境限制免疫，实测 8/8。
       两路都失败 → None（首字母占位兜底）。"""
    if not HAVE_COM:
        return None
    pidl = ctypes.c_void_p()
    try:
        hr = _shell32.SHParseDisplayName(ctypes.c_wchar_p('shell:AppsFolder\\' + aumid),
                                         None, ctypes.byref(pidl), 0, None)
        if hr != 0 or not pidl:
            return None

        # 路线 1：IShellItemImageFactory::GetImage
        ppv = ctypes.c_void_p()
        hr = _shell32.SHCreateItemFromIDList(pidl, IID_ISHELLITEMIMAGEFACTORY,
                                             ctypes.byref(ppv))
        if hr == 0 and ppv:
            hbmp = ctypes.c_void_p()
            try:
                vt = ctypes.cast(ctypes.cast(ppv, ctypes.POINTER(ctypes.c_void_p)).contents,
                                 ctypes.POINTER(ctypes.c_void_p * 16)).contents
                gi = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p,
                                        _SIZE, ctypes.c_uint,
                                        ctypes.POINTER(ctypes.c_void_p))(vt[3])
                hr = gi(ppv, _SIZE(size, size), 0, ctypes.byref(hbmp))
                if hr == 0 and hbmp:
                    img = _hbitmap_to_qimage(hbmp)
                    if img is not None and not img.isNull():
                        return img
            finally:
                if hbmp:
                    _gdi32.DeleteObject(hbmp)
                try:                            # IUnknown::Release
                    rel = ctypes.cast(ctypes.cast(ppv, ctypes.POINTER(ctypes.c_void_p)).contents,
                                      ctypes.POINTER(ctypes.c_void_p * 16)).contents[2]
                    ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(rel)(ppv)
                except Exception:
                    pass

        # 路线 2：SHGetFileInfoW(PIDL, SHGFI_ICON) → hIcon（32/64px，质量足够芯片显示）
        sfi = SHFILEINFOW()
        hr = _shell32.SHGetFileInfoW(pidl, 0, ctypes.byref(sfi), ctypes.sizeof(SHFILEINFOW),
                                     0x100 | 0x8)   # SHGFI_ICON | SHGFI_PIDL
        if hr != 0 and sfi.hIcon:
            img = _hicon_to_qimage(sfi.hIcon, 64)
            _user32.DestroyIcon(sfi.hIcon)
            if img is not None and not img.isNull():
                return img
        return None
    finally:
        if pidl:
            ctypes.windll.ole32.CoTaskMemFree(pidl)

_uwp_cache = {'ts': 0.0, 'apps': []}
UWP_CACHE_TTL = 86400                # 24h：UWP 列表变化极慢，缓存避免每轮 ~0.9s COM 枚举
UWP_CACHE_PATH = os.path.join(os.path.dirname(ICON_DIR), 'uwp_cache.json')

def _load_uwp_disk():
    """从磁盘读取 UWP 列表缓存（跨进程生效）"""
    try:
        with open(UWP_CACHE_PATH, 'r', encoding='utf-8') as f:
            d = json.load(f)
        if time.time() - d.get('ts', 0) < UWP_CACHE_TTL:
            return [(a, b) for a, b in d.get('apps', [])]
    except Exception:
        pass
    return None

def _save_uwp_disk(apps):
    try:
        os.makedirs(os.path.dirname(UWP_CACHE_PATH), exist_ok=True)
        with open(UWP_CACHE_PATH, 'w', encoding='utf-8') as f:
            json.dump({'ts': time.time(), 'apps': apps}, f, ensure_ascii=False)
    except Exception:
        pass

def enumerate_uwp_apps():
    """枚举 shell:AppsFolder 里的 UWP/商店应用 → [(name, aumid)]
       AUMID 判定：Path 含 '!' 且无盘符/反斜杠/::（桌面 exe 与 Control Panel 项被排除）
       三级缓存：进程内存 → 磁盘 JSON（24h TTL）→ COM 枚举"""
    global _uwp_cache
    now = time.time()
    if now - _uwp_cache['ts'] < UWP_CACHE_TTL:
        return _uwp_cache['apps']
    disk = _load_uwp_disk()
    if disk is not None:
        _uwp_cache = {'ts': now, 'apps': disk}
        return disk
    if not HAVE_COM:
        return []
    out, seen = [], set()
    try:
        shell = win32com.client.Dispatch('Shell.Application')
        folder = shell.NameSpace('shell:AppsFolder')
        for item in folder.Items():
            try:
                path = item.Path
                name = item.Name
            except Exception:
                continue
            if not path or not name:
                continue
            if ('!' not in path or '\\' in path or ':' in path
                    or path.startswith('::')):
                continue
            if path in seen:
                continue
            seen.add(path)
            out.append((name, path))
    except Exception:
        return []
    _uwp_cache = {'ts': now, 'apps': out}
    _save_uwp_disk(out)
    return out

def build_uwp_app(name, aumid, mt=0):
    """UWP 应用卡片数据：target=AUMID，启动走 shell:AppsFolder；图标/缩略图/主色同管线"""
    img = uwp_icon_image(aumid)
    img = _trim_icon_border(img)
    tint = dominant_tint(img)
    icon_file = None
    thumb_file = None
    if img is not None:
        # 始终放大到 160px（RESIZEFIT 不放大，小图源需手动上采样填充海报位）
        big = img.scaled(160, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        icon_file = _icon_cache_path('uwp:' + aumid)
        big.save(icon_file, 'PNG')
        thumb_file = _thumb_cache_path('uwp:' + aumid)
        img.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(thumb_file, 'PNG')
    app = {'name': name, 'lnk': 'uwp:' + aumid, 'cat': UWP_CAT,
           'target': aumid, 'mtime': '', 'img': img, 'tint': tint, 'args': '',
           'icon_file': os.path.basename(icon_file) if icon_file else None,
           'thumb_file': os.path.basename(thumb_file) if thumb_file else None}
    entry = {'mt': mt, 'name': name, 'cat': UWP_CAT, 'target': aumid, 'mtime': '',
             'icon': os.path.basename(icon_file) if icon_file else None,
             'thumb': os.path.basename(thumb_file) if thumb_file else None,
             'noicon': img is None, 'failat': time.time() if img is None else 0,
             'tint': tint.name(), 'v': 3, 'uwp': 1, 'args': ''}
    return app, entry

# ============================================================
# 主色提取 + 降饱和（视觉 token）
# ============================================================
def dominant_tint(img):
    if img is None or img.isNull():
        return QColor(ACCENT)
    small = img.scaled(14, 14).convertToFormat(QImage.Format_RGB32)
    try:
        buf = small.constBits()
        stride = small.bytesPerLine()
        buckets = {}
        for y in range(small.height()):
            row = y * stride
            for x in range(small.width()):
                i = row + x * 4
                b, g, r = buf[i], buf[i + 1], buf[i + 2]
                mx = max(r, g, b)
                mn = min(r, g, b)
                if mx == 0 or (mx - mn) * 100 // mx < 18 or mx < 30:
                    continue
                h, s, v = QColor(r, g, b).getHsvF()
                if s < 0.18 or v < 0.12:
                    continue
                key = int((h if h >= 0 else 0.62) * 12) % 12
                e = buckets.setdefault(key, [0, 0, 0, 0])
                e[0] += 1
                e[1] += r; e[2] += g; e[3] += b
    except Exception:
        return QColor(ACCENT)
    if not buckets:
        return QColor(ACCENT)
    best = max(buckets.values(), key=lambda e: e[0])
    col = QColor(best[1] // best[0], best[2] // best[0], best[3] // best[0])
    if col.valueF() > 0.92:
        col = col.darker(115)
    if col.valueF() < 0.45:
        col = col.lighter(140)
    return col

def muted_tint(color):
    """主色压饱和：S≤0.45，V 限定 0.55–0.70"""
    c = QColor(color)
    h, s, v, _a = c.getHsvF()
    s = min(s if s >= 0 else 0.35, 0.45)
    v = min(0.70, max(0.55, v))
    c.setHsvF(h if h >= 0 else 0.58, s, v)
    return c

# ============================================================
# 磁盘缓存
# ============================================================
def _icon_cache_path(lnk):
    h = hashlib.md5(lnk.lower().encode('utf-8')).hexdigest()[:16]
    return os.path.join(ICON_DIR, h + '_c.png')

def _thumb_cache_path(lnk):
    h = hashlib.md5(lnk.lower().encode('utf-8')).hexdigest()[:16]
    return os.path.join(ICON_DIR, h + '_t.png')

def _trim_icon_border(img):
    """裁掉图标四周的纯色/透明边（如白边 letterbox），让内容铺满芯片。
       用 64×64 缩略图找内容 bbox，按比例映射回原图裁剪。
       仅当 bbox 面积占 25%–97% 时裁剪（太小=噪声，太满=无需裁）。"""
    try:
        if img is None or img.isNull():
            return img
        small = img.scaled(64, 64, Qt.IgnoreAspectRatio,
                           Qt.SmoothTransformation).convertToFormat(QImage.Format_ARGB32)
        w, h = small.width(), small.height()
        buf = small.constBits()
        stride = small.bytesPerLine()

        def px(x, y):
            i = y * stride + x * 4
            return buf[i], buf[i + 1], buf[i + 2], buf[i + 3]

        corners = [px(0, 0), px(w - 1, 0), px(0, h - 1), px(w - 1, h - 1)]
        cr = sum(c[0] for c in corners) // 4
        cg = sum(c[1] for c in corners) // 4
        cb = sum(c[2] for c in corners) // 4
        ca = sum(c[3] for c in corners) // 4
        TH = 28

        def is_bg(x, y):
            r, g, b, a = px(x, y)
            return (abs(r - cr) <= TH and abs(g - cg) <= TH and
                    abs(b - cb) <= TH and abs(a - ca) <= TH)

        top = 0
        while top < h and all(is_bg(x, top) for x in range(w)):
            top += 1
        if top >= h:
            return img
        bottom = h - 1
        while bottom > top and all(is_bg(x, bottom) for x in range(w)):
            bottom -= 1
        left = 0
        while left < w and all(is_bg(left, y) for y in range(top, bottom + 1)):
            left += 1
        right = w - 1
        while right > left and all(is_bg(right, y) for y in range(top, bottom + 1)):
            right -= 1

        area = (right - left + 1) * (bottom - top + 1) / (w * h)
        if area < 0.25 or area > 0.97:
            return img
        ow, oh = img.width(), img.height()
        mx, my = max(1, ow // 50), max(1, oh // 50)
        x0 = max(0, left * ow // w - mx)
        y0 = max(0, top * oh // h - my)
        x1 = min(ow, (right + 1) * ow // w + mx)
        y1 = min(oh, (bottom + 1) * oh // h + my)
        if x1 - x0 < ow * 0.2 or y1 - y0 < oh * 0.2:
            return img
        return img.copy(x0, y0, x1 - x0, y1 - y0)
    except Exception:
        return img


def build_app(path, name, cat, mt=None, target=None, args=None):
    """解析 lnk/exe → 应用卡片数据（目标 / 图标 / 主色 + 图标缓存）"""
    if target is None:
        target, args, _w = resolve_lnk(path)
    mt_src = target if (target and os.path.exists(target)) else path
    try:
        mtime = datetime.fromtimestamp(os.path.getmtime(mt_src)).strftime('%Y-%m-%d')
    except Exception:
        mtime = ''
    img = icon_for_path(target if (target and os.path.exists(target)) else path, 256)
    img = _trim_icon_border(img)          # 裁掉资源自带的白边/透明边
    tgtmt = 0
    if target and os.path.exists(target):
        try:
            tgtmt = int(os.path.getmtime(target))
        except OSError:
            tgtmt = 0
    tint = dominant_tint(img)
    icon_file = None
    thumb_file = None
    if img is not None:
        # 缓存 160px 主图 + 80px 缩略图；键 = mt_src（同 target 多 lnk 共享同一缓存文件）
        big = img.scaled(160, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation) \
            if (img.width() > 160 or img.height() > 160) else img
        icon_file = _icon_cache_path(mt_src)
        big.save(icon_file, 'PNG')
        thumb_file = _thumb_cache_path(mt_src)
        # 80px 缩略图：200% DPI 下 40 逻辑 px 需要更多像素才不糊
        img.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(thumb_file, 'PNG')
    app = {'name': name, 'lnk': path, 'cat': cat, 'target': target,
           'mtime': mtime, 'img': img, 'tint': tint, 'args': args or '',
           'icon_file': os.path.basename(icon_file) if icon_file else None,
           'thumb_file': os.path.basename(thumb_file) if thumb_file else None}
    if mt is None:
        try:
            mt = int(os.path.getmtime(path))
        except OSError:
            mt = 0
    entry = {'mt': mt, 'name': name, 'cat': cat, 'target': target, 'mtime': mtime,
             'args': args or '', 'tgtmt': tgtmt,
             'icon': os.path.basename(icon_file) if icon_file else None,
             'thumb': os.path.basename(thumb_file) if thumb_file else None,
             'noicon': img is None, 'failat': time.time() if img is None else 0,
             'tint': tint.name(), 'v': 3}
    return app, entry

# ============================================================
# 扫描线程（可取消 + 缓存加速）
# ============================================================
JUNK = re.compile(r'uninstall|卸载|unins\d|readme', re.I)

class ScanWorker(QThread):
    batch = Signal(list)
    done = Signal(int, float)
    EXTRACT_WORKERS = max(1, int(os.environ.get('AL_WORKERS', '4')))   # 并行提取线程数（实测 K=4 最优，可用 AL_WORKERS 调参）

    def __init__(self, customs=None, hidden=None, scan_enabled=True):
        super().__init__()
        self._stop = False
        self._customs = list(customs or [])
        self._hidden = set(hidden or [])
        self._scan_enabled = scan_enabled

    def cancel(self):
        self._stop = True

    def run(self):
        t0 = time.time()
        if HAVE_COM:
            try:
                pythoncom.CoInitialize()
            except Exception:
                pass
        try:
            self._scan(t0)
        except Exception:
            logging.exception('扫描线程异常')
        finally:
            if HAVE_COM:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

    def _extract_parallel(self, tasks):
        """K 线程并行 解析 lnk + 提取图标（冷启动主要耗时在此，并行度 ≈ 3x）。
           返回 {full: (app, entry)}；JUNK 目标 / 失败的路径不在结果里。"""
        from queue import Queue
        qout = Queue()
        cancel = threading.Event()
        chunks = [tasks[i::self.EXTRACT_WORKERS] for i in range(self.EXTRACT_WORKERS)]
        chunks = [c for c in chunks if c]

        def extract(chunk):
            if HAVE_COM:
                try:
                    pythoncom.CoInitialize()
                except Exception:
                    pass
            try:
                for full, name, cat, mt in chunk:
                    if cancel.is_set():
                        return
                    try:
                        if full.startswith('uwp:'):
                            app, entry = build_uwp_app(name, full[4:])
                        else:
                            target, _a, _w = resolve_lnk(full)
                            tlow = (target or '').lower()
                            if tlow and JUNK.search(os.path.splitext(os.path.basename(tlow))[0] or ''):
                                continue
                            # 首扫只收录目标为 .exe 的应用；其余格式（文件夹/文档/URL 等）
                            # 由用户「＋ 添加」或拖拽进入，不受此限。
                            # 注意：Win11 应用执行别名（calc 等 reparse point）os.path.exists 为 False，
                            # 因此只按扩展名判定，悬空 lnk 交由图标提取失败 → noicon 兜底。
                            if not tlow.endswith('.exe'):
                                continue
                            app, entry = build_app(full, name, cat, mt,
                                                   target=target, args=_a)
                        qout.put((full, app, entry))
                    except Exception:
                        continue
            finally:
                if HAVE_COM:
                    try:
                        pythoncom.CoUninitialize()
                    except Exception:
                        pass
                qout.put(None)            # 结束标记

        threads = [threading.Thread(target=extract, args=(c,), daemon=True) for c in chunks]
        for t in threads:
            t.start()
        results = {}
        done_cnt = 0
        while done_cnt < len(threads):
            if self._stop:
                cancel.set()
            try:
                item = qout.get(timeout=0.05)
            except Exception:
                if self._stop and qout.empty():
                    break                 # 取消且队列已空：立即收尾
                continue
            if item is None:
                done_cnt += 1
            else:
                full, app, entry = item
                results[full] = (app, entry)
        return results

    def _scan(self, t0):
        roots = []
        for var in (r'%APPDATA%\Microsoft\Windows\Start Menu\Programs',
                    r'%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs',
                    r'%USERPROFILE%\Desktop',
                    r'%PUBLIC%\Desktop'):
            p = os.path.expandvars(var)
            if os.path.isdir(p):
                roots.append(p)
        cache = load_meta()
        meta_new = {}
        seen_paths = set()
        emitted = []                      # 统一发射流：customs + 扫描项按序混排（一处计数、一处补尾）
        BATCH = 16
        n_cached = 0
        try:
            os.makedirs(ICON_DIR, exist_ok=True)
            for f in os.listdir(ICON_DIR):
                # 只清“无后缀标记”的历史遗留缓存；_c/_t 都是现行缓存，不能动
                if f.endswith('.png') and not (f.endswith('_c.png') or f.endswith('_t.png')):
                    os.remove(os.path.join(ICON_DIR, f))
        except Exception:
            pass

        # 1) 手动添加的应用（优先、置前）——并入统一发射流
        for path in self._customs:
            if self._stop:
                break
            if not os.path.exists(path):
                continue
            try:
                lnk_mt = int(os.path.getmtime(path))
            except OSError:
                continue
            name = os.path.splitext(os.path.basename(path))[0]
            entry = cache.get(path)
            app = None
            if entry and entry.get('mt') == lnk_mt and (entry.get('icon') or entry.get('noicon')):
                img = None
                thumb_file = entry.get('thumb')
                if thumb_file:
                    img = QImage(os.path.join(ICON_DIR, thumb_file))
                    if img.isNull():
                        img = None
                if img is None and entry.get('icon'):
                    img = QImage(os.path.join(ICON_DIR, entry['icon']))
                    if img.isNull():
                        img = None
                if img is not None or entry.get('noicon'):
                    n_cached += 1
                    meta_new[path] = entry
                    app = {'name': entry['name'], 'lnk': path, 'cat': entry['cat'],
                           'target': entry['target'], 'mtime': entry.get('mtime', ''),
                           'img': img, 'tint': QColor(entry.get('tint') or ACCENT),
                           'icon_file': entry.get('icon')}
            if app is None:
                app, entry2 = build_app(path, name, '自定义', lnk_mt)
                meta_new[path] = entry2
            seen_paths.add(path)
            emitted.append(app)
            if len(emitted) % BATCH == 0:
                self.batch.emit(emitted[-BATCH:])

        # 2) 收集候选（纯文件系统，快）：JUNK 名过滤 + mtime。
        #    无视 scan_enabled/hidden 也收集：这些路径必须进 seen_paths，
        #    否则「仅手动」会把全量缓存判过期、隐藏应用图标被当孤儿删光（P0-1）。
        #    名称不再去重：同名同目标由 target 去重兜底，同名不同目标应都显示。
        candidates = []                   # (full, name, cat, lnk_mt, hidden)
        for root in roots:
          if self._stop:
            break
          for dirpath, _dirs, files in os.walk(root):
            if self._stop:
                break
            for fn in files:
                if self._stop:
                    break
                if not fn.lower().endswith('.lnk'):
                    continue
                name = os.path.splitext(fn)[0].strip()
                if not name or JUNK.search(name):
                    continue
                full = os.path.join(dirpath, fn)
                try:
                    lnk_mt = int(os.path.getmtime(full))
                except OSError:
                    continue
                cat = '桌面'
                if 'Start Menu' in root:
                    rel = os.path.relpath(dirpath, root)
                    cat = rel.split(os.sep)[0] if rel and rel != '.' else '应用'
                candidates.append((full, name, cat, lnk_mt, full in self._hidden))

        # UWP/商店应用（无视 scan_enabled 也枚举：进 seen_paths 保住缓存，与 P0-1 同理）
        if UWP_ENABLED:
            uwp_apps = enumerate_uwp_apps()
            desktop_names = {c[1].casefold() for c in candidates}
            for name, aumid in uwp_apps:
                if name and name.casefold() not in desktop_names:
                    candidates.append(('uwp:' + aumid, name, UWP_CAT, 0,
                                       ('uwp:' + aumid) in self._hidden))
        seen_paths.update(c[0] for c in candidates)   # 存在于磁盘 → 缓存一律保留
        # P0：AL_UWP=0 或 UWP 枚举跳过时，缓存的 uwp:* 条目仍需保留
        # （否则 merge_meta 判过期 → 孤儿清扫删图标 → 切回全量全量重提）
        seen_paths.update(k for k in cache if k.startswith('uwp:'))

        # 3) 缓存命中（流式发射：命中即出卡，不等提取）+ 未命中进并行提取
        #    seen_targets 同时约束 customs/命中/提取三路，键 = target + args
        #    （同一 exe 的不同参数入口视为不同应用，不再被误合并）
        if self._scan_enabled:
            cand_paths = {c[0] for c in candidates if not c[4]}   # 未隐藏候选（dup 自愈依据）
            misses = []
            seen_targets = {}             # (target_lower, args) → 主 lnk 路径

            def dedup_claim(full, target, args, lnk_mt):
                """target+args 去重：重复者记 dup 账（带 primary，主 lnk 消失自动复活）"""
                tlow = (target or '').lower()
                if not tlow:
                    return True
                key = tlow + chr(31) + (args or '')
                if key in seen_targets:
                    meta_new[full] = {'mt': lnk_mt, 'dup': 1, 'target': target,
                                      'args': args or '', 'primary': seen_targets[key]}
                    return False
                seen_targets[key] = full
                return True

            for full, name, cat, lnk_mt, hidden in candidates:
                if hidden:
                    continue              # 隐藏项不提取不发射；缓存已由 seen_paths 保留
                entry = cache.get(full)
                app = None
                is_dup = bool(entry and entry.get('mt') == lnk_mt and entry.get('dup'))
                if is_dup and entry.get('primary') in cand_paths:
                    continue              # 主 lnk 仍在候选中 → 有效记账，缓存已保留
                if entry and entry.get('mt') == lnk_mt and not is_dup:
                    # 非 .exe 目标：不发射；旧缓存条目由 seen_paths 保留（UWP 例外）
                    if not full.startswith('uwp:') and \
                            not (entry.get('target') or '').lower().endswith('.exe'):
                        continue
                    # v3 = 高清图标缓存；v2 及更早按未命中处理，自动迁移一次
                    need_v = 3
                    if entry.get('v') != need_v:
                        misses.append((full, name, cat, lnk_mt))
                        continue
                    # 目标文件指纹：target 更新 → 图标缓存过期
                    tgtmt = entry.get('tgtmt')
                    if tgtmt and not full.startswith('uwp:'):
                        try:
                            if int(os.path.getmtime(entry['target'])) != tgtmt:
                                misses.append((full, name, cat, lnk_mt))
                                continue
                        except OSError:
                            misses.append((full, name, cat, lnk_mt))
                            continue
                    # 缩略图优先：80px 解码远小于 256px 全图；无缩略图退回大图
                    img = None
                    thumb_file = entry.get('thumb')
                    if thumb_file:
                        img = QImage(os.path.join(ICON_DIR, thumb_file))
                        if img.isNull():
                            img = None
                    if img is None and entry.get('icon'):
                        img = QImage(os.path.join(ICON_DIR, entry['icon']))
                        if img.isNull():
                            img = None
                    # noicon 失败重试窗口：超 24h 重新尝试提取
                    fresh_noicon = bool(entry.get('noicon')) and \
                        (time.time() - entry.get('failat', 0) < 86400)
                    if img is not None or fresh_noicon:
                        n_cached += 1
                        meta_new[full] = entry
                        tlow_h = (entry.get('target') or '').lower()
                        if dedup_claim(full, tlow_h, entry.get('args', ''), lnk_mt):
                            app = {'name': entry['name'], 'lnk': full, 'cat': entry['cat'],
                                   'target': entry['target'], 'mtime': entry.get('mtime', ''),
                                   'img': img, 'tint': QColor(entry.get('tint') or ACCENT),
                                   'args': entry.get('args', ''),
                                   'icon_file': entry.get('icon')}
                        else:
                            continue      # 命中即记账（dup），不发射
                    else:
                        misses.append((full, name, cat, lnk_mt))
                        continue
                else:
                    misses.append((full, name, cat, lnk_mt))
                if app is not None:
                    emitted.append(app)
                    if len(emitted) % BATCH == 0:
                        self.batch.emit(emitted[-BATCH:])

            # 4) 并行提取（取消时及时收尾）；结果按候选序流式发射
            results = {}
            if misses and not self._stop:
                results = self._extract_parallel(misses)

            for full, name, cat, lnk_mt in misses:
                if self._stop:
                    break
                res = results.get(full)
                if res is None:           # 提取失败或目标被 JUNK/.exe 过滤
                    continue
                app, entry = res
                tlow = (app.get('target') or '').lower()
                if dedup_claim(full, tlow, app.get('args') or '', lnk_mt):
                    meta_new[full] = entry
                    emitted.append(app)
                    if len(emitted) % BATCH == 0:
                        self.batch.emit(emitted[-BATCH:])

        if not self._stop:
            if emitted and len(emitted) % BATCH != 0:
                self.batch.emit(emitted[len(emitted) - len(emitted) % BATCH:])
            meta_new = merge_meta(cache, meta_new, seen_paths)
            if meta_new != cache:              # 按需写盘：缓存未变时跳过 I/O
                save_meta(meta_new)
            try:                       # 清理孤儿图标（不再收录的路径残留的 PNG，含缩略图）
                referenced = set()
                for e in meta_new.values():
                    if e.get('icon'):
                        referenced.add(e['icon'])
                    if e.get('thumb'):
                        referenced.add(e['thumb'])
                for f in os.listdir(ICON_DIR):
                    if (f.endswith('_c.png') or f.endswith('_t.png')) and f not in referenced:
                        os.remove(os.path.join(ICON_DIR, f))
            except Exception:
                pass
            logging.info('[scan] 完成：%d 个快捷方式（缓存命中 %d），耗时 %.2fs',
                           len(emitted), n_cached, time.time() - t0)
        self.done.emit(len(emitted), time.time() - t0)

class AddWorker(QThread):
    """手动添加单个应用（图标提取放线程，避免卡 UI）"""
    ready = Signal(dict)
    failed = Signal(str)

    def __init__(self, path):
        super().__init__()
        self._path = path

    def run(self):
        if HAVE_COM:
            try:
                pythoncom.CoInitialize()
            except Exception:
                pass
        try:
            path = self._path
            if not os.path.exists(path):
                self.failed.emit('文件不存在')
                return
            name = os.path.splitext(os.path.basename(path))[0]
            app, entry = build_app(path, name, '自定义')
            # 图标提取失败也允许添加：卡片走首字母占位，24h 后扫描自动重试图标
            meta = load_meta()
            meta[path] = entry
            ok_meta = save_meta(meta)
            store = load_custom_store()
            if path not in store['customs']:
                store['customs'].append(path)
            if path in store['hidden']:    # 重新添加 = 自动取消隐藏，否则卡片会被静默过滤
                store['hidden'].remove(path)
            ok_store = save_custom_store(store)
            if not (ok_meta and ok_store):
                self.failed.emit('配置保存失败，添加未完成（磁盘或权限问题）')
                return
            self.ready.emit(app)
        except Exception as ex:
            self.failed.emit(str(ex))
        finally:
            if HAVE_COM:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass


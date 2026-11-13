# -*- coding: utf-8 -*-
"""视觉 / 动效 / 布局 token —— 唯一事实来源（保持 Qt-free，方便复用）"""

# 动效（ms）：快=悬停反馈，中=布局重排/淡出，慢=颜色补间/归位
DUR_FAST, DUR_BASE, DUR_SLOW = 180, 240, 400

# 布局
CW, CH, GAP, PAD = 176, 110, 18, 10
GUTTER = 48                       # 全局左右留白：顶栏 / Hero / 货架 / 底栏共用同一网格
BAR_H = 108                       # 底部占位（菜单岛 50 + 提示岛 44 + 边距 14）
CLICK_DEDUPE = 0.30               # 同卡点击去重（s）
HOVER_CONFIRM = 80                # 悬停切换 Hero 的确认延迟（ms，防横扫闪烁）

# 圆角
R_SM, R_MD, R_XL = 8, 12, 28

# 字体
FONT_UI = 'Microsoft YaHei UI'
FONT_MONO = 'Consolas'

# 字级阶梯（px）：海报字母/托盘字母/Hero标题/时钟/副标题/正文/提示/元信息/角标/图标字母
FS_POSTER, FS_TRAY, FS_HERO, FS_CLOCK = 110, 30, 44, 20
FS_SUB, FS_BODY, FS_HINT, FS_META, FS_BADGE, FS_CHIP = 14, 13, 12, 11, 10, 26

# 色板（同一角色一个 token：一套灰、一套蓝；收编此前散落的 40+ 字面量）
ACCENT = '#1a9fff'                # 品牌蓝（UI 强调色，兼作图标 tint fallback，收编 #4f9cff）
ACCENT2 = '#6f5cff'               # 托盘图标渐变尾色
BG_BASE = '#0b0e14'               # 全局底色
BG_TOP = '#101626'                # 背景渐变亮端
CARD_TOP = '#1c2230'              # 卡面渐变顶
CARD_BOT = '#141924'              # 卡面渐变底
POSTER_BG = '#10141f'             # Hero 海报底
HERO_TOP = '#0d111b'              # Hero 渐变 (13,17,27)
HERO_BOT = '#0a0d14'              # Hero/菜单岛底 (10,13,20)
INK = '#090c12'                   # 深色罩层基色 (9,12,18)
TEXT = '#eef2f8'                  # 主文字
TEXT_SOFT = '#dfe6ee'             # 键位徽章 / 次强调文字（收编 #c8d2e0）
DIM = '#98a4b5'                   # 次级文字（唯一灰，收编 #8d99ab）
NAV_TEXT = '#aeb9c9'              # 菜单岛 chip 未选中文字
EMPTY_TEXT = '#9aa7b8'            # 空态提示文字
HIGH_BLUE = '#7db6e8'             # 高亮蓝字（toast 强调 / 副标题）
CHIP_BG = '#0d1118'               # 图标芯片底
SKEL_BG = '#161c29'               # 骨架卡底
RED = '#ef4444'                   # 管理模式 ×
RED_SOFT = '#ffd7d7'              # 管理按钮选中文字
KB_BG = '#232a33'                 # 键位徽章底
KB_BORDER = '#454d58'             # 键位徽章描边
WHITE = '#ffffff'
BLACK = '#000000'
FOCUS_RING = '#ffffff'

# RGB 元组（供 QSS rgba() 拼接）
ACCENT_RGB = (26, 159, 255)
WHITE_RGB = (255, 255, 255)
HERO_RGB = (13, 17, 27)
HERO_RGB_B = (10, 13, 20)
TOAST_RGB = (10, 13, 19)
RED_RGB = (239, 68, 68)


def rgba(rgb, a):
    """拼 QSS 的 rgba() 片段：rgba(ACCENT_RGB, 48) -> 'rgba(26,159,255,48)'"""
    return 'rgba(%d,%d,%d,%d)' % (rgb[0], rgb[1], rgb[2], a)

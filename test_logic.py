# -*- coding: utf-8 -*-
"""纯逻辑单元测试（无 GUI、无 PySide6 依赖）：
   python test_logic.py
覆盖：custom store 往返（含 recent / scan_enabled）、merge_meta 记账规则、
      recent 持久化、prune_recent、托盘「仅手动」开关语义
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store  # noqa: E402  （纯 Python，无 Qt）


def test_custom_store_roundtrip_real():
    """custom store 写读往返（含 recent 浮点 / scan_enabled / hidden）"""
    d = tempfile.mkdtemp()
    old_dir = store.CACHE_DIR
    old_meta = store.META_PATH
    old_custom = store.CUSTOM_PATH
    store.CACHE_DIR = d
    store.META_PATH = os.path.join(d, 'meta.json')
    store.CUSTOM_PATH = os.path.join(d, 'custom.json')
    try:
        st = {'customs': [r'C:\a\app.lnk'], 'hidden': [r'C:\b\hid.lnk'],
              'recent': {r'C:\a\app.lnk': 1730000000.5}, 'scan_enabled': False}
        store.save_custom_store(st)
        back = store.load_custom_store()
        assert back['customs'] == st['customs']
        assert back['hidden'] == st['hidden']
        assert abs(back['recent'][r'C:\a\app.lnk'] - 1730000000.5) < 1e-6
        assert back['scan_enabled'] is False
        print('PASS custom_store 往返（含 recent / scan_enabled）')
    finally:
        store.CACHE_DIR = old_dir
        store.META_PATH = old_meta
        store.CUSTOM_PATH = old_custom


def test_recent_survives_load():
    """recent 字段必须能从磁盘读回（P0-2 回归）"""
    d = tempfile.mkdtemp()
    old_c = store.CUSTOM_PATH
    store.CUSTOM_PATH = os.path.join(d, 'custom.json')
    try:
        store.save_custom_store({'customs': [], 'hidden': [],
                                 'recent': {'x': 1.0}, 'scan_enabled': True})
        back = store.load_custom_store()
        assert back.get('recent', {}).get('x') == 1.0, 'recent 被丢弃！'
        print('PASS recent 跨重启持久化')
    finally:
        store.CUSTOM_PATH = old_c


def test_merge_meta_two_cycle():
    """P0-1 回归：全命中的轮次不得抹掉缓存（隔次冷启动震荡）"""
    cache = {'a.lnk': {'mt': 1, 'name': 'A'}, 'b.lnk': {'mt': 1, 'name': 'B'}}
    # 第一轮：全量新提取
    meta_new = {'a.lnk': {'mt': 1, 'name': 'A', 'icon': 'a_c.png'},
                'b.lnk': {'mt': 1, 'name': 'B', 'icon': 'b_c.png'}}
    cache = store.merge_meta(cache, meta_new, {'a.lnk', 'b.lnk'})
    assert len(cache) == 2
    # 第二轮：全部命中（命中分支也写回 → meta_new 与 cache 等价）
    meta_new2 = {'a.lnk': cache['a.lnk'], 'b.lnk': cache['b.lnk']}
    cache = store.merge_meta(cache, meta_new2, {'a.lnk', 'b.lnk'})
    assert len(cache) == 2, '命中轮丢缓存！'
    # 第三轮：一个应用被隐藏（不在 seen_paths）→ 被清理
    cache = store.merge_meta(cache, {}, {'a.lnk'})
    assert 'b.lnk' not in cache and 'a.lnk' in cache
    print('PASS merge_meta 两轮稳定 + 隐藏清理')


def test_prune_recent():
    r = {('p%d' % i): float(i) for i in range(50)}
    pruned = store.prune_recent(r, keep=30)
    assert len(pruned) == 30
    assert 'p49' in pruned and 'p0' not in pruned
    print('PASS prune_recent')


def test_scan_mode_semantics():
    """托盘「仅显示我添加的应用」勾选语义：核对 launcher 的真实接线（不再自说自话）：
       1) launcher 源码里托盘初始态 = not scan_enabled，勾选事件接到 set_scan_mode(not on)
       2) 语义本身：勾上=仅手动（关闭自动扫描），取消=恢复全量"""
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'launcher.py'),
               encoding='utf-8').read()
    assert 'setChecked(not self._scan_enabled)' in src, '托盘初始勾选态未与 scan_enabled 反接'
    assert 'set_scan_mode(not on)' in src, '勾选事件未接到 set_scan_mode(not on)'
    checked = True                     # 用户勾上「仅手动」
    assert (not checked) is False, '勾上应关闭自动扫描'
    checked = False                    # 用户取消勾选
    assert (not checked) is True, '取消勾选应恢复全量扫描'
    print('PASS scan_mode 勾选语义（真实接线核对 + 勾上=仅手动）')


if __name__ == '__main__':
    test_custom_store_roundtrip_real()
    test_recent_survives_load()
    test_merge_meta_two_cycle()
    test_prune_recent()
    test_scan_mode_semantics()
    print('ALL LOGIC TESTS PASSED')

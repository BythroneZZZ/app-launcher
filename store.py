# -*- coding: utf-8 -*-
"""数据持久层（纯 Python，无 Qt 依赖 —— 可独立单元测试）
   meta.json   : 扫描缓存（路径 → {mt, name, cat, target, mtime, icon, noicon, tint}）
   custom.json : 用户数据（customs / hidden / recent / scan_enabled）
   merge_meta  : 扫描记账规则（命中轮也必须保留缓存条目）
"""
import json
import os

CACHE_DIR = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'AppLauncher')
ICON_DIR = os.path.join(CACHE_DIR, 'icons')
META_PATH = os.path.join(CACHE_DIR, 'meta.json')
CUSTOM_PATH = os.path.join(CACHE_DIR, 'custom.json')


def _write_atomic(path, data, backup=False):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        if backup and os.path.exists(path):
            bak = path + '.bak'
            try:
                os.replace(path, bak)       # 原文件 → .bak（含上次成功数据）
            except OSError:
                pass
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def load_meta():
    try:
        with open(META_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_meta(meta):
    return _write_atomic(META_PATH, meta)


def merge_meta(cache, meta_new, seen_paths):
    """合并本轮元数据与旧缓存；仅保留仍存在的路径。
       规则：命中分支也必须写回 meta_new，否则命中轮会抹掉缓存（隔次冷启动震荡）。"""
    out = dict(meta_new)
    for k, v in cache.items():
        if k in seen_paths:
            out.setdefault(k, v)
    return out


def _parse_custom_data(d):
    """解析 custom.json 字典 → 规范化结构（类型过滤 + 默认值）"""
    if not isinstance(d, dict):
        return None
    rec = d.get('recent', {})
    recent = {k: float(v) for k, v in rec.items()
              if isinstance(k, str) and isinstance(v, (int, float))} \
        if isinstance(rec, dict) else {}
    freq = d.get('frequent', {})
    frequent = {k: int(v) for k, v in freq.items()
                if isinstance(k, str) and isinstance(v, (int, float)) and v > 0} \
        if isinstance(freq, dict) else {}
    return {'customs': [p for p in d.get('customs', []) if isinstance(p, str)],
            'hidden': [p for p in d.get('hidden', []) if isinstance(p, str)],
            'recent': recent,
            'frequent': frequent,
            'sort_mode': d.get('sort_mode', 'recent') if d.get('sort_mode') in ('recent', 'frequent') else 'recent',
            'scan_enabled': bool(d.get('scan_enabled', True))}


def load_custom_store():
    """读 custom.json；主文件损坏时回退 .bak（上次成功写入的旧数据）"""
    for path in (CUSTOM_PATH, CUSTOM_PATH + '.bak'):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                d = json.load(f)
            parsed = _parse_custom_data(d)
            if parsed is not None:
                return parsed
        except Exception:
            continue
    return {'customs': [], 'hidden': [], 'recent': {}, 'frequent': {},
            'sort_mode': 'recent', 'scan_enabled': True}


def save_custom_store(store):
    return _write_atomic(CUSTOM_PATH, store, backup=True)   # 用户数据：写入前备份旧文件


def prune_recent(recent, keep=30):
    """只保留最近 keep 条启动记录"""
    items = sorted(recent.items(), key=lambda kv: kv[1], reverse=True)[:keep]
    return dict(items)

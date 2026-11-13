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


def _write_atomic(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        pass


def load_meta():
    try:
        with open(META_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_meta(meta):
    _write_atomic(META_PATH, meta)


def merge_meta(cache, meta_new, seen_paths):
    """合并本轮元数据与旧缓存；仅保留仍存在的路径。
       规则：命中分支也必须写回 meta_new，否则命中轮会抹掉缓存（隔次冷启动震荡）。"""
    out = dict(meta_new)
    for k, v in cache.items():
        if k in seen_paths:
            out.setdefault(k, v)
    return out


def load_custom_store():
    try:
        with open(CUSTOM_PATH, 'r', encoding='utf-8') as f:
            d = json.load(f)
        if isinstance(d, dict):
            rec = d.get('recent', {})
            recent = {k: float(v) for k, v in rec.items()
                      if isinstance(k, str) and isinstance(v, (int, float))} \
                if isinstance(rec, dict) else {}
            return {'customs': [p for p in d.get('customs', []) if isinstance(p, str)],
                    'hidden': [p for p in d.get('hidden', []) if isinstance(p, str)],
                    'recent': recent,
                    'scan_enabled': bool(d.get('scan_enabled', True))}
    except Exception:
        pass
    return {'customs': [], 'hidden': [], 'recent': {}, 'scan_enabled': True}


def save_custom_store(store):
    _write_atomic(CUSTOM_PATH, store)


def prune_recent(recent, keep=30):
    """只保留最近 keep 条启动记录"""
    items = sorted(recent.items(), key=lambda kv: kv[1], reverse=True)[:keep]
    return dict(items)

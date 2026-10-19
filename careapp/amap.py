"""高德地图开放平台封装：地理编码 + 骑行路径规划。

Key 来源（二选一，均不入 git）：
  1. 环境变量 AMAP_KEY
  2. 项目根目录 secrets.json 的 "amap_key" 字段（模板见 secrets.example.json）
未配置时相关功能自动退回直线估算/手动地图选点，不影响其余功能。
坐标系为 GCJ-02，与高德底图一致。
"""
import json
import os
from datetime import datetime

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_cache = {}


def get_key():
    key = os.environ.get('AMAP_KEY', '').strip()
    if key:
        return key
    try:
        with open(os.path.join(BASE_DIR, 'secrets.json'), encoding='utf-8') as f:
            return (json.load(f).get('amap_key') or '').strip()
    except Exception:
        return ''


def _cached(key, fn, ttl=86400):
    now = datetime.now().timestamp()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    if val:
        _cache[key] = (now, val)
    return val


def geocode(address, city=''):
    """地址 -> (lat, lng)；失败或未配 Key 返回 None。"""
    key = get_key()
    if not key:
        return None

    def run():
        try:
            r = requests.get('https://restapi.amap.com/v3/geocode/geo',
                             params={'key': key, 'address': address, 'city': city},
                             timeout=5)
            d = r.json()
            if d.get('status') == '1' and d.get('geocodes'):
                lng, lat = d['geocodes'][0]['location'].split(',')
                return (float(lat), float(lng))
        except Exception:
            return None

    return _cached(('geo', address, city), run)


def bicycling(origin, dest):
    """骑行路径规划：(lat,lng) x2 -> (米, 秒)；失败或未配 Key 返回 None。"""
    key = get_key()
    if not key:
        return None

    def run():
        try:
            r = requests.get('https://restapi.amap.com/v4/direction/bicycling',
                             params={'key': key,
                                     'origin': f'{origin[1]:.6f},{origin[0]:.6f}',
                                     'destination': f'{dest[1]:.6f},{dest[0]:.6f}'},
                             timeout=5)
            j = r.json()
            if j.get('errcode') == 0 and j.get('data', {}).get('paths'):
                p = j['data']['paths'][0]
                return (int(p['distance']), int(p['duration']))
        except Exception:
            return None

    return _cached(('bike', origin, dest), run)

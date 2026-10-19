"""行程规划：TSP 排序、电瓶车耗时/电量估算、Open-Meteo 天气、高德骑行路网。"""
import math
from datetime import datetime, timedelta

import requests
from flask import current_app

from . import amap

WMO_TEXT = {0: '晴', 1: '基本晴', 2: '多云', 3: '阴', 45: '雾', 48: '雾凇',
            51: '小毛雨', 53: '毛雨', 55: '大毛雨', 56: '冻毛雨', 57: '冻毛雨',
            61: '小雨', 63: '中雨', 65: '大雨', 66: '冻雨', 67: '冻雨',
            71: '小雪', 73: '中雪', 75: '大雪', 77: '雪粒',
            80: '小阵雨', 81: '阵雨', 82: '强阵雨', 85: '小阵雪', 86: '大阵雪',
            95: '雷阵雨', 96: '雷阵雨伴冰雹', 99: '雷阵雨伴冰雹'}

_weather_cache = {}


def wmo_text(code):
    return WMO_TEXT.get(code, '未知天气')


def haversine_km(p1, p2):
    r = 6371.0
    lat1, lng1, lat2, lng2 = map(math.radians, (p1[0], p1[1], p2[0], p2[1]))
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def fetch_weather(date_str, lat, lng):
    """Open-Meteo 免密钥逐日预报；失败或历史日期返回 None。离线时路线仍可规划。"""
    key = (date_str, round(lat, 2), round(lng, 2))
    hit = _weather_cache.get(key)
    if hit and (datetime.now() - hit[0]).total_seconds() < 3600:
        return hit[1]
    try:
        res = requests.get('https://api.open-meteo.com/v1/forecast', params={
            'latitude': lat, 'longitude': lng, 'timezone': 'auto', 'forecast_days': 7,
            'daily': 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,snowfall_sum',
        }, timeout=6)
        res.raise_for_status()
        daily = res.json().get('daily') or {}
        dates = daily.get('time') or []
        if date_str not in dates:
            data = None
        else:
            i = dates.index(date_str)
            code = daily['weather_code'][i]
            data = dict(code=code, text=wmo_text(code),
                        tmax=daily['temperature_2m_max'][i], tmin=daily['temperature_2m_min'][i],
                        precip_mm=daily['precipitation_sum'][i] or 0,
                        snow_cm=daily['snowfall_sum'][i] or 0)
    except Exception:
        data = None
    _weather_cache[key] = (datetime.now(), data)
    return data


def _tsp_order(start, pts):
    """最近邻 + 2-opt 顺序优化；返回下标访问顺序。"""
    n = len(pts)
    if n <= 1:
        return list(range(n))
    seq, left = [], set(range(n))
    cur = start
    while left:
        nxt = min(left, key=lambda i: haversine_km(cur, pts[i]))
        seq.append(nxt)
        left.remove(nxt)
        cur = pts[nxt]

    def length(s):
        d, p = 0.0, start
        for i in s:
            d += haversine_km(p, pts[i])
            p = pts[i]
        return d

    if n <= 12:
        improved = True
        while improved:
            improved = False
            for i in range(n - 1):
                for j in range(i + 1, n):
                    cand = seq[:i] + seq[i:j + 1][::-1] + seq[j + 1:]
                    if length(cand) < length(seq) - 1e-9:
                        seq, improved = cand, True
    return seq


def _apply_lunch(svc_start, minutes, lunch_s, lunch_e):
    """服务若跨越午餐时段则拆分：餐前做一部分，13:30 后补完。"""
    if svc_start < lunch_e and svc_start + timedelta(minutes=minutes) > lunch_s:
        before = max(0, int((lunch_s - svc_start).total_seconds() // 60))
        return lunch_e + timedelta(minutes=minutes - before), True
    return svc_start + timedelta(minutes=minutes), False


def plan_route(worker, orders, conf, date_str):
    """一天的电瓶车行程计划：排序 → 逐段估时 → 午餐 → 电量。"""
    warnings, stops_out, legs = [], [], []
    pts, valid = [], []
    for o in orders:
        if o.get('lat') is None or o.get('lng') is None:
            warnings.append(f'顾客 {o["customer_name"]} 未设置定位坐标，地图路线中已跳过')
            continue
        pts.append((o['lat'], o['lng']))
        valid.append(o)

    if worker.get('lat') is not None and worker.get('lng') is not None:
        start = (worker['lat'], worker['lng'])
        start_name = '我的驻地'
    elif pts:
        start = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        start_name = '顾客区中心（未设置我的定位）'
        warnings.append('您未设置居住定位，请在个人信息中补充，行程将从顾客区中心开始')
    else:
        return dict(date=date_str, stops=[], legs=[], warnings=['当天没有可规划的订单'],
                    weather=None, battery=None, total_km=0, work_minutes=0)

    weather = fetch_weather(date_str, start[0], start[1])
    speeds = conf['speed_kmh']
    speed = speeds['dry']
    weather_note = '天气数据暂不可用，按晴天速度估算'
    if weather:
        if weather['snow_cm'] > 0 or weather['code'] in (71, 73, 75, 77, 85, 86):
            speed = speeds['snow']
            weather_note = f'当天有雪（约{weather["snow_cm"]:.0f}cm），降速至 {speed}km/h，注意防滑'
        elif weather['precip_mm'] >= 0.5 or weather['code'] >= 51:
            speed = speeds['rain']
            weather_note = f'当天有雨（约{weather["precip_mm"]:.1f}mm），降速至 {speed}km/h，请带雨具'
        else:
            weather_note = f'天气{weather["text"]}，按 {speed}km/h 估算'

    d = datetime.strptime(date_str, '%Y-%m-%d')
    h, m = map(int, conf['day_start'].split(':'))
    clock = d.replace(hour=h, minute=m)
    ls_h, ls_m = map(int, conf['lunch']['start'].split(':'))
    le_h, le_m = map(int, conf['lunch']['end'].split(':'))
    lunch_s = d.replace(hour=ls_h, minute=ls_m)
    lunch_e = d.replace(hour=le_h, minute=le_m)

    factor, total_km = conf['road_factor'], 0.0
    weather_factor = speeds['dry'] / speed if speed < speeds['dry'] else 1.0  # 恶劣天气放大耗时
    seq = _tsp_order(start, pts)
    prev, lunch_used = start, False
    amap_legs = 0
    markers = [dict(lat=start[0], lng=start[1], seq='🏠', home=True, customer=start_name)]
    for k, idx in enumerate(seq):
        o = valid[idx]
        km = haversine_km(prev, pts[idx]) * factor
        leg_min = max(5, math.ceil(km / speed * 60))
        ride = amap.bicycling(prev, pts[idx])  # 高德骑行路网（配了 Key 才有，GCJ-02 一致）
        if ride:
            km = ride[0] / 1000
            leg_min = max(3, round(ride[1] / 60 * weather_factor))
            amap_legs += 1
        total_km += km
        arrive = clock + timedelta(minutes=leg_min)
        sched = datetime.strptime(o['sched_start'], '%Y-%m-%d %H:%M')
        svc_start = max(arrive, sched)
        if (svc_start - arrive).total_seconds() > 45 * 60:
            warnings.append(f'{o["customer_name"]} 计划到达比预约晚 '
                            f'{int((svc_start - arrive).total_seconds() // 60)} 分钟，建议联系顾客调整')
        depart, hit = _apply_lunch(svc_start, o['minutes'], lunch_s, lunch_e)
        if hit:
            lunch_used = True
        legs.append(dict(seq=k + 1, km=round(km, 2), minutes=leg_min))
        markers.append(dict(lat=pts[idx][0], lng=pts[idx][1], seq=k + 1,
                            customer=o['customer_name'], item=o['item_name'],
                            address=o.get('customer_address') or o.get('address') or ''))
        stops_out.append(dict(seq=k + 1, order_id=o['id'], customer=o['customer_name'],
                              address=o.get('customer_address') or o.get('address') or '',
                              phone=o.get('customer_phone') or o.get('phone') or '',
                              item=o['item_name'], status=o['status'],
                              sched=o['sched_start'], arrive=arrive.strftime('%H:%M'),
                              service_start=svc_start.strftime('%H:%M'),
                              depart=depart.strftime('%H:%M')))
        clock, prev = depart, pts[idx]

    work_minutes = int((clock - datetime.strptime(conf['day_start'], '%H:%M').replace(
        year=d.year, month=d.month, day=d.day)).total_seconds() // 60) if stops_out else 0

    bat_conf = conf['battery']
    tavg = (weather['tmax'] + weather['tmin']) / 2 if weather else 20.0
    wh_per_km = bat_conf['wh_per_km_base'] + max(0.0, bat_conf['temp_ref_c'] - tavg) * bat_conf['wh_per_km_per_degree']
    use_wh = total_km * wh_per_km
    use_pct = use_wh / bat_conf['capacity_wh'] * 100
    bat_note = (f'当日均温约 {tavg:.0f}℃，按 {wh_per_km:.1f} Wh/km 估算，'
                f'{total_km:.1f} km 约耗电 {use_pct:.0f}%')
    if use_pct > 85:
        bat_note += '，耗电偏高，建议携带充电器或中午补电'
    elif tavg < 5:
        bat_note += '，低温会进一步缩短续航，请留意电量'
    battery = dict(capacity_wh=bat_conf['capacity_wh'], wh_per_km=round(wh_per_km, 1),
                   use_wh=round(use_wh), use_pct=round(use_pct, 1), temp_avg=round(tavg, 1), note=bat_note)

    return dict(date=date_str, start_name=start_name, start=start, stops=stops_out, legs=legs,
                markers=markers,
                distance_source=('高德骑行实测' if amap_legs == len(seq) and amap_legs
                                 else f'高德骑行/直线混合({amap_legs}/{len(seq)})' if amap_legs
                                 else '直线×1.35估算'),
                total_km=round(total_km, 2), work_minutes=work_minutes,
                lunch=dict(start=conf['lunch']['start'], end=conf['lunch']['end'], used=lunch_used),
                weather=weather, weather_note=weather_note, battery=battery, warnings=warnings)

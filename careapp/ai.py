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
    """保留用于未来「空闲时段顺路优化」；当前排程以预约时间为准（见 plan_route）。"""
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
    buffer_min = int(conf.get('schedule_buffer_min', 10))  # 骑行之外需预留的准备时间
    weather_factor = speeds['dry'] / speed if speed < speeds['dry'] else 1.0  # 恶劣天气放大耗时
    # 按预约时间排序（预约是承诺，不按地理位置重排）；地理只用于估算相邻两单路程
    ordered = sorted(valid, key=lambda o: o['sched_start'])
    prev, lunch_used = start, False
    amap_legs = 0
    prev_label = start_name
    day_start_dt = clock
    prev_sched_end = None
    first_depart_dt = None
    schedule_orders = []
    markers = [dict(lat=start[0], lng=start[1], seq='🏠', home=True, customer=start_name)]
    for k, o in enumerate(ordered):
        pt = (o['lat'], o['lng'])
        km = haversine_km(prev, pt) * factor
        leg_min = max(5, math.ceil(km / speed * 60))
        ride = amap.bicycling(prev, pt)  # 高德骑行路网（配了 Key 才有，GCJ-02 一致）
        if ride:
            km = ride[0] / 1000
            leg_min = max(3, round(ride[1] / 60 * weather_factor))
            amap_legs += 1
        total_km += km
        sched = datetime.strptime(o['sched_start'], '%Y-%m-%d %H:%M')
        sched_end = sched + timedelta(minutes=o['minutes'])
        # 时间安排合理性：上一单预约结束 → 本单预约开始 的预留间隔 vs 所需（骑行+准备）
        gap_base = prev_sched_end if prev_sched_end else day_start_dt
        available_min = int((sched - gap_base).total_seconds() // 60)
        required_min = leg_min + buffer_min
        if available_min < leg_min:
            check_status = 'late'
        elif available_min < required_min:
            check_status = 'tight'
        else:
            check_status = 'ok'
        arrive = clock + timedelta(minutes=leg_min)
        svc_start = max(arrive, sched)
        late_min = int((svc_start - sched).total_seconds() // 60)
        if late_min > 15:
            warnings.append(f'{o["customer_name"]} 预约 {sched:%H:%M}，预计 {svc_start:%H:%M} 才到'
                            f'（晚 {late_min} 分钟）')
        elif (sched - arrive).total_seconds() > 3600:
            warnings.append(f'{o["customer_name"]} 将提前约 '
                            f'{int((sched - arrive).total_seconds() // 60)} 分钟到达')
        depart, hit = _apply_lunch(svc_start, o['minutes'], lunch_s, lunch_e)
        if hit:
            lunch_used = True
        legs.append(dict(seq=k + 1, km=round(km, 2), minutes=leg_min,
                         from_lat=prev[0], from_lng=prev[1], to_lat=pt[0], to_lng=pt[1],
                         from_label=prev_label, to_label=o['customer_name'],
                         available_min=available_min, required_min=required_min,
                         status=check_status))
        depart_advice = None
        if k == 0:
            first_depart_dt = max(day_start_dt, sched - timedelta(minutes=required_min))
            depart_advice = first_depart_dt.strftime('%H:%M')
        schedule_orders.append(dict(
            seq=k + 1, order_id=o['id'], customer=o['customer_name'], item=o['item_name'],
            start=sched.strftime('%H:%M'), end=sched_end.strftime('%H:%M'),
            from_label=prev_label, distance_km=round(km, 2), travel_min=leg_min,
            gap_min=available_min, required_min=required_min,
            depart_advice=depart_advice, status=check_status))
        prev_sched_end = sched_end
        prev_label = o['customer_name']
        markers.append(dict(lat=pt[0], lng=pt[1], seq=k + 1,
                            customer=o['customer_name'], item=o['item_name'],
                            address=o.get('customer_address') or o.get('address') or ''))
        stops_out.append(dict(seq=k + 1, order_id=o['id'], customer=o['customer_name'],
                              address=o.get('customer_address') or o.get('address') or '',
                              phone=o.get('customer_phone') or o.get('phone') or '',
                              item=o['item_name'], status=o['status'],
                              sched=o['sched_start'], arrive=arrive.strftime('%H:%M'),
                              service_start=svc_start.strftime('%H:%M'),
                              depart=depart.strftime('%H:%M')))
        clock, prev = depart, pt

    work_minutes = int((clock - datetime.strptime(conf['day_start'], '%H:%M').replace(
        year=d.year, month=d.month, day=d.day)).total_seconds() // 60) if stops_out else 0

    # 返程：最后一单结束 → 驻地
    return_leg = None
    total_ride_km, total_ride_min, day_work_min, income_cents = 0.0, 0, 0, 0
    if ordered:
        ride_back = amap.bicycling(prev, start)
        if ride_back:
            ret_km = ride_back[0] / 1000
            ret_min = max(3, round(ride_back[1] / 60 * weather_factor))
        else:
            ret_km = haversine_km(prev, start) * factor
            ret_min = max(5, math.ceil(ret_km / speed * 60))
        arrive_home = prev_sched_end + timedelta(minutes=ret_min)
        return_leg = dict(distance_km=round(ret_km, 2), travel_min=ret_min,
                          from_lat=prev[0], from_lng=prev[1],
                          to_lat=start[0], to_lng=start[1],
                          from_label=prev_label, arrive_home=arrive_home.strftime('%H:%M'))
        total_ride_km = total_km + ret_km
        total_ride_min = sum(l['minutes'] for l in legs) + ret_min
        if first_depart_dt:
            day_work_min = int((arrive_home - first_depart_dt).total_seconds() // 60)
        income_cents = sum(int(o.get('worker_pay_cents') or 0) for o in ordered)

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

    check = dict(
        buffer_min=buffer_min,
        legs=legs,
        orders=schedule_orders,
        return_leg=return_leg,
        totals=dict(distance_km=round(total_ride_km, 2), ride_minutes=total_ride_min,
                    work_minutes=day_work_min, income_cents=income_cents),
        ok=sum(1 for l in legs if l['status'] == 'ok'),
        tight=sum(1 for l in legs if l['status'] == 'tight'),
        late=sum(1 for l in legs if l['status'] == 'late'),
        reasonable=all(l['status'] == 'ok' for l in legs),
    )
    return dict(date=date_str, start_name=start_name, start=start, stops=stops_out, legs=legs,
                check=check, markers=markers,
                distance_source=('高德骑行实测' if amap_legs == len(ordered) and amap_legs
                                 else f'高德骑行/直线混合({amap_legs}/{len(ordered)})' if amap_legs
                                 else '直线×1.35估算'),
                total_km=round(total_km, 2), work_minutes=work_minutes,
                lunch=dict(start=conf['lunch']['start'], end=conf['lunch']['end'], used=lunch_used),
                weather=weather, weather_note=weather_note, battery=battery, warnings=warnings)

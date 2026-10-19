"""后端冒烟测试：临时库上用 Flask test_client 全流程验证。"""
import os
import sys
import tempfile
import uuid
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
os.environ['CARE_DB'] = os.path.join(tempfile.gettempdir(), f'care_test_{uuid.uuid4().hex[:8]}.db')

from careapp import create_app  # noqa: E402

app = create_app()
c = app.test_client()
PASSED = []


def call(method, path, token=None, expect=200, data=None, **kw):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    r = getattr(c, method)(path, headers=headers, json=data, **kw)
    body = r.get_json(silent=True) or {}
    assert r.status_code == expect, f'{method} {path} -> {r.status_code} (期望 {expect}): {body}'
    return body


def login(phone, pwd):
    return call('post', '/api/login', data={'phone': phone, 'password': pwd})['token']


def t(name):
    PASSED.append(name)
    print(f'  PASS {name}')


# --- 登录与基础 ---
t('meta 版本信息')
assert 'version' in call('get', '/api/meta')

t('三种角色登录')
admin = login('13900000001', 'admin123')
w1 = login('13800001001', '123456')
c1 = login('13800002001', '123456')   # 陈桂芳 → 服务员王秀英
c2 = login('13800002002', '123456')   # 周明德 → 服务员王秀英
call('post', '/api/login', data={'phone': '13900000001', 'password': 'wrong'}, expect=401)
t('错误密码被拒绝')

# --- 顾客预约与冲突检测 ---
tomorrow = (date.today() + timedelta(days=1)).isoformat()
d_after = (date.today() + timedelta(days=2)).isoformat()
items = call('get', '/api/c/services', c1)['items']
item = next(i for i in items if i['name'] == '上门助浴')
item2 = next(i for i in items if i['name'] == '居家保洁')

# 陈桂芳(服务员1)明天 09:30 已有上门助浴（演示数据）
r = call('post', '/api/c/orders', c1,
         data={'item_id': item['id'], 'date': tomorrow, 'time': '09:30'}, expect=409)
assert r['conflicts'], '应检测到冲突'
t('预约冲突检测（409 + 冲突详情）')
assert r.get('suggestions'), '应给出建议时段'
t('空闲时段建议')

call('post', '/api/c/orders', c1,
     data={'item_id': item['id'], 'date': tomorrow, 'time': r['suggestions'][0]})
t('按建议时段下单成功')

# 周明德（同属服务员1）挤同一时段 → 冲突；force 后成功但带提醒
call('post', '/api/c/orders', c2,
     data={'item_id': item2['id'], 'date': tomorrow, 'time': '09:00'}, expect=409)
forced = call('post', '/api/c/orders', c2,
              data={'item_id': item2['id'], 'date': tomorrow, 'time': '09:00', 'force': True})
assert forced['order']['conflict_warning'], 'force 下单应保留冲突提醒'
t('强制下单保留冲突提醒')

assert 'balance_cents' in call('get', '/api/c/summary', c1)
txs = call('get', '/api/c/transactions', c1)['transactions']
assert txs and 'balance_after' in txs[0]
t('顾客账户概览/明细（含每笔后余额）')

# --- 服务员：确认/完成/异常/路线 ---
ov = call('get', '/api/w/overview', w1)
assert ov['to_confirm'] >= 1
t('服务员工作台概览')

pending = [o for o in call('get', f'/api/w/orders?scope=tomorrow', w1)['orders']
           if o['status'] == 'pending']
call('post', f'/api/w/orders/{pending[0]["id"]}/confirm', w1)
t('逐单确认')

call('post', '/api/w/confirm_all', w1, data={'date': tomorrow})
assert all(o['status'] != 'pending'
           for o in call('get', f'/api/w/orders?scope=tomorrow', w1)['orders'])
t('一键确认明日订单')

today_orders = call('get', '/api/w/orders?scope=today', w1)['orders']
target = next(o for o in today_orders if o['status'] == 'confirmed')
tok = c1 if target['customer_phone'] == '13800002001' else c2
bal_before = call('get', '/api/c/summary', tok)['balance_cents']
call('post', f'/api/w/orders/{target["id"]}/complete', w1, data={'note': '服务顺利'})
bal_after = call('get', '/api/c/summary', tok)['balance_cents']
assert bal_after == bal_before - target['price_cents'], '完成后应按订单价扣款'
t('完成订单自动扣款')

route = call('get', f'/api/w/route?date={tomorrow}', w1)
assert route['stops'] and route['battery'] and route['total_km'] > 0
assert route['lunch']['start'] == '11:30'
t('AI 行程路线（排序/耗时/电量/午餐）')
if route['weather']:
    t('Open-Meteo 天气已接入')

assert len(call('get', '/api/w/customers', w1)['customers']) == 2
t('服务员顾客名单')

# --- 管理员：人员/项目/订单/统计/充值/酬金/异常 ---
workers = call('get', '/api/a/users?role=worker', admin)['users']
customers = call('get', '/api/a/users?role=customer', admin)['users']
t('管理员人员列表')

new_w = call('post', '/api/a/users', admin,
             data={'role': 'worker', 'phone': '13800009999', 'name': '测试员',
                   'password': '123456', 'address': '测试路1号', 'lat': 31.23, 'lng': 121.48})
new_c = call('post', '/api/a/users', admin,
             data={'role': 'customer', 'phone': '13800008888', 'name': '测试奶奶',
                   'password': '123456', 'address': '测试路2号', 'lat': 31.24, 'lng': 121.49,
                   'worker_id': new_w['id']})
call('put', f'/api/a/users/{new_w["id"]}', admin, data={'name': '测试员2'})
new_w_tok = login('13800009999', '123456')
dmy = login('13800008888', '123456')
assert call('get', '/api/me', dmy)['name'] == '测试奶奶'
t('新增服务员/顾客+指派+改资料+可登录')

proxy = call('post', '/api/a/orders', admin,
             data={'customer_id': new_c['id'], 'item_id': item['id'],
                   'date': d_after, 'time': '10:00'})
proxy_oid = proxy['order']['id']
t('管理员代下单')

# 异常订单闭环：上报 → 改期 → 改派 → 标记完成 → 取消退款
call('post', f'/api/w/orders/{proxy_oid}/exception', new_w_tok,
     data={'type': '顾客不在家', 'note': '敲门无人应答'})
o = next(o for o in call('get', '/api/a/orders?status=exception', admin)['orders']
         if o['id'] == proxy_oid)
assert o['exception_type'] == '顾客不在家'
t('服务员上报异常')

call('post', f'/api/a/orders/{proxy_oid}/reschedule', admin, data={'start': f'{d_after} 14:00'})
call('post', f'/api/a/orders/{proxy_oid}/reassign', admin, data={'worker_id': workers[0]['id']})
# “恢复确认”作用于另一单待确认订单
pend = call('get', '/api/a/orders?status=pending', admin)['orders'][0]
call('post', f'/api/a/orders/{pend["id"]}/resolve', admin, data={'action': 'confirm'})
t('管理员改期/改派/恢复确认')

bal0 = call('get', '/api/c/summary', dmy)['balance_cents']
call('post', f'/api/a/orders/{proxy_oid}/resolve', admin, data={'action': 'complete'})
assert call('get', '/api/c/summary', dmy)['balance_cents'] == bal0 - 8000
call('post', f'/api/a/orders/{proxy_oid}/resolve', admin, data={'action': 'cancel_refund'})
assert call('get', '/api/c/summary', dmy)['balance_cents'] == bal0, '退款后应恢复余额'
t('完成扣款 → 取消退款自动返还余额')

logs = call('get', f'/api/a/orders/{proxy_oid}/logs', admin)['logs']
assert len(logs) >= 5
t('订单操作日志可追溯')

st = call('get', '/api/a/stats?from=2020-01-01&to=2099-01-01', admin)
assert st['summary']['total'] >= 8 and st['by_worker'] and st['by_item'] and st['by_month']
t('多维统计（服务员/项目/月份）')

csv_res = c.get('/api/a/stats/export.csv?from=2020-01-01&to=2099-01-01',
                headers={'Authorization': f'Bearer {admin}'})
assert csv_res.status_code == 200 and csv_res.data[:3] == b'\xef\xbb\xbf'
t('CSV 导出（含 BOM）')

call('post', '/api/a/recharge', admin,
     data={'customer_ids': [customers[0]['id'], customers[1]['id']],
           'amount_cents': 30000, 'note': f'{date.today().strftime("%Y年%m月")}批量充值'})
assert call('get', '/api/a/recharges', admin)['recharges'][0]['delta_cents'] == 30000
t('批量充值')

pv = call('get', f'/api/a/payout/preview?worker={workers[0]["id"]}&from=2020-01-01&to=2099-01-01', admin)
if pv['count']:
    pay = call('post', '/api/a/payout', admin,
               data={'worker_id': workers[0]['id'], 'from': '2020-01-01', 'to': '2099-01-01'})
    assert pay['total_cents'] == pv['total_cents']
    assert call('get', '/api/a/payouts', admin)['payouts']
    t('酬金发放（按完成订单）')
pv2 = call('get', f'/api/a/payout/preview?worker={workers[0]["id"]}&from=2020-01-01&to=2099-01-01', admin)
assert pv2['count'] == 0, '发放后不应再有未发订单'
t('酬金不可重复发放')

cancelme = call('post', '/api/c/orders', c1,
                data={'item_id': item2['id'], 'date': d_after, 'time': '15:00'})
call('post', f'/api/c/orders/{cancelme["order"]["id"]}/cancel', c1)
t('顾客自行取消订单')

call('post', '/api/a/items', admin, data={'name': '代购跑腿', 'minutes': 30,
                                          'price_cents': 3000, 'worker_pay_cents': 1500})
iid = call('get', '/api/a/items', admin)['items'][-1]['id']
call('put', f'/api/a/items/{iid}', admin, data={'name': '代购跑腿2', 'minutes': 30,
                                                'price_cents': 3000, 'worker_pay_cents': 1500})
call('delete', f'/api/a/items/{iid}', admin)
t('服务项目增改停用')

bad = c.delete(f'/api/a/users/{workers[0]["id"]}', headers={'Authorization': f'Bearer {admin}'})
assert bad.status_code == 400
t('有顾客的服务员禁止停用')

print(f'\n全部通过：{len(PASSED)} 项')

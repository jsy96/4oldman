"""管理端接口：人员/项目管理、订单管理（含异常处理）、统计导出、批量充值、酬金发放。"""
import csv
import io
import re
from datetime import datetime, timedelta

from flask import Blueprint, g, jsonify, request, Response
from werkzeug.security import generate_password_hash

from .auth import auth_required
from .db import get_db
from . import services

bp = Blueprint('admin', __name__, url_prefix='/api/a')

STATUS_TEXT = {'pending': '待确认', 'confirmed': '已确认', 'completed': '已完成',
               'exception': '异常', 'cancelled': '已取消'}


# ---------- 人员管理 ----------

@bp.get('/users')
@auth_required('admin')
def users():
    role = request.args.get('role')
    db = get_db()
    if role == 'worker':
        rows = db.execute(
            'SELECT u.id, u.phone, u.name, u.address, u.lat, u.lng, u.active, '
            '(SELECT COUNT(*) FROM users c WHERE c.worker_id=u.id AND c.active=1) AS customer_count '
            "FROM users u WHERE u.role='worker' ORDER BY u.active DESC, u.name").fetchall()
    elif role == 'customer':
        rows = db.execute(
            'SELECT c.id, c.phone, c.name, c.address, c.lat, c.lng, c.active, c.balance_cents, '
            'c.worker_id, w.name AS worker_name '
            'FROM users c LEFT JOIN users w ON w.id=c.worker_id '
            "WHERE c.role='customer' ORDER BY c.active DESC, c.name").fetchall()
    else:
        rows = db.execute('SELECT id, phone, name, role, active FROM users ORDER BY id').fetchall()
    return jsonify(users=[dict(r) for r in rows])


def _user_payload(d):
    phone = (d.get('phone') or '').strip()
    name = (d.get('name') or '').strip()
    if not re.fullmatch(r'\d{5,15}', phone):
        raise ValueError('手机号格式不正确')
    if not name:
        raise ValueError('请填写姓名')
    lat, lng = d.get('lat'), d.get('lng')
    return dict(phone=phone, name=name, password=d.get('password') or '',
                address=(d.get('address') or '').strip(),
                lat=float(lat) if lat not in (None, '') else None,
                lng=float(lng) if lng not in (None, '') else None,
                worker_id=d.get('worker_id') or None)


@bp.post('/users')
@auth_required('admin')
def create_user():
    d = request.get_json(force=True, silent=True) or {}
    if d.get('role') not in ('worker', 'customer', 'admin'):
        return jsonify(error='角色不正确'), 400
    try:
        p = _user_payload(d)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    if len(p['password']) < 6:
        return jsonify(error='初始密码至少 6 位'), 400
    if d['role'] == 'customer' and not p['worker_id']:
        return jsonify(error='请为顾客指派服务员'), 400
    db = get_db()
    if db.execute('SELECT 1 FROM users WHERE phone=?', (p['phone'],)).fetchone():
        return jsonify(error='该手机号已被使用'), 400
    if p['worker_id'] and not db.execute(
            "SELECT 1 FROM users WHERE id=? AND role='worker'", (p['worker_id'],)).fetchone():
        return jsonify(error='所指派的服务员不存在'), 400
    db.execute('INSERT INTO users(phone,password_hash,role,name,address,lat,lng,worker_id,created_at) '
               'VALUES(?,?,?,?,?,?,?,?,?)',
               (p['phone'], generate_password_hash(p['password']), d['role'], p['name'],
                p['address'], p['lat'], p['lng'], p['worker_id'], services.now_str()))
    db.commit()
    return jsonify(ok=True, id=db.execute('SELECT last_insert_rowid()').fetchone()[0])


@bp.put('/users/<int:uid>')
@auth_required('admin')
def update_user(uid):
    d = request.get_json(force=True, silent=True) or {}
    db = get_db()
    row = db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    if row is None:
        return jsonify(error='用户不存在'), 404
    try:
        p = _user_payload({**dict(row), **{k: v for k, v in d.items() if k in
                                           ('phone', 'name', 'password', 'address', 'lat', 'lng', 'worker_id')}})
    except ValueError as e:
        return jsonify(error=str(e)), 400
    if db.execute('SELECT 1 FROM users WHERE phone=? AND id!=?', (p['phone'], uid)).fetchone():
        return jsonify(error='该手机号已被使用'), 400
    sets, params = ['phone=?', 'name=?', 'address=?', 'lat=?', 'lng=?', 'worker_id=?'], \
        [p['phone'], p['name'], p['address'], p['lat'], p['lng'],
         p['worker_id'] if row['role'] == 'customer' else row['worker_id']]
    if p['password']:
        if len(p['password']) < 6:
            return jsonify(error='密码至少 6 位'), 400
        sets.append('password_hash=?')
        params.append(generate_password_hash(p['password']))
    if 'active' in d and row['id'] != g.user['id']:  # 不能停用自己
        sets.append('active=?')
        params.append(1 if d['active'] else 0)
    params.append(uid)
    db.execute(f'UPDATE users SET {", ".join(sets)} WHERE id=?', params)
    db.commit()
    return jsonify(ok=True)


@bp.delete('/users/<int:uid>')
@auth_required('admin')
def deactivate_user(uid):
    """软删除（停用）：保留历史订单与流水，可随时启用恢复。"""
    db = get_db()
    row = db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    if row is None:
        return jsonify(error='用户不存在'), 404
    if row['id'] == g.user['id']:
        return jsonify(error='不能停用自己的账号'), 400
    if row['role'] == 'worker':
        n = db.execute('SELECT COUNT(*) c FROM users WHERE worker_id=? AND active=1', (uid,)).fetchone()['c']
        if n:
            return jsonify(error=f'该服务员名下还有 {n} 名顾客，请先改派顾客'), 400
    db.execute('UPDATE users SET active=0 WHERE id=?', (uid,))
    db.commit()
    return jsonify(ok=True)


# ---------- 服务项目 ----------

@bp.get('/items')
@auth_required('admin')
def items():
    rows = get_db().execute('SELECT * FROM service_items ORDER BY active DESC, id').fetchall()
    return jsonify(items=[dict(r) for r in rows])


@bp.post('/items')
@auth_required('admin')
def create_item():
    d = request.get_json(force=True, silent=True) or {}
    name = (d.get('name') or '').strip()
    if not name:
        return jsonify(error='请填写项目名称'), 400
    if not (isinstance(d.get('minutes'), int) and d['minutes'] > 0):
        return jsonify(error='服务时长必须为正整数（分钟）'), 400
    if not (isinstance(d.get('price_cents'), int) and d['price_cents'] > 0):
        return jsonify(error='价格必须为正整数（分）'), 400
    pay = d.get('worker_pay_cents') or 0
    if not isinstance(pay, int) or pay < 0:
        return jsonify(error='酬金必须为非负整数（分）'), 400
    db = get_db()
    db.execute('INSERT INTO service_items(name,minutes,price_cents,worker_pay_cents) VALUES(?,?,?,?)',
               (name, d['minutes'], d['price_cents'], pay))
    db.commit()
    return jsonify(ok=True)


@bp.put('/items/<int:iid>')
@auth_required('admin')
def update_item(iid):
    d = request.get_json(force=True, silent=True) or {}
    db = get_db()
    if db.execute('SELECT 1 FROM service_items WHERE id=?', (iid,)).fetchone() is None:
        return jsonify(error='项目不存在'), 404
    name = (d.get('name') or '').strip()
    if not name:
        return jsonify(error='请填写项目名称'), 400
    db.execute('UPDATE service_items SET name=?, minutes=?, price_cents=?, worker_pay_cents=?, active=? '
               'WHERE id=?', (name, int(d['minutes']), int(d['price_cents']),
                              int(d.get('worker_pay_cents') or 0), 1 if d.get('active', 1) else 0, iid))
    db.commit()
    return jsonify(ok=True)


@bp.delete('/items/<int:iid>')
@auth_required('admin')
def deactivate_item(iid):
    db = get_db()
    db.execute('UPDATE service_items SET active=0 WHERE id=?', (iid,))
    db.commit()
    return jsonify(ok=True)


# ---------- 订单管理 ----------

def _order_filters(args):
    where, params = ['1=1'], []
    if args.get('from'):
        where.append('substr(o.sched_start,1,10)>=?')
        params.append(args['from'])
    if args.get('to'):
        where.append('substr(o.sched_start,1,10)<=?')
        params.append(args['to'])
    for field, col in (('status', 'o.status'), ('worker', 'o.worker_id'),
                       ('customer', 'o.customer_id'), ('item', 'o.item_id')):
        if args.get(field):
            where.append(f'{col}=?')
            params.append(args[field])
    return ' AND '.join(where), params


def _query_orders(args):
    where, params = _order_filters(args)
    rows = get_db().execute(
        'SELECT o.*, si.name AS item_name, uc.name AS customer_name, uc.phone AS customer_phone, '
        'uw.name AS worker_name FROM orders o '
        'JOIN service_items si ON si.id=o.item_id JOIN users uc ON uc.id=o.customer_id '
        'JOIN users uw ON uw.id=o.worker_id WHERE ' + where + ' ORDER BY o.sched_start DESC LIMIT 2000',
        params).fetchall()
    return [dict(r) for r in rows]


@bp.get('/orders')
@auth_required('admin')
def orders():
    return jsonify(orders=_query_orders(request.args))


@bp.post('/orders')
@auth_required('admin')
def create_order():
    """管理员代顾客下单（如电话预约）。"""
    d = request.get_json(force=True, silent=True) or {}
    db = get_db()
    customer = db.execute("SELECT * FROM users WHERE id=? AND role='customer'",
                          (d.get('customer_id'),)).fetchone()
    if customer is None:
        return jsonify(error='顾客不存在'), 400
    if not customer['worker_id']:
        return jsonify(error='该顾客未指派服务员'), 400
    item = db.execute('SELECT * FROM service_items WHERE id=? AND active=1', (d.get('item_id'),)).fetchone()
    if item is None:
        return jsonify(error='服务项目不存在或已下架'), 400
    try:
        start_dt = datetime.strptime(f"{d.get('date')} {d.get('time')}", '%Y-%m-%d %H:%M')
    except (TypeError, ValueError):
        return jsonify(error='日期时间格式不正确'), 400
    worker = db.execute('SELECT * FROM users WHERE id=?', (customer['worker_id'],)).fetchone()
    conflicts = services.get_conflicts(worker['id'], start_dt,
                                       start_dt + timedelta(minutes=item['minutes']))
    oid = services.create_order(dict(customer), dict(worker), dict(item), start_dt,
                                d.get('note') or '', f'管理员{g.user["name"]}代下单')
    db.commit()
    return jsonify(ok=True, order=services.get_order_or_404(oid), conflict_warning=conflicts or None)


@bp.get('/orders/<int:oid>/logs')
@auth_required('admin')
def order_logs(oid):
    rows = get_db().execute('SELECT * FROM order_logs WHERE order_id=? ORDER BY id DESC',
                            (oid,)).fetchall()
    return jsonify(logs=[dict(r) for r in rows])


def _load_order(oid):
    o = get_db().execute('SELECT * FROM orders WHERE id=?', (oid,)).fetchone()
    if o is None:
        return None, (jsonify(error='订单不存在'), 404)
    return dict(o), None


@bp.post('/orders/<int:oid>/reschedule')
@auth_required('admin')
def reschedule(oid):
    """改期：重算结束时间，恢复为已确认状态，并做冲突预警。"""
    o, err = _load_order(oid)
    if err:
        return err
    if o['status'] in ('completed', 'cancelled'):
        return jsonify(error='已完成/已取消订单不能改期'), 400
    d = request.get_json(force=True, silent=True) or {}
    try:
        start_dt = datetime.strptime(d.get('start'), '%Y-%m-%d %H:%M')
    except (TypeError, ValueError):
        return jsonify(error='时间格式不正确'), 400
    item = get_db().execute('SELECT minutes FROM service_items WHERE id=?', (o['item_id'],)).fetchone()
    end_dt = start_dt + timedelta(minutes=item['minutes'])
    conflicts = services.get_conflicts(o['worker_id'], start_dt, end_dt, exclude_order_id=oid)
    db = get_db()
    db.execute("UPDATE orders SET sched_start=?, sched_end=?, status='confirmed', updated_at=? WHERE id=?",
               (start_dt.strftime('%Y-%m-%d %H:%M'), end_dt.strftime('%Y-%m-%d %H:%M'),
                services.now_str(), oid))
    services.log_order(oid, g.user['name'], '管理员改期',
                       f'{o["sched_start"]} → {start_dt:%Y-%m-%d %H:%M}')
    db.commit()
    return jsonify(ok=True, conflict_warning=conflicts or None)


@bp.post('/orders/<int:oid>/reassign')
@auth_required('admin')
def reassign(oid):
    o, err = _load_order(oid)
    if err:
        return err
    if o['status'] in ('completed', 'cancelled'):
        return jsonify(error='已完成/已取消订单不能改派'), 400
    d = request.get_json(force=True, silent=True) or {}
    db = get_db()
    w = db.execute("SELECT * FROM users WHERE id=? AND role='worker' AND active=1",
                   (d.get('worker_id'),)).fetchone()
    if w is None:
        return jsonify(error='服务员不存在或已停用'), 400
    old = db.execute('SELECT name FROM users WHERE id=?', (o['worker_id'],)).fetchone()['name']
    db.execute('UPDATE orders SET worker_id=?, updated_at=? WHERE id=?', (w['id'], services.now_str(), oid))
    services.log_order(oid, g.user['name'], '管理员改派', f'{old} → {w["name"]}')
    db.commit()
    return jsonify(ok=True)


@bp.post('/orders/<int:oid>/resolve')
@auth_required('admin')
def resolve(oid):
    """异常订单处理入口：confirm 恢复确认 / complete 标记完成 / cancel_refund 取消退款。"""
    o, err = _load_order(oid)
    if err:
        return err
    action = (request.get_json(force=True, silent=True) or {}).get('action')
    db = get_db()
    if action == 'confirm':
        if o['status'] not in ('pending', 'exception'):
            return jsonify(error='仅待确认/异常订单可恢复'), 400
        db.execute("UPDATE orders SET status='confirmed', exception_type=NULL, exception_note=NULL, "
                   'updated_at=? WHERE id=?', (services.now_str(), oid))
        services.log_order(oid, g.user['name'], '恢复确认', '管理员处理异常后恢复为已确认')
    elif action == 'complete':
        if o['status'] in ('completed', 'cancelled'):
            return jsonify(error='订单已结束'), 400
        services.complete_order(o, f'管理员{g.user["name"]}')
    elif action == 'cancel_refund':
        if o['status'] == 'cancelled':
            return jsonify(error='订单已取消'), 400
        services.cancel_order(o, g.user['name'], '管理员取消（异常处理）', refund=True)
    else:
        return jsonify(error='未知的处理动作'), 400
    db.commit()
    return jsonify(ok=True)


# ---------- 统计与导出 ----------

@bp.get('/stats')
@auth_required('admin')
def stats():
    rows = _query_orders(request.args)
    s = dict(total=len(rows), completed=0, exception=0, cancelled=0, pending=0, confirmed=0,
             revenue_cents=0, refund_cents=0, wage_cents=0, wage_unpaid_cents=0)
    by_worker, by_item, by_month = {}, {}, {}
    for o in rows:
        st = o['status']
        s[st] = s.get(st, 0) + 1
        if st == 'completed':
            s['revenue_cents'] += o['price_cents'] if o['paid'] else 0
            s['wage_cents'] += o['worker_pay_cents']
            if not o['payout_id']:
                s['wage_unpaid_cents'] += o['worker_pay_cents']
        if o['refunded']:
            s['refund_cents'] += o['price_cents']
        for key, agg, label in ((o['worker_name'], by_worker, o['worker_name']),
                                (str(o['item_id']), by_item, o['item_name']),
                                (o['sched_start'][:7], by_month, o['sched_start'][:7])):
            a = agg.setdefault(key, dict(name=label, total=0, completed=0, revenue_cents=0, wage_cents=0))
            a['total'] += 1
            if st == 'completed':
                a['completed'] += 1
                a['revenue_cents'] += o['price_cents'] if o['paid'] else 0
                a['wage_cents'] += o['worker_pay_cents']
    return jsonify(summary=s,
                   by_worker=sorted(by_worker.values(), key=lambda x: -x['total']),
                   by_item=sorted(by_item.values(), key=lambda x: -x['total']),
                   by_month=sorted(by_month.values(), key=lambda x: x['name']))


@bp.get('/stats/export.csv')
@auth_required('admin')
def export_csv():
    rows = _query_orders(request.args)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['订单ID', '预约开始', '预约结束', '顾客', '手机号', '服务员', '服务项目',
                '状态', '价格(元)', '酬金(元)', '已扣款', '已退款', '异常类型', '异常说明', '备注'])
    for o in rows:
        w.writerow([o['id'], o['sched_start'], o['sched_end'], o['customer_name'], o['customer_phone'],
                    o['worker_name'], o['item_name'], STATUS_TEXT[o['status']],
                    f'{o["price_cents"] / 100:.2f}', f'{o["worker_pay_cents"] / 100:.2f}',
                    '是' if o['paid'] else '否', '是' if o['refunded'] else '否',
                    o['exception_type'] or '', o['exception_note'] or '', o['note'] or ''])
    data = '﻿' + buf.getvalue()  # 带 BOM 便于 Excel 识别 UTF-8
    return Response(data, mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename=orders.csv'})


# ---------- 批量充值 ----------

@bp.post('/recharge')
@auth_required('admin')
def recharge():
    d = request.get_json(force=True, silent=True) or {}
    ids = d.get('customer_ids') or []
    amount = d.get('amount_cents')
    if not isinstance(ids, list) or not ids:
        return jsonify(error='请选择要充值的顾客'), 400
    if not isinstance(amount, int) or amount <= 0:
        return jsonify(error='充值金额必须为正整数（分）'), 400
    note = (d.get('note') or '').strip() or '管理员充值'
    db = get_db()
    n = 0
    for cid in ids:
        if db.execute("SELECT 1 FROM users WHERE id=? AND role='customer'", (cid,)).fetchone():
            services.add_tx(cid, amount, 'recharge', None, note, f'管理员{g.user["name"]}')
            n += 1
    db.commit()
    return jsonify(ok=True, count=n)


@bp.get('/recharges')
@auth_required('admin')
def recharges():
    rows = get_db().execute(
        "SELECT t.id, t.delta_cents, t.note, t.created_at, u.name AS customer_name, u.phone "
        'FROM transactions t JOIN users u ON u.id=t.customer_id '
        "WHERE t.kind='recharge' ORDER BY t.id DESC LIMIT 100").fetchall()
    return jsonify(recharges=[dict(r) for r in rows])


# ---------- 酬金发放 ----------

@bp.get('/payout/preview')
@auth_required('admin')
def payout_preview():
    args = request.args
    if not (args.get('worker') and args.get('from') and args.get('to')):
        return jsonify(error='请选择服务员和日期范围'), 400
    rows = get_db().execute(
        "SELECT o.id, o.sched_start, o.worker_pay_cents, si.name AS item_name, uc.name AS customer_name "
        'FROM orders o JOIN service_items si ON si.id=o.item_id JOIN users uc ON uc.id=o.customer_id '
        "WHERE o.worker_id=? AND o.status='completed' AND o.payout_id IS NULL "
        'AND substr(o.sched_start,1,10) BETWEEN ? AND ? ORDER BY o.sched_start',
        (args['worker'], args['from'], args['to'])).fetchall()
    total = sum(r['worker_pay_cents'] for r in rows)
    return jsonify(orders=[dict(r) for r in rows], total_cents=total, count=len(rows))


@bp.post('/payout')
@auth_required('admin')
def payout():
    d = request.get_json(force=True, silent=True) or {}
    db = get_db()
    w = db.execute("SELECT * FROM users WHERE id=? AND role='worker'", (d.get('worker_id'),)).fetchone()
    if w is None:
        return jsonify(error='服务员不存在'), 400
    if not (d.get('from') and d.get('to')):
        return jsonify(error='请选择日期范围'), 400
    rows = db.execute(
        "SELECT id, worker_pay_cents FROM orders WHERE worker_id=? AND status='completed' "
        'AND payout_id IS NULL AND substr(sched_start,1,10) BETWEEN ? AND ?',
        (w['id'], d['from'], d['to'])).fetchall()
    if not rows:
        return jsonify(error='该时间段没有待发放的酬金订单'), 400
    total = sum(r['worker_pay_cents'] for r in rows)
    db.execute('INSERT INTO payouts(worker_id,from_date,to_date,total_cents,order_count,created_at) '
               'VALUES(?,?,?,?,?,?)',
               (w['id'], d['from'], d['to'], total, len(rows), services.now_str()))
    pid = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    db.execute('UPDATE orders SET payout_id=? WHERE id IN '
               f'({",".join(str(r["id"]) for r in rows)})', (pid,))
    for r in rows:
        services.log_order(r['id'], g.user['name'], '酬金发放',
                           f'{w["name"]} 获得 {r["worker_pay_cents"] / 100:.2f} 元')
    db.commit()
    return jsonify(ok=True, total_cents=total, count=len(rows))


@bp.get('/payouts')
@auth_required('admin')
def payouts():
    rows = get_db().execute(
        'SELECT p.*, u.name AS worker_name FROM payouts p JOIN users u ON u.id=p.worker_id '
        'ORDER BY p.id DESC LIMIT 100').fetchall()
    return jsonify(payouts=[dict(r) for r in rows])

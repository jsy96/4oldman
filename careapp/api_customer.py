"""顾客端接口：历史订单、预约（含冲突提醒）、账户明细。"""
from datetime import datetime, timedelta

from flask import Blueprint, g, jsonify, request

from .auth import auth_required
from .db import get_db
from . import services

bp = Blueprint('customer', __name__, url_prefix='/api/c')


@bp.get('/summary')
@auth_required('customer')
def summary():
    db = get_db()
    w = db.execute('SELECT name, phone, address FROM users WHERE id=?',
                   (g.user['worker_id'],)).fetchone() if g.user['worker_id'] else None
    nxt = db.execute(
        "SELECT o.sched_start, si.name FROM orders o JOIN service_items si ON si.id=o.item_id "
        "WHERE o.customer_id=? AND o.status IN ('pending','confirmed') AND o.sched_start>=? "
        'ORDER BY o.sched_start LIMIT 1',
        (g.user['id'], services.now_str()[:16])).fetchone()
    pending = db.execute(
        "SELECT COUNT(*) c FROM orders WHERE customer_id=? AND status IN ('pending','confirmed')",
        (g.user['id'],)).fetchone()['c']
    return jsonify(balance_cents=g.user['balance_cents'],
                   worker=dict(w) if w else None,
                   next_order=dict(nxt) if nxt else None, active_orders=pending)


@bp.get('/orders')
@auth_required('customer')
def orders():
    rows = get_db().execute(
        'SELECT o.id, o.sched_start, o.sched_end, o.status, o.price_cents, o.note, '
        'o.exception_type, si.name AS item_name, si.minutes, uw.name AS worker_name '
        'FROM orders o JOIN service_items si ON si.id=o.item_id '
        'JOIN users uw ON uw.id=o.worker_id WHERE o.customer_id=? ORDER BY o.sched_start DESC',
        (g.user['id'],)).fetchall()
    return jsonify(orders=[dict(r) for r in rows])


@bp.get('/transactions')
@auth_required('customer')
def transactions():
    rows = get_db().execute(
        'SELECT * FROM transactions WHERE customer_id=? ORDER BY created_at, id',
        (g.user['id'],)).fetchall()
    bal, out = 0, []
    for r in rows:  # 正序累计出每笔后的余额，再倒序返回（最新在前）
        bal += r['delta_cents']
        d = dict(r)
        d['balance_after'] = bal
        out.append(d)
    out.reverse()
    return jsonify(transactions=out, balance_cents=bal)


@bp.get('/services')
@auth_required()
def service_items():
    rows = get_db().execute('SELECT * FROM service_items WHERE active=1 ORDER BY id').fetchall()
    return jsonify(items=[dict(r) for r in rows])


@bp.post('/orders')
@auth_required('customer')
def book():
    d = request.get_json(force=True, silent=True) or {}
    db = get_db()
    item = db.execute('SELECT * FROM service_items WHERE id=? AND active=1',
                      (d.get('item_id'),)).fetchone()
    if item is None:
        return jsonify(error='服务项目不存在或已下架'), 400
    if not g.user['worker_id']:
        return jsonify(error='管理员还未给您指派服务员，请稍后再试或联系客服'), 400
    try:
        start_dt = datetime.strptime(f"{d.get('date')} {d.get('time')}", '%Y-%m-%d %H:%M')
    except (TypeError, ValueError):
        return jsonify(error='日期时间格式不正确'), 400
    if start_dt < datetime.now():
        return jsonify(error='不能预约过去的时间'), 400

    worker = db.execute('SELECT * FROM users WHERE id=?', (g.user['worker_id'],)).fetchone()
    end_dt = start_dt + timedelta(minutes=item['minutes'])
    conflicts = services.get_conflicts(worker['id'], start_dt, end_dt)
    if conflicts and not d.get('force'):
        return jsonify(error='所选时间段与您服务员的其它预约冲突',
                       conflicts=conflicts,
                       suggestions=services.suggest_slots(worker['id'], start_dt, item['minutes'])), 409
    oid = services.create_order(g.user, dict(worker), dict(item), start_dt, d.get('note') or '',
                                g.user['name'])
    db.commit()
    order = services.get_order_or_404(oid)
    order['conflict_warning'] = conflicts or None
    return jsonify(ok=True, order=order)


@bp.post('/orders/<int:oid>/cancel')
@auth_required('customer')
def cancel(oid):
    db = get_db()
    o = db.execute('SELECT * FROM orders WHERE id=? AND customer_id=?', (oid, g.user['id'])).fetchone()
    if o is None:
        return jsonify(error='订单不存在'), 404
    if o['status'] not in ('pending', 'confirmed'):
        return jsonify(error='该订单当前状态不可取消'), 400
    services.cancel_order(dict(o), g.user['name'], '顾客自行取消', refund=bool(o['paid']))
    db.commit()
    return jsonify(ok=True)

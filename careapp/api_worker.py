"""服务员端接口：待办、订单、确认、完成、异常上报、行程规划、顾客联系。"""
from datetime import date, datetime, timedelta

from flask import Blueprint, g, jsonify, request

from .ai import plan_route
from .auth import auth_required
from .db import get_db
from . import services
from flask import current_app

bp = Blueprint('worker', __name__, url_prefix='/api/w')

EXCEPTION_TYPES = ('顾客不在家', '顾客临时取消', '顾客身体原因', '只完成部分服务', '地址有误', '其他')


@bp.get('/overview')
@auth_required('worker')
def overview():
    db = get_db()
    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    cnt = lambda sql, p: db.execute(sql, p).fetchone()['c']
    today_orders = cnt("SELECT COUNT(*) c FROM orders WHERE worker_id=? AND "
                       "substr(sched_start,1,10)=? AND status IN ('confirmed','completed')",
                       (g.user['id'], today))
    to_confirm = cnt("SELECT COUNT(*) c FROM orders WHERE worker_id=? AND "
                     "substr(sched_start,1,10)=? AND status='pending'", (g.user['id'], tomorrow))
    month_done = cnt("SELECT COUNT(*) c FROM orders WHERE worker_id=? AND status='completed' "
                     "AND substr(sched_start,1,7)=?", (g.user['id'], today[:7]))
    month_pay = db.execute(
        "SELECT COALESCE(SUM(worker_pay_cents),0) s FROM orders WHERE worker_id=? AND status='completed' "
        "AND substr(sched_start,1,7)=?", (g.user['id'], today[:7])).fetchone()['s']
    return jsonify(today_orders=today_orders, to_confirm=to_confirm,
                   month_done=month_done, month_pay_cents=month_pay)


def _order_list(where, params):
    rows = get_db().execute(
        'SELECT o.*, si.name AS item_name, o.duration_minutes AS minutes, uc.name AS customer_name, '
        'uc.phone AS customer_phone, uc.address AS customer_address, uc.lat, uc.lng '
        'FROM orders o JOIN service_items si ON si.id=o.item_id '
        'JOIN users uc ON uc.id=o.customer_id WHERE ' + where + ' ORDER BY o.sched_start',
        params).fetchall()
    return [dict(r) for r in rows]


@bp.get('/orders')
@auth_required('worker')
def orders():
    scope = request.args.get('scope', 'upcoming')
    wid = g.user['id']
    if scope == 'today':
        where = "o.worker_id=? AND substr(o.sched_start,1,10)=? AND o.status!='cancelled'"
        rows = _order_list(where, (wid, date.today().isoformat()))
    elif scope == 'tomorrow':
        where = "o.worker_id=? AND substr(o.sched_start,1,10)=?"
        rows = _order_list(where, (wid, (date.today() + timedelta(days=1)).isoformat()))
    elif scope == 'day_after':
        rows = _order_list("o.worker_id=? AND substr(o.sched_start,1,10)=?",
                           (wid, (date.today() + timedelta(days=2)).isoformat()))
    elif scope == 'future':
        # 后天以后（不含明天、后天）的待服务订单
        where = ("o.worker_id=? AND o.status IN ('pending','confirmed') "
                 'AND substr(o.sched_start,1,10) BETWEEN ? AND ?')
        rows = _order_list(where, (wid,
                                   (date.today() + timedelta(days=3)).isoformat(),
                                   (date.today() + timedelta(days=60)).isoformat()))
    elif scope == 'history':
        where = "o.worker_id=? AND o.status IN ('completed','exception','cancelled') AND o.sched_start<?"
        rows = _order_list(where, (wid, services.now_str()[:10]))
        rows.reverse()
    else:  # 兼容旧参数：未来 7 天
        upto = (date.today() + timedelta(days=7)).isoformat()
        where = ("o.worker_id=? AND o.status IN ('pending','confirmed') "
                 'AND substr(o.sched_start,1,10) BETWEEN ? AND ?')
        rows = _order_list(where, (wid, date.today().isoformat(), upto))
    return jsonify(orders=rows)


@bp.post('/orders/<int:oid>/confirm')
@auth_required('worker')
def confirm(oid):
    db = get_db()
    o = db.execute('SELECT * FROM orders WHERE id=? AND worker_id=?', (oid, g.user['id'])).fetchone()
    if o is None:
        return jsonify(error='订单不存在'), 404
    if o['status'] != 'pending':
        return jsonify(error='该订单不是待确认状态'), 400
    db.execute("UPDATE orders SET status='confirmed', updated_at=? WHERE id=?",
               (services.now_str(), oid))
    services.log_order(oid, g.user['name'], '服务员确认', '已确认按预约时间上门')
    db.commit()
    return jsonify(ok=True)


@bp.post('/confirm_all')
@auth_required('worker')
def confirm_all():
    body = request.get_json(force=True, silent=True) or {}
    day = body.get('date') or (date.today() + timedelta(days=1)).isoformat()
    db = get_db()
    ids = [r['id'] for r in db.execute(
        "SELECT id FROM orders WHERE worker_id=? AND status='pending' AND substr(sched_start,1,10)=?",
        (g.user['id'], day)).fetchall()]
    for oid in ids:
        db.execute("UPDATE orders SET status='confirmed', updated_at=? WHERE id=?",
                   (services.now_str(), oid))
        services.log_order(oid, g.user['name'], '服务员确认', '一键确认明日订单')
    db.commit()
    return jsonify(ok=True, count=len(ids))


@bp.post('/orders/<int:oid>/complete')
@auth_required('worker')
def complete(oid):
    db = get_db()
    o = db.execute('SELECT * FROM orders WHERE id=? AND worker_id=?', (oid, g.user['id'])).fetchone()
    if o is None:
        return jsonify(error='订单不存在'), 404
    if o['status'] not in ('confirmed', 'exception'):
        return jsonify(error='仅已确认/异常订单可标记完成'), 400
    note = (request.get_json(force=True, silent=True) or {}).get('note') or ''
    services.complete_order(dict(o), g.user['name'], note)
    db.commit()
    return jsonify(ok=True)


@bp.post('/orders/<int:oid>/exception')
@auth_required('worker')
def exception(oid):
    db = get_db()
    o = db.execute('SELECT * FROM orders WHERE id=? AND worker_id=?', (oid, g.user['id'])).fetchone()
    if o is None:
        return jsonify(error='订单不存在'), 404
    if o['status'] not in ('pending', 'confirmed'):
        return jsonify(error='该订单状态不可上报异常'), 400
    d = request.get_json(force=True, silent=True) or {}
    etype = d.get('type')
    if etype not in EXCEPTION_TYPES:
        return jsonify(error='请选择异常类型'), 400
    db.execute("UPDATE orders SET status='exception', exception_type=?, exception_note=?, updated_at=? "
               'WHERE id=?', (etype, d.get('note') or '', services.now_str(), oid))
    services.log_order(oid, g.user['name'], '上报异常', f'{etype} {d.get("note") or ""}')
    db.commit()
    return jsonify(ok=True)


@bp.get('/route')
@auth_required('worker')
def route():
    day = request.args.get('date') or (date.today() + timedelta(days=1)).isoformat()
    try:
        datetime.strptime(day, '%Y-%m-%d')
    except ValueError:
        return jsonify(error='日期格式不正确'), 400
    rows = get_db().execute(
        "SELECT o.*, si.name AS item_name, o.duration_minutes AS minutes, uc.name AS customer_name, "
        'uc.phone AS customer_phone, uc.address AS customer_address, uc.lat, uc.lng '
        'FROM orders o JOIN service_items si ON si.id=o.item_id '
        'JOIN users uc ON uc.id=o.customer_id WHERE o.worker_id=? AND '
        "substr(o.sched_start,1,10)=? AND o.status IN ('confirmed','completed')",
        (g.user['id'], day)).fetchall()
    plan = plan_route(g.user, [dict(r) for r in rows], current_app.config['APP_CONF'], day)
    return jsonify(plan)


@bp.get('/customers')
@auth_required('worker')
def customers():
    rows = get_db().execute(
        'SELECT id, name, phone, address, lat, lng, balance_cents FROM users '
        'WHERE role=\'customer\' AND worker_id=? AND active=1 ORDER BY name', (g.user['id'],)).fetchall()
    return jsonify(customers=[dict(r) for r in rows])

"""订单/账户共享业务逻辑：冲突检测、下单、完成、取消退款、流水。"""
from datetime import datetime, timedelta

from flask import current_app

from .db import get_db


def now_str():
    return datetime.now().strftime('%Y-%m-%d %H:%M')


def log_order(order_id, actor, action, detail=''):
    db = get_db()
    db.execute('INSERT INTO order_logs(order_id,actor,action,detail,created_at) VALUES(?,?,?,?,?)',
               (order_id, actor, action, detail, now_str()))


def add_tx(customer_id, delta_cents, kind, order_id=None, note='', by='系统'):
    """记录账户流水并更新余额。"""
    db = get_db()
    db.execute('INSERT INTO transactions(customer_id,delta_cents,kind,order_id,note,created_by,created_at) '
               'VALUES(?,?,?,?,?,?,?)',
               (customer_id, delta_cents, kind, order_id, note, by, now_str()))
    db.execute('UPDATE users SET balance_cents=balance_cents+? WHERE id=?', (delta_cents, customer_id))


def get_conflicts(worker_id, start_dt, end_dt, exclude_order_id=None):
    """同一服务员同一天订单时间冲突检测（含前后 30 分钟路程缓冲）。"""
    db = get_db()
    buf = timedelta(minutes=current_app.config['APP_CONF']['conflict_buffer_min'])
    rows = db.execute(
        "SELECT o.id, o.sched_start, o.sched_end, si.name AS item_name "
        "FROM orders o JOIN service_items si ON si.id=o.item_id "
        "WHERE o.worker_id=? AND o.status IN ('pending','confirmed') "
        "AND substr(o.sched_start,1,10)=? ORDER BY o.sched_start",
        (worker_id, start_dt.strftime('%Y-%m-%d'))).fetchall()
    conflicts = []
    for r in rows:
        if exclude_order_id and r['id'] == exclude_order_id:
            continue
        s = datetime.strptime(r['sched_start'], '%Y-%m-%d %H:%M')
        e = datetime.strptime(r['sched_end'], '%Y-%m-%d %H:%M')
        if start_dt < e + buf and s - buf < end_dt:
            conflicts.append(dict(id=r['id'], sched_start=r['sched_start'], sched_end=r['sched_end'],
                                  item_name=r['item_name']))
    return conflicts


def suggest_slots(worker_id, want_dt, duration_min, limit=3):
    """建议当天最近的空闲时段（工作时间内，每 30 分钟一档）。"""
    conf = current_app.config['APP_CONF']
    h0, m0 = map(int, conf['work_hours']['start'].split(':'))
    h1, m1 = map(int, conf['work_hours']['end'].split(':'))
    t = datetime(want_dt.year, want_dt.month, want_dt.day, h0, m0)
    end_limit = datetime(want_dt.year, want_dt.month, want_dt.day, h1, m1)
    slots = []
    while t + timedelta(minutes=duration_min) <= end_limit:
        if not get_conflicts(worker_id, t, t + timedelta(minutes=duration_min)):
            slots.append(t)
        t += timedelta(minutes=30)
    slots.sort(key=lambda s: abs((s - want_dt).total_seconds()))
    return [s.strftime('%H:%M') for s in slots[:limit]]


def create_order(customer, worker, item, start_dt, note, actor):
    db = get_db()
    price, pay = item['price_cents'], item['worker_pay_cents']
    end_dt = start_dt + timedelta(minutes=item['minutes'])
    db.execute(
        'INSERT INTO orders(customer_id,worker_id,item_id,sched_start,sched_end,status,'
        'price_cents,worker_pay_cents,note,created_at,updated_at) '
        "VALUES(?,?,?,?,?, 'pending',?,?,?,?,?)",
        (customer['id'], worker['id'], item['id'], start_dt.strftime('%Y-%m-%d %H:%M'),
         end_dt.strftime('%Y-%m-%d %H:%M'), price, pay, note or '', now_str(), now_str()))
    oid = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    log_order(oid, actor, '下单', f'{customer["name"]} 预约 {item["name"]} '
                f'{start_dt.strftime("%Y-%m-%d %H:%M")}，服务员 {worker["name"]}')
    return oid


def complete_order(order, actor, note=''):
    """完成订单：扣款（余额可为负，欠费提醒管理员充值）、写流水与日志。"""
    db = get_db()
    customer = db.execute('SELECT name FROM users WHERE id=?', (order['customer_id'],)).fetchone()
    if not order['paid']:
        add_tx(order['customer_id'], -order['price_cents'], 'order', order['id'],
               f'服务扣款：订单#{order["id"]}', by=actor)
    db.execute("UPDATE orders SET status='completed', paid=1, updated_at=?, "
               'exception_type=NULL, exception_note=NULL WHERE id=?', (now_str(), order['id']))
    log_order(order['id'], actor, '完成服务', f'已向 {customer["name"]} 扣款 '
              f'{order["price_cents"] / 100:.2f} 元 {note and "（" + note + "）" or ""}')


def cancel_order(order, actor, reason, refund=True):
    """取消订单；已扣款的自动退款并生成退款流水。"""
    db = get_db()
    refunded = 0
    if refund and order['paid']:
        add_tx(order['customer_id'], order['price_cents'], 'refund', order['id'],
               f'订单取消退款：订单#{order["id"]}', by=actor)
        refunded = 1
    db.execute("UPDATE orders SET status='cancelled', refunded=?, updated_at=? WHERE id=?",
               (refunded, now_str(), order['id']))
    log_order(order['id'], actor, '取消订单', f'{reason}' + ('，已退款' if refunded else ''))


def get_order_or_404(order_id):
    row = get_db().execute(
        'SELECT o.*, si.name AS item_name, si.minutes, '
        'uc.name AS customer_name, uc.phone AS customer_phone, uc.address AS customer_address, '
        'uw.name AS worker_name FROM orders o '
        'JOIN service_items si ON si.id=o.item_id '
        'JOIN users uc ON uc.id=o.customer_id '
        'JOIN users uw ON uw.id=o.worker_id WHERE o.id=?', (order_id,)).fetchone()
    return dict(row) if row else None

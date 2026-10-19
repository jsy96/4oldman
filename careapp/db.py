"""数据库连接、表结构与初始示例数据。"""
import json
import os
import sqlite3
from datetime import datetime, timedelta

from flask import g
from werkzeug.security import generate_password_hash

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  phone TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('admin','worker','customer')),
  name TEXT NOT NULL,
  address TEXT NOT NULL DEFAULT '',
  lat REAL,
  lng REAL,
  worker_id INTEGER REFERENCES users(id),
  balance_cents INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS service_items(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  minutes INTEGER NOT NULL,
  price_cents INTEGER NOT NULL,
  worker_pay_cents INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id INTEGER NOT NULL REFERENCES users(id),
  worker_id INTEGER NOT NULL REFERENCES users(id),
  item_id INTEGER NOT NULL REFERENCES service_items(id),
  sched_start TEXT NOT NULL,
  sched_end TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('pending','confirmed','completed','exception','cancelled')),
  exception_type TEXT,
  exception_note TEXT,
  price_cents INTEGER NOT NULL,
  worker_pay_cents INTEGER NOT NULL DEFAULT 0,
  paid INTEGER NOT NULL DEFAULT 0,
  refunded INTEGER NOT NULL DEFAULT 0,
  note TEXT,
  payout_id INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transactions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id INTEGER NOT NULL REFERENCES users(id),
  delta_cents INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('recharge','order','refund','adjust')),
  order_id INTEGER,
  note TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payouts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  worker_id INTEGER NOT NULL REFERENCES users(id),
  from_date TEXT NOT NULL,
  to_date TEXT NOT NULL,
  total_cents INTEGER NOT NULL,
  order_count INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS order_logs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id INTEGER NOT NULL REFERENCES orders(id),
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  detail TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions(
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_worker ON orders(worker_id, sched_start);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id, sched_start);
CREATE INDEX IF NOT EXISTS idx_tx_customer ON transactions(customer_id, created_at);
"""


def load_config():
    with open(os.path.join(BASE, 'config.json'), encoding='utf-8') as f:
        return json.load(f)


def db_path():
    return os.environ.get('CARE_DB') or os.path.join(BASE, 'data', 'care.db')


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(db_path())
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
        g.db.execute('PRAGMA journal_mode=WAL')
    return g.db


def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db(app):
    path = db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    if conn.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0:
        seed(conn)
    conn.commit()
    conn.close()


def seed(conn):
    """首次运行写入演示数据：1 管理员 + 2 服务员 + 4 顾客 + 5 服务项目 + 示例订单。"""
    conf = load_config()
    lat0, lng0 = conf['map']['center_lat'], conf['map']['center_lng']
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    today = datetime.now().date()

    def u(phone, pwd, role, name, address, la, ln, worker_id=None):
        conn.execute(
            'INSERT INTO users(phone,password_hash,role,name,address,lat,lng,worker_id,created_at) '
            'VALUES(?,?,?,?,?,?,?,?,?)',
            (phone, generate_password_hash(pwd), role, name, address, la, ln, worker_id, now))
        return conn.execute('SELECT last_insert_rowid()').fetchone()[0]

    admin = u('13900000001', 'admin123', 'admin', '管理员', '', None, None)
    w1 = u('13800001001', '123456', 'worker', '王秀英', '江汉区解放大道690号', lat0 + 0.012, lng0 - 0.008)
    w2 = u('13800001002', '123456', 'worker', '李建国', '武昌区中南路99号', lat0 - 0.015, lng0 + 0.010)
    c1 = u('13800002001', '123456', 'customer', '陈桂芳', '江岸区中山大道100号', lat0 + 0.005, lng0 + 0.004, w1)
    c2 = u('13800002002', '123456', 'customer', '周明德', '硚口区解放大道55号', lat0 + 0.018, lng0 - 0.012, w1)
    c3 = u('13800002003', '123456', 'customer', '吴淑珍', '洪山区珞狮路500号', lat0 - 0.020, lng0 - 0.015, w2)
    c4 = u('13800002004', '123456', 'customer', '郑国强', '青山区和平大道300号', lat0 - 0.008, lng0 + 0.020, w2)

    items = {}
    for name, minutes, price, pay in [
        ('上门助浴', 60, 8000, 4500),
        ('居家保洁', 90, 7000, 4000),
        ('陪同就医', 120, 10000, 6000),
        ('康复理疗', 60, 9000, 5500),
        ('助餐配送', 20, 2000, 800),
    ]:
        conn.execute('INSERT INTO service_items(name,minutes,price_cents,worker_pay_cents) VALUES(?,?,?,?)',
                     (name, minutes, price, pay))
        items[name] = (conn.execute('SELECT last_insert_rowid()').fetchone()[0], minutes, price, pay)

    def order(cid, wid, item, day, hm, status, paid=0):
        iid, minutes, price, pay = items[item]
        start = f'{day} {hm}'
        end_min = datetime.strptime(start, '%Y-%m-%d %H:%M') + timedelta(minutes=minutes)
        conn.execute(
            'INSERT INTO orders(customer_id,worker_id,item_id,sched_start,sched_end,status,'
            'price_cents,worker_pay_cents,paid,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (cid, wid, iid, start, end_min.strftime('%Y-%m-%d %H:%M'), status, price, pay, paid, now, now))
        oid = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        conn.execute('INSERT INTO order_logs(order_id,actor,action,detail,created_at) VALUES(?,?,?,?,?)',
                     (oid, '系统', '初始化', '示例数据', now))
        return oid, price

    # 已完成的历史订单（会生成扣款流水）
    txs = []
    for cid, wid, item, day, hm in [
        (c1, w1, '上门助浴', str(today - timedelta(days=5)), '09:00'),
        (c2, w1, '居家保洁', str(today - timedelta(days=5)), '14:00'),
        (c3, w2, '陪同就医', str(today - timedelta(days=4)), '08:30'),
        (c1, w1, '康复理疗', str(today - timedelta(days=2)), '10:00'),
        (c4, w2, '助餐配送', str(today - timedelta(days=2)), '12:00'),
    ]:
        oid, price = order(cid, wid, item, day, hm, 'completed', paid=1)
        conn.execute('UPDATE orders SET updated_at=? WHERE id=?', (now, oid))
        txs.append((cid, -price, 'order', oid, f'服务扣款：{item}'))

    # 今天已确认 + 明天待确认（供服务员确认/路线演示）
    order(c2, w1, '上门助浴', str(today), '09:00', 'confirmed')
    order(c1, w1, '居家保洁', str(today), '14:00', 'confirmed')
    order(c3, w2, '康复理疗', str(today), '10:00', 'confirmed')
    order(c1, w1, '上门助浴', str(today + timedelta(days=1)), '09:30', 'pending')
    order(c2, w1, '陪同就医', str(today + timedelta(days=1)), '13:30', 'pending')
    order(c3, w2, '上门助浴', str(today + timedelta(days=1)), '11:00', 'pending')
    order(c4, w2, '居家保洁', str(today + timedelta(days=2)), '09:00', 'pending')

    # 每位顾客月初批量充值 800 元，再扣除已完成订单费用，余额由流水推出
    month_first = f'{today.strftime("%Y-%m")}-01 09:00'
    for cid in (c1, c2, c3, c4):
        txs.insert(0, (cid, 80000, 'recharge', None, f'{today.strftime("%Y年%m月")}批量充值'))
    for cid, delta, kind, oid, note in txs:
        conn.execute('INSERT INTO transactions(customer_id,delta_cents,kind,order_id,note,created_by,created_at) '
                     'VALUES(?,?,?,?,?,?,?)',
                     (cid, delta, kind, oid, note, '管理员', month_first if kind == 'recharge' else now))
        conn.execute('UPDATE users SET balance_cents=balance_cents+? WHERE id=?', (delta, cid))

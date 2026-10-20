"""数据库层：默认本地 SQLite；配置 database_url 后自动切换云数据库。

database_url 来源（二选一，均不入 git）：
  1. 环境变量 DATABASE_URL
  2. secrets.json 的 "database_url" 字段（模板见 secrets.example.json）

支持三种形态：
  mysql://用户:密码@主机:3306/库名     —— 腾讯云 MySQL（云函数 SCF 部署推荐，同区内网连接）
  postgresql://...                    —— PostgreSQL（如 Supabase，需自行加 psycopg2-binary）
  未配置                              —— 本地 SQLite（data/care.db）

三套 SQL 完全共用：占位符统一写 `?`（执行时自动转 `%s`）；
自增主键统一走 insert_returning_id()（PG 用 RETURNING，SQLite/MySQL 用 lastrowid）。
"""
import json
import os
import sqlite3
from datetime import datetime, timedelta
from urllib.parse import urlparse, unquote

from flask import g
from werkzeug.security import generate_password_hash

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id __ID__,
  phone TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('admin','worker','customer')),
  name TEXT NOT NULL,
  address TEXT NOT NULL DEFAULT '',
  lat __REAL__,
  lng __REAL__,
  worker_id INTEGER REFERENCES users(id),
  balance_cents INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS service_items(
  id __ID__,
  name TEXT NOT NULL,
  minutes INTEGER NOT NULL,
  price_cents INTEGER NOT NULL,
  worker_pay_cents INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS orders(
  id __ID__,
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
  id __ID__,
  customer_id INTEGER NOT NULL REFERENCES users(id),
  delta_cents INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('recharge','order','refund','adjust')),
  order_id INTEGER,
  note TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payouts(
  id __ID__,
  worker_id INTEGER NOT NULL REFERENCES users(id),
  from_date TEXT NOT NULL,
  to_date TEXT NOT NULL,
  total_cents INTEGER NOT NULL,
  order_count INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS order_logs(
  id __ID__,
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

SCHEMA_SQLITE = SCHEMA.replace('__ID__', 'INTEGER PRIMARY KEY AUTOINCREMENT') \
                      .replace('__REAL__', 'REAL')
SCHEMA_PG = SCHEMA.replace('__ID__', 'SERIAL PRIMARY KEY') \
                  .replace('__REAL__', 'DOUBLE PRECISION')
SCHEMA_MYSQL = (SCHEMA.replace('__ID__', 'INT PRIMARY KEY AUTO_INCREMENT')
                      .replace('__REAL__', 'DOUBLE')
                      .replace('phone TEXT UNIQUE NOT NULL', 'phone VARCHAR(20) UNIQUE NOT NULL')
                      .replace('address TEXT NOT NULL DEFAULT \'\'',
                               'address VARCHAR(255) NOT NULL DEFAULT \'\'')
                      .replace('token TEXT PRIMARY KEY', 'token VARCHAR(64) PRIMARY KEY'))


def _secrets():
    try:
        with open(os.path.join(BASE, 'secrets.json'), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def database_url():
    """返回云数据库连接串；空串 = 本地 SQLite。设了 CARE_DB 时强制 SQLite（测试用）。"""
    if os.environ.get('CARE_DB'):
        return ''
    url = os.environ.get('DATABASE_URL', '').strip()
    if not url:
        url = (_secrets().get('database_url') or '').strip()
    if url.startswith('mysql+pymysql://'):
        url = 'mysql://' + url[len('mysql+pymysql://'):]
    if url.startswith(('postgres://', 'postgresql://')) and 'sslmode' not in url:
        url += ('&' if '?' in url else '?') + 'sslmode=require'
    return url


def db_kind(url=''):
    url = url or database_url()
    if url.startswith(('postgres://', 'postgresql://')):
        return 'pg'
    if url.startswith('mysql://'):
        return 'mysql'
    return 'sqlite'


def load_config():
    with open(os.path.join(BASE, 'config.json'), encoding='utf-8') as f:
        return json.load(f)


def db_path():
    return os.environ.get('CARE_DB') or os.path.join(BASE, 'data', 'care.db')


class DB:
    """统一连接封装：execute 返回可 fetchone/fetchall/rowcount 的游标，行均为 dict 风格。"""

    def __init__(self, conn, kind):
        self.conn, self.kind = conn, kind

    def execute(self, sql, params=()):
        if self.kind == 'pg':
            from psycopg2.extras import RealDictCursor
            cur = self.conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(sql.replace('?', '%s'), params)
            return cur
        if self.kind == 'mysql':
            from pymysql.cursors import DictCursor
            cur = self.conn.cursor(DictCursor)
            cur.execute(sql.replace('?', '%s'), params)
            return cur
        return self.conn.execute(sql, params)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        try:
            self.conn.rollback()
        except Exception:
            pass


def insert_returning_id(db, sql, params):
    """INSERT 并返回自增 id：PG 用 RETURNING，SQLite/MySQL 用 lastrowid。"""
    if db.kind == 'pg':
        return db.execute(sql + ' RETURNING id', params).fetchone()['id']
    return db.execute(sql, params).lastrowid


_pg_pool = None


def _pg_connect(url):
    import psycopg2
    return psycopg2.connect(dsn=url)


def _mysql_connect(url):
    import pymysql
    p = urlparse(url)
    return pymysql.connect(host=p.hostname, port=p.port or 3306,
                           user=unquote(p.username or ''), password=unquote(p.password or ''),
                           database=(p.path or '/')[1:], charset='utf8mb4',
                           autocommit=False, connect_timeout=6)


def get_db():
    if 'db' not in g:
        url = database_url()
        kind = db_kind(url)
        if kind == 'pg':
            global _pg_pool
            if _pg_pool is None:
                from psycopg2.pool import ThreadedConnectionPool
                _pg_pool = ThreadedConnectionPool(1, 8, dsn=url)
            g.db = DB(_pg_pool.getconn(), 'pg')
        elif kind == 'mysql':
            g.db = DB(_mysql_connect(url), 'mysql')  # 内网直连，低流量下每请求一连接即可
        else:
            conn = sqlite3.connect(db_path())
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('PRAGMA journal_mode=WAL')
            g.db = DB(conn, 'sqlite')
    return g.db


def close_db(e=None):
    db = g.pop('db', None)
    if db is None:
        return
    try:
        db.commit() if e is None else db.rollback()
    finally:
        if db.kind == 'pg':
            _pg_pool.putconn(db.conn)
        else:
            db.conn.close()


def _run_script(db, sql):
    """执行多语句 DDL。"""
    if db.kind == 'sqlite':
        db.conn.executescript(sql)
        return
    for stmt in sql.split(';'):
        if stmt.strip():
            db.execute(stmt)


def init_db(app):
    """启动时建表；空库自动写入演示数据。三种数据库同一套逻辑。"""
    url = database_url()
    kind = db_kind(url)
    if kind == 'pg':
        conn = _pg_connect(url)
        db = DB(conn, 'pg')
        _run_script(db, SCHEMA_PG)
    elif kind == 'mysql':
        conn = _mysql_connect(url)
        db = DB(conn, 'mysql')
        _run_script(db, SCHEMA_MYSQL)
    else:
        path = db_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        db = DB(conn, 'sqlite')
        _run_script(db, SCHEMA_SQLITE)
    try:
        if db.execute('SELECT COUNT(*) AS c FROM users').fetchone()['c'] == 0:
            seed(db)
        db.commit()
    except Exception:
        db.rollback()
        conn.close()
        raise


def seed(db):
    """首次运行写入演示数据：1 管理员 + 2 服务员 + 4 顾客 + 5 服务项目 + 示例订单。"""
    conf = load_config()
    lat0, lng0 = conf['map']['center_lat'], conf['map']['center_lng']
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    today = datetime.now().date()

    def u(phone, pwd, role, name, address, la, ln, worker_id=None):
        return insert_returning_id(
            db, 'INSERT INTO users(phone,password_hash,role,name,address,lat,lng,worker_id,created_at) '
                'VALUES(?,?,?,?,?,?,?,?,?)',
            (phone, generate_password_hash(pwd), role, name, address, la, ln, worker_id, now))

    admin = u('13900000001', 'admin123', 'admin', '管理员', '', None, None)  # noqa: F841
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
        iid = insert_returning_id(
            db, 'INSERT INTO service_items(name,minutes,price_cents,worker_pay_cents) VALUES(?,?,?,?)',
            (name, minutes, price, pay))
        items[name] = (iid, minutes, price, pay)

    def order(cid, wid, item, day, hm, status, paid=0):
        iid, minutes, price, pay = items[item]
        start = f'{day} {hm}'
        end_min = datetime.strptime(start, '%Y-%m-%d %H:%M') + timedelta(minutes=minutes)
        oid = insert_returning_id(
            db, 'INSERT INTO orders(customer_id,worker_id,item_id,sched_start,sched_end,status,'
                'price_cents,worker_pay_cents,paid,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (cid, wid, iid, start, end_min.strftime('%Y-%m-%d %H:%M'), status, price, pay, paid, now, now))
        db.execute('INSERT INTO order_logs(order_id,actor,action,detail,created_at) VALUES(?,?,?,?,?)',
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
        db.execute('UPDATE orders SET updated_at=? WHERE id=?', (now, oid))
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
        db.execute('INSERT INTO transactions(customer_id,delta_cents,kind,order_id,note,created_by,created_at) '
                   'VALUES(?,?,?,?,?,?,?)',
                   (cid, delta, kind, oid, note, '管理员', month_first if kind == 'recharge' else now))
        db.execute('UPDATE users SET balance_cents=balance_cents+? WHERE id=?', (delta, cid))

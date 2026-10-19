"""登录、会话与鉴权。"""
import functools
import secrets
from datetime import datetime

from flask import Blueprint, g, jsonify, request
from werkzeug.security import check_password_hash

from .db import get_db

bp = Blueprint('auth', __name__)


@bp.post('/api/login')
def login():
    d = request.get_json(force=True, silent=True) or {}
    phone = (d.get('phone') or '').strip()
    password = d.get('password') or ''
    if not phone or not password:
        return jsonify(error='请输入账号和密码'), 400
    db = get_db()
    row = db.execute('SELECT * FROM users WHERE phone=?', (phone,)).fetchone()
    if row is None or not check_password_hash(row['password_hash'], password):
        return jsonify(error='账号或密码错误'), 401
    if not row['active']:
        return jsonify(error='账号已停用，请联系管理员'), 403
    token = secrets.token_hex(32)
    db.execute('INSERT INTO sessions(token,user_id,created_at) VALUES(?,?,?)',
               (token, row['id'], datetime.now().strftime('%Y-%m-%d %H:%M')))
    db.commit()
    return jsonify(token=token, role=row['role'], name=row['name'], id=row['id'])


@bp.post('/api/logout')
def logout():
    db = get_db()
    db.execute('DELETE FROM sessions WHERE token=?', (g.get('token') or '',))
    db.commit()
    return jsonify(ok=True)


def auth_required(*roles):
    """请求鉴权装饰器；roles 为空表示任意登录用户。"""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            token = (request.headers.get('Authorization') or '').replace('Bearer ', '').strip()
            db = get_db()
            row = db.execute(
                'SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?', (token,)).fetchone()
            if row is None:
                return jsonify(error='请先登录'), 401
            if not row['active']:
                return jsonify(error='账号已停用'), 403
            if roles and row['role'] not in roles:
                return jsonify(error='无权访问'), 403
            g.token = token
            g.user = dict(row)
            return fn(*a, **kw)
        return wrapper
    return deco


@bp.get('/api/me')
@auth_required()
def me():
    u = g.user
    extra = {}
    if u['role'] == 'customer':
        db = get_db()
        w = db.execute('SELECT name, phone, address FROM users WHERE id=?',
                       (u['worker_id'],)).fetchone() if u['worker_id'] else None
        extra = dict(worker=dict(w) if w else None, balance_cents=u['balance_cents'])
    return jsonify(id=u['id'], phone=u['phone'], role=u['role'], name=u['name'],
                   address=u['address'], **extra)

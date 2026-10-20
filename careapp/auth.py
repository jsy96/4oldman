"""登录、会话、鉴权、短信验证码与密码管理。"""
import functools
import random
import re
import secrets
import time
from datetime import datetime

from flask import Blueprint, g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from . import sms
from .db import HASH_METHOD, get_db

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
    # 旧版 100 万次迭代哈希自动升级为 15 万次（首次登录慢一次，之后每次登录更快）
    if not row['password_hash'].startswith(HASH_METHOD + '$'):
        db.execute('UPDATE users SET password_hash=? WHERE id=?',
                   (generate_password_hash(password, method=HASH_METHOD), row['id']))
    token = secrets.token_hex(32)
    db.execute('INSERT INTO sessions(token,user_id,created_at) VALUES(?,?,?)',
               (token, row['id'], datetime.now().strftime('%Y-%m-%d %H:%M')))
    db.commit()
    return jsonify(token=token, role=row['role'], name=row['name'], id=row['id'],
                   is_super=row['is_super'])


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
                   address=u['address'], is_super=u.get('is_super', 0), **extra)


# ---------- 短信验证码 / 密码 ----------

@bp.post('/api/auth/send-code')
def send_code():
    d = request.get_json(force=True, silent=True) or {}
    phone = (d.get('phone') or '').strip()
    scene = (d.get('scene') or 'reset').strip()
    if scene not in ('reset', 'change'):
        return jsonify(error='场景不正确'), 400
    if not re.fullmatch(r'\d{5,15}', phone):
        return jsonify(error='手机号格式不正确'), 400
    db = get_db()
    user = db.execute('SELECT id, active FROM users WHERE phone=?', (phone,)).fetchone()
    if user is not None and not user['active']:
        return jsonify(error='账号已停用，请联系管理员'), 403
    if user is None:
        if scene == 'reset':
            # 按业务要求：未注册手机号直接提示，且不发短信
            return jsonify(error='该手机号尚未注册'), 400
        return jsonify(ok=True, message='若该手机号已注册，验证码将发送')
    now_epoch = int(time.time())
    last = db.execute('SELECT created_at FROM sms_codes WHERE phone=? AND scene=? '
                      'ORDER BY id DESC LIMIT 1', (phone, scene)).fetchone()
    if last:
        try:
            last_ts = int(datetime.strptime(last['created_at'], '%Y-%m-%d %H:%M:%S').timestamp())
        except (TypeError, ValueError):
            last_ts = 0
        if now_epoch - last_ts < 60:
            return jsonify(error='发送过于频繁，请 1 分钟后再试'), 429
    code = f'{random.randint(0, 999999):06d}'
    try:
        mode = sms.send_verification_code(phone, code, 5)
    except sms.SmsNotConfigured as e:
        return jsonify(error=str(e)), 503
    except Exception as e:
        return jsonify(error=f'短信发送失败，请稍后重试（{e}）'), 502
    db.execute('INSERT INTO sms_codes(phone,code,scene,expires_at,used,attempts,created_at) '
               'VALUES(?,?,?,?,0,0,?)',
               (phone, code, scene, now_epoch + 300,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    db.commit()
    resp = dict(ok=True, message='验证码已发送，5 分钟内有效')
    if mode == 'debug':
        resp['debug_code'] = code  # 仅本地调试模式返回
    return jsonify(resp)


def _check_code(db, phone, scene, code):
    """校验验证码；返回 (ok, error)。"""
    row = db.execute('SELECT * FROM sms_codes WHERE phone=? AND scene=? AND used=0 '
                     'ORDER BY id DESC LIMIT 1', (phone, scene)).fetchone()
    if row is None:
        return False, '请先获取验证码'
    if int(time.time()) > row['expires_at']:
        db.execute('UPDATE sms_codes SET used=1 WHERE id=?', (row['id'],))
        db.commit()
        return False, '验证码已过期，请重新获取'
    if row['attempts'] >= 5:
        db.execute('UPDATE sms_codes SET used=1 WHERE id=?', (row['id'],))
        db.commit()
        return False, '验证码错误次数过多，请重新获取'
    if str(row['code']) != str(code):
        db.execute('UPDATE sms_codes SET attempts=attempts+1 WHERE id=?', (row['id'],))
        db.commit()
        return False, '验证码错误'
    db.execute('UPDATE sms_codes SET used=1 WHERE id=?', (row['id'],))
    return True, ''


@bp.post('/api/auth/reset-password')
def reset_password():
    """未登录：手机号 + 短信验证码重置密码。"""
    d = request.get_json(force=True, silent=True) or {}
    phone = (d.get('phone') or '').strip()
    code = (d.get('code') or '').strip()
    new = d.get('new_password') or ''
    if not re.fullmatch(r'\d{5,15}', phone) or not code:
        return jsonify(error='请填写手机号和验证码'), 400
    if len(new) < 6:
        return jsonify(error='新密码至少 6 位'), 400
    db = get_db()
    user = db.execute('SELECT id, active FROM users WHERE phone=?', (phone,)).fetchone()
    if user is None:
        return jsonify(error='该手机号未注册'), 400
    if not user['active']:
        return jsonify(error='账号已停用，请联系管理员'), 403
    ok, err = _check_code(db, phone, 'reset', code)
    if not ok:
        return jsonify(error=err), 400
    db.execute('UPDATE users SET password_hash=? WHERE id=?',
               (generate_password_hash(new, method=HASH_METHOD), user['id']))
    db.execute('DELETE FROM sessions WHERE user_id=?', (user['id'],))  # 所有设备重新登录
    db.commit()
    return jsonify(ok=True, message='密码已重置，请用新密码登录')


@bp.post('/api/auth/change-password')
@auth_required()
def change_password():
    """已登录：手机验证码 + 新密码（等同重置密码，不再使用原密码）。"""
    d = request.get_json(force=True, silent=True) or {}
    code = (d.get('code') or '').strip()
    new = d.get('new_password') or ''
    if not code:
        return jsonify(error='请输入短信验证码'), 400
    if len(new) < 6:
        return jsonify(error='新密码至少 6 位'), 400
    db = get_db()
    ok, err = _check_code(db, g.user['phone'], 'change', code)
    if not ok:
        return jsonify(error=err), 400
    db.execute('UPDATE users SET password_hash=? WHERE id=?',
               (generate_password_hash(new, method=HASH_METHOD), g.user['id']))
    db.execute('DELETE FROM sessions WHERE user_id=? AND token!=?', (g.user['id'], g.token))
    db.commit()
    return jsonify(ok=True, message='密码已修改')

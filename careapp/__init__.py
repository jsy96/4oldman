"""颐养通 —— 居家养老服务管理平台 应用工厂。"""
import os

from flask import Flask, jsonify, request, send_from_directory

from .db import BASE, close_db, init_db, load_config

WEB_DIR = os.path.join(BASE, 'web')

APP_VERSION = 'v1.0.261020-26'


def create_app():
    app = Flask(__name__, static_folder=None)
    app.config['APP_CONF'] = load_config()
    app.json.ensure_ascii = False
    if os.environ.get('CARE_DEBUG'):
        app.config['PROPAGATE_EXCEPTIONS'] = True  # 云上排障：异常堆栈随响应抛出

    # 云上部署：数据库暂时连不上也先监听端口（否则 HTTP 云函数健康检查失败），
    # 后台每 20 秒重试，错误堆栈进平台日志便于定位
    try:
        init_db(app)
    except Exception:
        import threading
        import time
        import traceback
        traceback.print_exc()

        def _retry():
            while True:
                time.sleep(20)
                try:
                    init_db(app)
                    print('[db] 重试连接成功，已建表')
                    return
                except Exception:
                    traceback.print_exc()
        threading.Thread(target=_retry, daemon=True).start()

    app.teardown_appcontext(close_db)

    from .auth import bp as auth_bp
    from .api_customer import bp as customer_bp
    from .api_worker import bp as worker_bp
    from .api_admin import bp as admin_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(customer_bp)
    app.register_blueprint(worker_bp)
    app.register_blueprint(admin_bp)

    @app.get('/api/meta')
    def meta():
        conf = app.config['APP_CONF']
        return jsonify(version=APP_VERSION, app_name=conf['app_name'], app_sub=conf['app_sub'],
                       map=conf['map'], lunch=conf['lunch'], work_hours=conf['work_hours'],
                       schedule_buffer_min=conf.get('schedule_buffer_min', 10),
                       conflict_buffer_min=conf.get('conflict_buffer_min', 30))

    @app.get('/api/health')
    def health():
        """数据库连通性诊断：ok=true 表示建表与登录均可用。"""
        try:
            from .db import get_db
            n = get_db().execute('SELECT COUNT(*) AS c FROM users').fetchone()['c']
            return jsonify(ok=True, users=n)
        except Exception as e:
            return jsonify(ok=False, error=f'{type(e).__name__}: {e}'[:400]), 500

    @app.get('/')
    def index():
        # 云端挂在路由前缀下时（如 /eldercare），注入 <base> 让相对路径的 JS/CSS/API 走对
        prefix = request.environ.get('SCRIPT_NAME', '')
        with open(os.path.join(WEB_DIR, 'index.html'), encoding='utf-8') as f:
            html = f.read()
        if prefix and prefix != '/':
            html = html.replace('<head>', f'<head>\n<base href="{prefix}/">', 1)
        return html

    @app.get('/<path:p>')
    def assets(p):
        resp = send_from_directory(WEB_DIR, p)
        if request.args.get('v'):
            # 带版本号的资源：浏览器/CDN 长期缓存，发版换版本号即自动失效
            resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        else:
            resp.headers['Cache-Control'] = 'no-cache'
        return resp

    return app

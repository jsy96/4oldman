"""颐养通 —— 居家养老服务管理平台 应用工厂。"""
import os

from flask import Flask, jsonify, send_from_directory

from .db import BASE, close_db, init_db, load_config

WEB_DIR = os.path.join(BASE, 'web')

APP_VERSION = 'v1.0.261020-4'


def create_app():
    app = Flask(__name__, static_folder=None)
    app.config['APP_CONF'] = load_config()
    app.json.ensure_ascii = False

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
                       map=conf['map'], lunch=conf['lunch'], work_hours=conf['work_hours'])

    @app.get('/')
    def index():
        return send_from_directory(WEB_DIR, 'index.html')

    @app.get('/<path:p>')
    def assets(p):
        return send_from_directory(WEB_DIR, p)

    return app

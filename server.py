"""颐养通服务入口：python server.py（默认 http://127.0.0.1:8000）。

本地运行：python server.py / start.bat
腾讯云函数 Web 函数：PORT 环境变量由平台注入，自动适配，无需改动。
"""
import os
import threading
import webbrowser

from careapp import create_app
from careapp.db import database_url, db_kind

app = create_app()

if __name__ == '__main__':
    conf = app.config['APP_CONF']
    # SCF Web 函数注入 PORT；本地用 CARE_PORT/config；open_browser 仅本地
    port = int(os.environ.get('PORT') or os.environ.get('CARE_PORT') or conf.get('port', 8000))
    on_scf = bool(os.environ.get('PORT'))
    print(f'ElderCare server on port {port} | database: {db_kind() or "sqlite"}'
          f'{"" if db_kind() == "sqlite" else " (cloud)"}')
    if conf.get('open_browser') and not on_scf and not os.environ.get('CARE_NO_BROWSER'):
        threading.Timer(1.5, lambda: webbrowser.open(f'http://127.0.0.1:{port}')).start()
    app.run(host='0.0.0.0', port=port, threaded=not on_scf)

"""颐养通服务入口：python server.py（默认 http://127.0.0.1:8000）。

本地运行：python server.py / start.bat
云端（HTTP 云函数/云托管）：scf_bootstrap 或 Dockerfile 调起，监听 config.json 的 port。
"""
import os
import threading
import webbrowser

from careapp import create_app
from careapp.db import database_url, db_kind

app = create_app()

if __name__ == '__main__':
    conf = app.config['APP_CONF']
    # 监听端口：本地可用 CARE_PORT 覆盖；云上以 config.json 的 port 为准（与控制台「监听端口」一致）
    port = int(os.environ.get('CARE_PORT') or conf.get('port', 8000))
    on_cloud = bool(os.environ.get('TENCENTCLOUD_RUNENV') or os.environ.get('TCB_LOG'))
    print(f'ElderCare server on port {port} | database: {db_kind() or "sqlite"}', flush=True)
    if conf.get('open_browser') and not on_cloud and not os.environ.get('CARE_NO_BROWSER'):
        threading.Timer(1.5, lambda: webbrowser.open(f'http://127.0.0.1:{port}')).start()
    app.run(host='0.0.0.0', port=port, threaded=True)

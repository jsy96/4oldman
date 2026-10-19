"""颐养通服务入口：python server.py（默认 http://127.0.0.1:8000）。"""
import os
import threading
import webbrowser

from careapp import create_app

app = create_app()

if __name__ == '__main__':
    conf = app.config['APP_CONF']
    port = int(os.environ.get('CARE_PORT', conf.get('port', 8000)))
    if conf.get('open_browser') and not os.environ.get('CARE_NO_BROWSER'):
        threading.Timer(1.5, lambda: webbrowser.open(f'http://127.0.0.1:{port}')).start()
    print(f'ElderCare server running at http://127.0.0.1:{port} (LAN: http://0.0.0.0:{port})')
    app.run(host='0.0.0.0', port=port, threaded=True)

"""腾讯云开发 TCB 云函数入口：把「HTTP 访问/云接入」事件转成 WSGI 交给 Flask。

部署（函数入口配置）：index.main_handler
若云接入路径不是根路径（如 /eldercare），在函数环境变量加 STRIP_PREFIX=/eldercace。
"""
import base64
import io
import os
import sys
from urllib.parse import urlencode

from careapp import create_app

_flask = None


def _app():
    global _flask
    if _flask is None:
        _flask = create_app()
    return _flask


_KNOWN = ('/api', '/css', '/js', '/vendor', '/img')  # 应用真实路由前缀


def _strip(path):
    """优先用 STRIP_PREFIX；否则自动剥掉路径第一段（HTTP 云函数 URL 里的函数名前缀）。"""
    prefix = os.environ.get('STRIP_PREFIX', '')
    if prefix and path.startswith(prefix):
        return path[len(prefix):] or '/'
    if path == '/' or any(path == k or path.startswith(k + '/') for k in _KNOWN):
        return path
    seg = path.split('/', 2)  # /eldercare/api/meta → ['', 'eldercare', 'api/meta']
    return '/' + (seg[2] if len(seg) > 2 else '')


def main_handler(event, context):
    if not isinstance(event, dict) or ('httpMethod' not in event and 'path' not in event):
        return {'code': 1, 'msg': '请在控制台为该函数开启 HTTP 访问（云接入）后用网址调用'}

    method = (event.get('httpMethod') or 'GET').upper()
    path = _strip(event.get('path') or '/')
    qs = event.get('queryStringParameters') or event.get('queryString') or {}
    query_string = urlencode(qs, doseq=True) if isinstance(qs, dict) else str(qs)
    headers = {str(k).lower(): str(v) for k, v in (event.get('headers') or {}).items()}

    body = event.get('body') or ''
    if event.get('isBase64Encoded'):
        try:
            body = base64.b64decode(body)
        except Exception:
            body = b''
    if isinstance(body, str):
        body = body.encode('utf-8', 'replace')

    environ = {
        'REQUEST_METHOD': method,
        'SCRIPT_NAME': '',
        'PATH_INFO': path,
        'QUERY_STRING': query_string,
        'SERVER_NAME': headers.get('host', 'tcb'),
        'SERVER_PORT': headers.get('x-forwarded-port', '443'),
        'SERVER_PROTOCOL': 'HTTP/1.1',
        'wsgi.version': (1, 0),
        'wsgi.url_scheme': headers.get('x-forwarded-proto', 'https'),
        'wsgi.input': io.BytesIO(body),
        'wsgi.errors': sys.stderr,
        'wsgi.multithread': True,
        'wsgi.multiprocess': False,
        'wsgi.run_once': False,
        'CONTENT_LENGTH': str(len(body)),
    }
    for k, v in headers.items():
        if k == 'content-type':
            environ['CONTENT_TYPE'] = v
        elif k == 'content-length':
            environ['CONTENT_LENGTH'] = v or str(len(body))
        else:
            environ['HTTP_' + k.upper().replace('-', '_')] = v

    holder = {}

    def start_response(status, response_headers, exc_info=None):
        holder['status'] = status
        holder['headers'] = response_headers

    chunks = _app()(environ, start_response)
    try:
        out = b''.join(chunks)
    finally:
        if hasattr(chunks, 'close'):
            chunks.close()

    return {
        'isBase64Encoded': True,
        'statusCode': int(holder['status'].split()[0]),
        'headers': {k: v for k, v in holder['headers']},
        'body': base64.b64encode(out).decode(),
    }

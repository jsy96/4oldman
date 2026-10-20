"""打包云开发「云托管」部署 zip（代码 + Dockerfile，依赖在云端构建时安装）。

用法：
  1. 先在 secrets.json 填好 database_url（mysql://账号:密码@172.17.0.6:3306/ajmj-xxx）
  2. .venv/Scripts/python.exe pack_run.py   → 生成 cloudbase_run.zip
  3. 云开发环境控制台 → 云托管 → 新建服务 → 本地上传该 zip（监听端口 8000）
"""
import os
import zipfile

BASE = os.path.dirname(os.path.abspath(__file__))
ZIP = os.path.join(BASE, 'cloudbase_run.zip')
INCLUDE = ['Dockerfile', 'careapp', 'web', 'server.py', 'config.json',
           'requirements.txt', 'secrets.json']


def main():
    # 防呆：账号密码还是占位符就打包，容器会起不来
    import json
    secrets_path = os.path.join(BASE, 'secrets.json')
    if os.path.exists(secrets_path):
        with open(secrets_path, encoding='utf-8') as f:
            url = (json.load(f).get('database_url') or '')
        if '[' in url:
            raise SystemExit('[中止] secrets.json 的 database_url 还是占位符 [DB-USERNAME]/[DB-PASSWORD]，'
                             '请先填真实账号密码再打包。')
    if os.path.exists(ZIP):
        os.remove(ZIP)
    included = []
    with zipfile.ZipFile(ZIP, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in INCLUDE:
            src = os.path.join(BASE, name)
            if not os.path.exists(src):
                if name == 'secrets.json':
                    print('[提示] 没有 secrets.json：部署后需在云托管服务设置里配 '
                          'DATABASE_URL / AMAP_KEY 环境变量')
                continue
            if os.path.isdir(src):
                for root, _, files in os.walk(src):
                    for f in files:
                        if f.endswith(('.pyc', '.db')):
                            continue
                        full = os.path.join(root, f)
                        z.write(full, os.path.relpath(full, BASE))
            else:
                z.write(src, name)
            included.append(name)
    print(f'完成：{ZIP}（{os.path.getsize(ZIP) / 1024:.0f} KB）')
    print('包含：', ', '.join(included))
    print('→ 云开发控制台 → 云托管 → 新建服务 → 代码本地上传，监听端口 8000')


if __name__ == '__main__':
    main()

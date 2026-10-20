"""打包云开发「云函数」部署 zip（入口 index.main_handler + Linux x86_64 依赖）。

用法：
  .venv/Scripts/python.exe pack_fn.py
产出 cloudbase_fn.zip，云开发控制台 → 云函数 → 新建函数（Python3.9）→
函数代码 → 本地上传 zip → 入口 index.main_handler → 内存256MB/超时60秒 →
开启 HTTP 访问（云接入）。
"""
import os
import shutil
import subprocess
import sys
import zipfile

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(BASE, 'build_fn')
ZIP = os.path.join(BASE, 'cloudbase_fn.zip')
INCLUDE = ['index.py', 'careapp', 'web', 'server.py', 'config.json',
           'requirements.txt', 'secrets.json', 'scf_bootstrap']


def main():
    if os.path.exists(BUILD):
        shutil.rmtree(BUILD)
    os.makedirs(BUILD)

    for name in INCLUDE:
        src = os.path.join(BASE, name)
        if not os.path.exists(src):
            if name == 'secrets.json':
                print('[提示] 没有 secrets.json：需在函数环境变量配 DATABASE_URL / AMAP_KEY')
            continue
        dst = os.path.join(BUILD, name)
        shutil.copytree(src, dst) if os.path.isdir(src) else shutil.copy2(src, dst)

    uv = shutil.which('uv') or r'C:\ProgramData\chocolatey\bin\uv.exe'
    cmd = [uv, 'pip', 'install', '--target', BUILD,
           '--python-version', '3.9', '--python-platform', 'x86_64-unknown-linux-gnu',
           '-r', os.path.join(BASE, 'requirements.txt')]
    print('安装 Linux 依赖 ...')
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr)
        sys.exit('[错误] uv 交叉安装依赖失败')

    if os.path.exists(ZIP):
        os.remove(ZIP)
    with zipfile.ZipFile(ZIP, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(BUILD):
            for f in files:
                if f.endswith(('.pyc', '.db')):
                    continue
                full = os.path.join(root, f)
                arc = os.path.relpath(full, BUILD)
                if f == 'scf_bootstrap':
                    # 平台要求可执行权限；并强制 LF 行尾（Windows 的 CRLF 会导致 bash 报错）
                    data = open(full, 'rb').read().replace(b'\r\n', b'\n')
                    zi = zipfile.ZipInfo('scf_bootstrap')
                    zi.external_attr = 0o100755 << 16
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    z.writestr(zi, data)
                else:
                    z.write(full, arc)
    print(f'完成：{ZIP}（{os.path.getsize(ZIP) / 1024:.0f} KB）')
    print('→ 云开发 → 云函数 → 新建（Python3.9，空白函数）→ 代码页上传本 zip')
    print('→ 入口 index.main_handler，内存 256MB，超时 60 秒')
    print('→ 开启 HTTP 访问（云接入），路径尽量填 /；不行则函数加环境变量 STRIP_PREFIX=/路径')


if __name__ == '__main__':
    main()

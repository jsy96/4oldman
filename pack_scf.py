"""打包腾讯云函数 SCF Web 函数部署 zip（代码 + Linux x86_64 依赖）。

用法（本机执行）：
  .venv/Scripts/python.exe pack_scf.py
产出 scf_bundle.zip 后：
  1. 腾讯云控制台 → 云函数 SCF → 新建 → Web 函数，上传该 zip
  2. 启动命令：python server.py（平台注入 PORT，自动监听）
  3. 环境变量配置：DATABASE_URL（mysql://… 腾讯云MySQL 内网地址）、AMAP_KEY
"""
import os
import shutil
import subprocess
import sys
import zipfile

BASE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(BASE, 'build_scf')
ZIP = os.path.join(BASE, 'scf_bundle.zip')

INCLUDE = ['careapp', 'web', 'server.py', 'config.json', 'requirements.txt',
           'secrets.json', 'secrets.example.json']


def main():
    if os.path.exists(BUILD):
        shutil.rmtree(BUILD)
    os.makedirs(os.path.join(BUILD, 'deps'))

    for name in INCLUDE:
        src = os.path.join(BASE, name)
        if os.path.exists(src):
            dst = os.path.join(BUILD, name)
            shutil.copytree(src, dst) if os.path.isdir(src) else shutil.copy2(src, dst)
        elif name == 'secrets.json':
            print('[提示] 未找到 secrets.json：请改在函数环境变量里配 DATABASE_URL / AMAP_KEY')

    # 交叉安装 Linux x86_64 依赖（SCF 运行环境）
    uv = shutil.which('uv') or r'C:\ProgramData\chocolatey\bin\uv.exe'
    cmd = [uv, 'pip', 'install', '--target', os.path.join(BUILD, 'deps'),
           '--python-version', '3.9', '--python-platform', 'x86_64-unknown-linux-gnu',
           '-r', os.path.join(BASE, 'requirements.txt')]
    print('安装 Linux 依赖 ...')
    r = subprocess.run(cmd, capture_output=True, text=True, shell=False)
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr)
        sys.exit('[错误] uv 交叉安装依赖失败，请检查 uv 版本或手动安装依赖到 build_scf/deps')
    print(r.stdout.strip())

    if os.path.exists(ZIP):
        os.remove(ZIP)
    with zipfile.ZipFile(ZIP, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(BUILD):
            for f in files:
                full = os.path.join(root, f)
                z.write(full, os.path.relpath(full, BUILD))
    size = os.path.getsize(ZIP) / 1024
    print(f'\n完成：{ZIP}（{size:.0f} KB）')
    print('上传到腾讯云 SCF → Web 函数，启动命令：python server.py')


if __name__ == '__main__':
    main()

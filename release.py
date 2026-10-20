"""一条命令发布：打包部署到腾讯云 → 刷新 CDN → git 提交推送。

用法：
  deploy.bat "本次改动说明"              （推荐，双击或命令行）
  .venv/Scripts/python.exe release.py "本次改动说明"

说明：不带说明时用「发布 日期 时间」作为提交信息。
"""
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BASE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def run(args, check=True):
    print('> ' + ' '.join(args))
    rc = subprocess.run(args, cwd=BASE).returncode
    if check and rc != 0:
        sys.exit(f'[失败] 命令返回码 {rc}：{" ".join(args)}')
    return rc


def main():
    msg = ' '.join(sys.argv[1:]).strip() or f'发布 {time.strftime("%Y-%m-%d %H:%M")}'

    # 1) 部署（脚本内部会打包、更新函数、建路由、刷新 CDN）
    run([PY, 'deploy_scf.py'])

    # 2) git 提交
    run(['git', 'add', '-A'])
    status = subprocess.run(['git', 'status', '--porcelain'], cwd=BASE,
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    if status.stdout.strip():
        run(['git', 'commit', '-m',
             f'{msg}\n\nCo-Authored-By: Claude Code <noreply@anthropic.com>'])
    else:
        print('没有代码改动，跳过提交')

    # 3) 推送（网络波动自动重试）
    for i in range(1, 11):
        rc = subprocess.run(['git', 'push'], cwd=BASE).returncode
        if rc == 0:
            print('✅ 已推送到 GitHub')
            return
        print(f'推送失败（第 {i} 次），10 秒后重试 ...')
        time.sleep(10)
    print('⚠ GitHub 推送未成功（网络问题），可稍后手动执行 git push')


if __name__ == '__main__':
    main()

"""全自动部署到腾讯云开发环境（HTTP 云函数），无需打开控制台。

用法：
  .venv/Scripts/python.exe deploy_scf.py            # 自动找环境（唯一环境时）
  .venv/Scripts/python.exe deploy_scf.py --env 环境ID  # 多环境时指定
  .venv/Scripts/python.exe deploy_scf.py --list     # 只列出你的环境

前提：secrets.json 已填 tencent_secret_id / tencent_secret_key
（控制台 → 右上角头像 → 访问管理 → API密钥管理 → 新建密钥）

自动完成：打包 → 查环境 → 在环境内创建/更新 HTTP 云函数（Python3.9, 256MB, 60s）
→ 建 API 触发器 → 打印访问网址。改代码后重跑即热更新。
"""
import argparse
import base64
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BASE = os.path.dirname(os.path.abspath(__file__))
REGIONS = ['ap-shanghai', 'ap-guangzhou', 'ap-beijing', 'ap-chengdu', 'ap-nanjing', 'ap-hongkong']


def load_secrets():
    with open(os.path.join(BASE, 'secrets.json'), encoding='utf-8') as f:
        return json.load(f)


def scf_region(r):
    return r if r.startswith('ap-') or r.startswith('na-') or r.startswith('eu-') else 'ap-' + r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--env', default='', help='云开发环境ID（多环境时指定）')
    ap.add_argument('--name', default='eldercare', help='函数名')
    ap.add_argument('--list', action='store_true', help='只列出环境')
    args = ap.parse_args()

    sec = load_secrets()
    sid, skey = sec.get('tencent_secret_id', ''), sec.get('tencent_secret_key', '')
    if not sid or not skey:
        sys.exit('[缺配置] secrets.json 的 tencent_secret_id / tencent_secret_key 还没填。\n'
                 '获取：控制台 → 右上角头像 → 访问管理 → API密钥管理 → 新建密钥 → 填入 secrets.json（别发聊天）')

    from tencentcloud.common import credential
    from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
    from tencentcloud.tcb.v20180608 import tcb_client, models as tcbm
    from tencentcloud.scf.v20180416 import scf_client, models as scfm

    cred = credential.Credential(sid, skey)

    # 1. 查环境
    envs = []
    for region in REGIONS:
        try:
            c = tcb_client.TcbClient(cred, region)
            req = tcbm.DescribeEnvsRequest()
            req.Limit = 100
            resp = c.DescribeEnvs(req)
            for e in resp.EnvList or []:
                envs.append(dict(id=e.EnvId, alias=e.Alias, region=e.Region or region,
                                 status=e.Status, package=e.PackageName))
        except TencentCloudSDKException as e:
            if 'UnauthorizedOperation' not in e.code:
                pass  # 无环境的地域忽略
    if not envs:
        sys.exit('没找到任何云开发环境：请确认密钥正确、账号下确实有云开发环境')
    print('找到环境：')
    for e in envs:
        print(f"  {e['id']}  ({e['alias']})  地域 {e['region']}  状态 {e['status']}")
    if args.list:
        return
    if args.env:
        env = next((e for e in envs if e['id'] == args.env), None)
        if not env:
            sys.exit(f'指定的环境 {args.env} 不存在（用 --list 查看）')
    elif len(envs) == 1:
        env = envs[0]
    else:
        cand = [e for e in envs if 'ajmj' in e['id'].lower()]
        if len(cand) == 1:
            env = cand[0]
            print(f"自动选择 ajmj 环境：{env['id']}")
        else:
            sys.exit('有多个环境，请用 --env 指定其一（上面已列出）')
    region = scf_region(env['region'])
    print(f'目标：环境 {env["id"]} @ {region}，函数 {args.name}')

    # 2. 打包
    sys.path.insert(0, BASE)
    import pack_fn
    pack_fn.main()
    code_b64 = base64.b64encode(open(os.path.join(BASE, 'cloudbase_fn.zip'), 'rb').read()).decode()

    # 3. 建函数或更新
    client = scf_client.ScfClient(cred, region)
    client.set_stream_logger(stream=sys.stderr, log_level='ERROR')

    def exists():
        try:
            req = scfm.GetFunctionRequest()
            req.FunctionName = args.name
            req.Namespace = env['id']
            client.GetFunction(req)
            return True
        except TencentCloudSDKException:
            return False

    if exists():
        print('函数已存在 → 更新代码与配置 ...')
        req = scfm.UpdateFunctionCodeRequest()
        req.FunctionName, req.Namespace, req.ZipFile = args.name, env['id'], code_b64
        client.UpdateFunctionCode(req)
        cfg = scfm.UpdateFunctionConfigurationRequest()
        cfg.FunctionName, cfg.Namespace = args.name, env['id']
        cfg.Timeout, cfg.MemorySize = 60, 256
        client.UpdateFunctionConfiguration(cfg)
    else:
        print('创建 HTTP 云函数 ...')
        req = scfm.CreateFunctionRequest()
        req.FunctionName = args.name
        req.Namespace = env['id']
        req.Type = 'HTTP'
        req.Runtime = 'Python3.9'
        req.Timeout = 60
        req.MemorySize = 256
        req.Code = scfm.Code(ZipFile=code_b64)
        try:
            client.CreateFunction(req)
        except TencentCloudSDKException as e:
            sys.exit(f'[创建失败] {e}\n若提示函数名已存在但查询不到（上次失败残留），'
                     f'去控制台删掉 {args.name} 再重跑本脚本。')
    print('函数代码已就位')

    # 4. 触发器（尽力而为）
    try:
        req = scfm.CreateTriggerRequest()
        req.FunctionName, req.Namespace = args.name, env['id']
        req.TriggerName, req.Type = 'http', 'apigw'
        req.TriggerDesc = json.dumps({
            'api': {'authRequired': 'FALSE', 'requestConfig': {'method': 'ANY'}},
            'service': {'path': '/' + args.name},
        })
        client.CreateTrigger(req)
        print('触发器创建成功')
    except TencentCloudSDKException as e:
        print(f'[触发器] 自动创建未成功（{e.message}），不影响函数；可稍后在控制台开启 HTTP 访问')

    print(f'''
完成！访问网址（其一可用）：
  https://{env['id']}.{region}.tcb.qcloud.la/{args.name}
  （或控制台 → 云函数 {args.name} → HTTP访问/云接入 里的地址）

首次访问约 3-10 秒（连库建表+演示数据），之后秒开。部署完用浏览器打开验证。''')


if __name__ == '__main__':
    main()

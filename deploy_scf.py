"""全自动部署到腾讯云开发环境（HTTP 云函数），无需打开控制台。

用法：
  .venv/Scripts/python.exe deploy_scf.py            # 自动找环境（唯一/ajmj环境时）
  .venv/Scripts/python.exe deploy_scf.py --env 环境ID
  .venv/Scripts/python.exe deploy_scf.py --list     # 只列出环境

前提：secrets.json 已填 tencent_secret_id / tencent_secret_key
SCF 接口采用 TC3-HMAC-SHA256 手工签名直调（不依赖 SDK 版本）。
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BASE = os.path.dirname(os.path.abspath(__file__))
REGIONS = ['ap-shanghai', 'ap-guangzhou', 'ap-beijing', 'ap-chengdu', 'ap-nanjing', 'ap-hongkong']
SCF_VERSION = '2018-04-16'


def load_secrets():
    with open(os.path.join(BASE, 'secrets.json'), encoding='utf-8') as f:
        return json.load(f)


def scf_region(r):
    return r if r.startswith(('ap-', 'na-', 'eu-')) else 'ap-' + r


def tc3_call(action, payload, sid, skey, region, service='scf', version=SCF_VERSION, host=None):
    """腾讯云 API TC3 签名直调。service: scf / tcb。"""
    host = host or (f'{service}.{region}.tencentcloudapi.com' if service == 'scf'
                    else 'tcb.tencentcloudapi.com')
    url = f'https://{host}'
    ts = int(time.time())
    date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d')
    body = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))

    ct = 'application/json; charset=utf-8'
    hashed_payload = hashlib.sha256(body.encode('utf-8')).hexdigest()
    canonical = (f'POST\n/\n\ncontent-type:{ct}\nhost:{host}\nx-tc-action:{action.lower()}\n\n'
                 f'content-type;host;x-tc-action\n{hashed_payload}')
    sts = (f'TC3-HMAC-SHA256\n{ts}\n{date}/{service}/tc3_request\n'
           + hashlib.sha256(canonical.encode('utf-8')).hexdigest())

    def hm(key, msg):
        return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()

    secret = hm(('TC3' + skey).encode('utf-8'), date)
    secret = hm(secret, service)
    secret = hm(secret, 'tc3_request')
    sign = hmac.new(secret, sts.encode('utf-8'), hashlib.sha256).hexdigest()
    auth = (f'TC3-HMAC-SHA256 Credential={sid}/{date}/{service}/tc3_request, '
            f'SignedHeaders=content-type;host;x-tc-action, Signature={sign}')

    r = requests.post(url, data=body.encode('utf-8'), headers={
        'Authorization': auth, 'Content-Type': ct, 'Host': host,
        'X-TC-Action': action, 'X-TC-Timestamp': str(ts),
        'X-TC-Version': version, 'X-TC-Region': region,
    }, timeout=120)
    resp = r.json().get('Response') or {}
    if resp.get('Error'):
        err = RuntimeError(f"{resp['Error'].get('Code')}: {resp['Error'].get('Message')}")
        err.code = resp['Error'].get('Code', '')
        raise err
    return resp


def list_envs(sid, skey):
    """借用 TCB SDK 查询环境（镜像里的 tcb 包够用）。"""
    from tencentcloud.common import credential
    from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
    from tencentcloud.tcb.v20180608 import tcb_client, models
    cred = credential.Credential(sid, skey)
    envs = []
    for region in REGIONS:
        try:
            req = models.DescribeEnvsRequest()
            req.Limit = 100
            for e in (tcb_client.TcbClient(cred, region).DescribeEnvs(req).EnvList or []):
                envs.append(dict(id=e.EnvId, alias=e.Alias, region=e.Region or region, status=e.Status))
        except TencentCloudSDKException:
            pass  # 无环境/无权限的地域忽略
    return envs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--env', default='', help='云开发环境ID')
    ap.add_argument('--name', default='eldercare', help='函数名')
    ap.add_argument('--list', action='store_true')
    args = ap.parse_args()

    sec = load_secrets()
    sid, skey = sec.get('tencent_secret_id', '').strip(), sec.get('tencent_secret_key', '').strip()
    if not sid or not skey:
        sys.exit('[缺配置] secrets.json 的 tencent_secret_id / tencent_secret_key 未填。')

    envs = list_envs(sid, skey)
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
            sys.exit(f'指定的环境 {args.env} 不存在（--list 查看）')
    elif len(envs) == 1:
        env = envs[0]
    else:
        cand = [e for e in envs if 'ajmj' in e['id'].lower()]
        if len(cand) == 1:
            env = cand[0]
            print(f"自动选择 ajmj 环境：{env['id']}")
        else:
            sys.exit('有多个环境，请用 --env 指定（见上面列表）')
    region = scf_region(env['region'])
    ns = env['id']
    print(f'目标：环境 {ns} @ {region}，函数 {args.name}')

    # 打包
    sys.path.insert(0, BASE)
    import pack_fn
    pack_fn.main()
    code_b64 = base64.b64encode(open(os.path.join(BASE, 'cloudbase_fn.zip'), 'rb').read()).decode()

    call = lambda action, payload: tc3_call(action, payload, sid, skey, region)

    def get_status():
        try:
            return call('GetFunction', {'FunctionName': args.name, 'Namespace': ns}).get('Status')
        except RuntimeError:
            return None

    # 4) TCB：创建 HTTP 访问服务路由（默认域名 + 路径 = 函数名）
    print('创建 HTTP 访问路由 ...')
    try:
        tc3_call('CreateHTTPServiceRoute', {
            'EnvId': ns,
            'Domain': {'DomainId': '', 'Domain': ''},
            'Path': '/' + args.name,
            'Name': args.name,
            'Methods': ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'HEAD'],
            'TargetList': [{'Type': 'scf', 'TargetName': args.name}],
        }, sid, skey, region, service='tcb', version='2018-06-08')
        print('路由创建成功')
    except RuntimeError as e:
        if 'exists' in str(e) or 'Exist' in str(e) or '已存在' in str(e):
            print('路由已存在，跳过')
        else:
            print(f'[路由] 未成功（{e}），可在控制台 HTTP 访问/云接入 手动添加路径 /{args.name}')
    status = get_status()
    if status:
        print(f'函数已存在（{status}）→ 删除重建 ...')
        call('DeleteFunction', {'FunctionName': args.name, 'Namespace': ns})
        for _ in range(12):
            time.sleep(5)
            if get_status() is None:
                break
        else:
            sys.exit('删除超时，请 1 分钟后重跑')

    # 云开发环境的函数必须走 TCB 接口创建：EnvId + Type=HTTP，且不能传 Stamp（实测矩阵验证）
    print('通过云开发接口创建 HTTP 云函数 ...')
    resp = tc3_call('CreateFunction', {
        'FunctionName': args.name, 'EnvId': ns,
        'Type': 'HTTP', 'Runtime': 'Python3.9',
        'Handler': 'index.main_handler', 'MemorySize': 256, 'Timeout': 60,
        'CodeSource': 'ZipFile', 'Code': {'ZipFile': code_b64},
    }, sid, skey, region, service='tcb', version='2018-06-08')
    if resp.get('SCFErrorCode'):
        sys.exit(f"[创建失败] {resp['SCFErrorCode']}: {resp['SCFErrorMsg']}")

    # 等待构建完成
    for i in range(20):
        time.sleep(5)
        st = get_status()
        print(f'  状态：{st}')
        if st == 'Active':
            break
        if st and 'Failed' in st:
            sys.exit(f'构建失败（{st}）：控制台 → 云函数 {args.name} → 日志 查看原因')
    else:
        print('  （等待超时，可稍后用 --list 或控制台查看状态）')
    print('函数已就位')

    print(f'''
完成！访问网址（其一可用）：
  https://{ns}.{region}.tcb.qcloud.la/{args.name}

首次访问 3-10 秒（连库建表+演示数据），之后秒开。''')


if __name__ == '__main__':
    main()

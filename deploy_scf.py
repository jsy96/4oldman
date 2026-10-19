"""一键部署到腾讯云函数 SCF（Web 函数），本机直接调 API，无需控制台手点。

前提：
  1. 已运行 pack_scf.py 生成 scf_bundle.zip
  2. secrets.json 中已填：
       tencent_secret_id / tencent_secret_key  —— 访问管理→API密钥管理 创建
       database_url  —— mysql://账号:密码@内网IP:3306/库名（腾讯云 MySQL）
       amap_key      —— 可选

用法：
  .venv/Scripts/python.exe deploy_scf.py --region ap-guangzhou \
      [--name eldercare] [--vpc-id vpc-xxx --subnet-id subnet-xxx] [--update-only]

流程：函数不存在则创建（含环境变量/VPC/超时/内存），已存在则更新代码与配置；
最后尝试自动创建 API 网关触发器并打印访问 URL（失败则给出控制台手动路径）。
"""
import argparse
import base64
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE = os.path.dirname(os.path.abspath(__file__))
ZIP = os.path.join(BASE, 'scf_bundle.zip')


def load_secrets():
    with open(os.path.join(BASE, 'secrets.json'), encoding='utf-8') as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--region', required=True, help='地域，如 ap-guangzhou / ap-shanghai')
    ap.add_argument('--name', default='eldercare', help='函数名，默认 eldercare')
    ap.add_argument('--vpc-id', default='', help='与 MySQL 同 VPC 的 vpc-xxx（内网连库必填）')
    ap.add_argument('--subnet-id', default='', help='子网 subnet-xxx')
    ap.add_argument('--update-only', action='store_true', help='只更新代码与配置，不尝试建触发器')
    args = ap.parse_args()

    sec = load_secrets()
    sid, skey = sec.get('tencent_secret_id', ''), sec.get('tencent_secret_key', '')
    if not sid or not skey:
        sys.exit('[缺配置] 请在 secrets.json 填 tencent_secret_id / tencent_secret_key\n'
                 '获取：腾讯云控制台 → 右上角头像 → 访问管理 → API密钥管理 → 新建密钥')
    if not os.path.exists(ZIP):
        sys.exit('[缺文件] 请先运行: .venv/Scripts/python.exe pack_scf.py')

    from tencentcloud.common import credential
    from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
    from tencentcloud.scf.v20180416 import scf_client, models

    cred = credential.Credential(sid, skey)
    client = scf_client.ScfClient(cred, args.region)
    env_vars = [models.Variable(Key=k, Value=v) for k, v in {
        'DATABASE_URL': sec.get('database_url', ''),
        'AMAP_KEY': sec.get('amap_key', ''),
    }.items() if v]

    def exists():
        try:
            req = models.GetFunctionRequest()
            req.FunctionName = args.name
            client.GetFunction(req)
            return True
        except TencentCloudSDKException:
            return False

    if exists():
        print(f'函数 {args.name} 已存在 → 更新代码 ...')
        req = models.UpdateFunctionCodeRequest()
        req.FunctionName = args.name
        req.ZipFile = base64.b64encode(open(ZIP, 'rb').read()).decode()
        client.UpdateFunctionCode(req)
        cfg = models.UpdateFunctionConfigurationRequest()
        cfg.FunctionName = args.name
        cfg.Environment = models.Environment(Variables=env_vars)
        if args.vpc_id and args.subnet_id:
            cfg.VpcConfig = models.VpcConfig(VpcId=args.vpc_id, SubnetId=args.subnet_id)
        client.UpdateFunctionConfiguration(cfg)
        print('代码与配置已更新')
    else:
        print(f'创建函数 {args.name}（Web 函数, Python3.9）...')
        req = models.CreateFunctionRequest()
        req.FunctionName = args.name
        req.Type = 'HTTP'
        req.Runtime = 'Python3.9'
        req.Handler = 'server.app'
        req.Timeout = 60
        req.MemorySize = 256
        req.Code = models.Code(ZipFile=base64.b64encode(open(ZIP, 'rb').read()).decode())
        req.Environment = models.Environment(Variables=env_vars)
        if args.vpc_id and args.subnet_id:
            req.VpcConfig = models.VpcConfig(VpcId=args.vpc_id, SubnetId=args.subnet_id)
        try:
            client.CreateFunction(req)
        except TencentCloudSDKException as e:
            sys.exit(f'[创建失败] {e}\n'
                     '常见原因：Runtime 不支持（错误信息会列出可选值，改 deploy_scf.py 里 req.Runtime）、\n'
                     '地域无 Python3.9、或函数名已存在。')
        print('函数创建成功')

    if args.update_only:
        print('\n完成。请在控制台查看/测试函数。')
        return

    # 尽力自动创建 API 网关触发器（格式随平台版本可能有差异，失败不影响函数本身）
    try:
        req = models.CreateTriggerRequest()
        req.FunctionName = args.name
        req.TriggerName = 'http'
        req.Type = 'apigw'
        req.TriggerDesc = json.dumps({
            'api': {'authRequired': 'FALSE', 'requestConfig': {'method': 'ANY'},
                    'isIntegratedResponse': 'FALSE'},
            'service': {'path': '/'},
        })
        resp = client.CreateTrigger(req)
        print('触发器创建成功：', getattr(resp, 'TriggerInfo', None))
    except TencentCloudSDKException as e:
        print(f'[触发器] 自动创建未成功（{e.message}）。\n'
              f'→ 控制台：云函数 {args.name} → 触发管理 → 创建触发器（API网关，免鉴权，路径 /）')

    print('\n最后一步：打开函数的 API 网关 URL 即可访问（首次冷启动 2-5 秒）。')


if __name__ == '__main__':
    main()

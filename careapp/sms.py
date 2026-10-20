"""腾讯云短信验证码发送。

配置（secrets.json，均不入 git）：
  "sms_sdk_app_id": "1400xxxxxx",
  "sms_sign_name": "你的短信签名",
  "sms_template_id": "1234567",
模板参数顺序需为：{1}=验证码，{2}=有效分钟数。

未配置时：
  - 设置环境变量 CARE_SMS_DEBUG=1 → 验证码打印到服务日志并以 debug 模式返回（仅本地联调）
  - 否则抛 SmsNotConfigured，接口提示未配置
"""
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone

import requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class SmsNotConfigured(Exception):
    pass


def _secrets():
    try:
        with open(os.path.join(BASE, 'secrets.json'), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _cfg():
    sec = _secrets()
    return dict(
        app_id=(os.environ.get('SMS_SDK_APP_ID') or sec.get('sms_sdk_app_id') or '').strip(),
        sign=(os.environ.get('SMS_SIGN_NAME') or sec.get('sms_sign_name') or '').strip(),
        template=(os.environ.get('SMS_TEMPLATE_ID') or sec.get('sms_template_id') or '').strip(),
        secret_id=(os.environ.get('TENCENT_SECRET_ID') or sec.get('tencent_secret_id') or '').strip(),
        secret_key=(os.environ.get('TENCENT_SECRET_KEY') or sec.get('tencent_secret_key') or '').strip(),
    )


def _tc3_post(action, payload, secret_id, secret_key, host='sms.tencentcloudapi.com',
              service='sms', version='2021-01-11', region='ap-guangzhou'):
    ts = int(time.time())
    date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d')
    body = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    ct = 'application/json; charset=utf-8'
    hashed = hashlib.sha256(body.encode('utf-8')).hexdigest()
    canonical = (f'POST\n/\n\ncontent-type:{ct}\nhost:{host}\nx-tc-action:{action.lower()}\n\n'
                 f'content-type;host;x-tc-action\n{hashed}')
    sts = (f'TC3-HMAC-SHA256\n{ts}\n{date}/{service}/tc3_request\n'
           + hashlib.sha256(canonical.encode('utf-8')).hexdigest())

    def hm(key, msg):
        return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()

    secret = hm(('TC3' + secret_key).encode('utf-8'), date)
    secret = hm(secret, service)
    secret = hm(secret, 'tc3_request')
    sign = hmac.new(secret, sts.encode('utf-8'), hashlib.sha256).hexdigest()
    auth = (f'TC3-HMAC-SHA256 Credential={secret_id}/{date}/{service}/tc3_request, '
            f'SignedHeaders=content-type;host;x-tc-action, Signature={sign}')
    r = requests.post(f'https://{host}', data=body.encode('utf-8'), headers={
        'Authorization': auth, 'Content-Type': ct, 'Host': host,
        'X-TC-Action': action, 'X-TC-Timestamp': str(ts),
        'X-TC-Version': version, 'X-TC-Region': region,
    }, timeout=10)
    resp = r.json().get('Response') or {}
    if resp.get('Error'):
        raise RuntimeError(f"{resp['Error'].get('Code')}: {resp['Error'].get('Message')}")
    return resp


def send_verification_code(phone, code, minutes=5):
    """发送验证码。返回 'sent' 或 'debug'（本地调试模式）。"""
    cfg = _cfg()
    if not (cfg['app_id'] and cfg['sign'] and cfg['template'] and
            cfg['secret_id'] and cfg['secret_key']):
        if os.environ.get('CARE_SMS_DEBUG') == '1':
            print(f'[SMS-DEBUG] phone={phone} code={code} minutes={minutes}', flush=True)
            return 'debug'
        raise SmsNotConfigured('短信服务未配置：请在 secrets.json 填写 sms_sdk_app_id / '
                               'sms_sign_name / sms_template_id（并确保已创建审核通过的验证码模板）')
    phone = phone.strip()
    if not phone.startswith('+'):
        phone = '+86' + phone
    resp = _tc3_post('SendSms', {
        'PhoneNumberSet': [phone],
        'SmsSdkAppId': cfg['app_id'],
        'SignName': cfg['sign'],
        'TemplateId': cfg['template'],
        'TemplateParamSet': [str(code), str(minutes)],
    }, cfg['secret_id'], cfg['secret_key'])
    status = (resp.get('SendStatusSet') or [{}])[0]
    if status.get('Code') != 'Ok':
        raise RuntimeError(f"短信发送失败：{status.get('Code')} {status.get('Message')}")
    return 'sent'

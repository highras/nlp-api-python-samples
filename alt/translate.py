#!/usr/bin/env python
# -*- coding: utf-8 -*-

import datetime
import base64
import hmac
from hashlib import sha256 as sha256
from urllib import parse
from urllib.request import Request, urlopen


pid = 'YOUR_PID_GOES_HERE'
secret_key = b'YOUR_SECRETKEY_GOES_HERE'
endpoint_host = 'translate.ilivedata.com'
endpoint_path = '/api/v2/translate'
endpoint_url = 'https://translate.ilivedata.com/api/v2/translate'


def translate(source, target, sentence):
    now_date = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

    params = {
        'q': sentence,
        'source': source,
        'target': target,
        'timeStamp': now_date,
        'appId': pid
    }
    parameter = 'POST\n'
    parameter += endpoint_host + '\n'
    parameter += endpoint_path + '\n'
    for key in sorted(params.keys()):
        parameter += key + '=' + parse.quote(params.get(key), safe='') + '&'
    parameter = parameter[:-1]
    print(parameter)
    signature = base64.b64encode(
        hmac.new(secret_key, parameter.encode('utf-8'), digestmod=sha256).digest())
    return send(params, signature)


def send(params, signature):
    headers = {
        "Content-type": "application/x-www-form-urlencoded",
        "Authorization": signature
    }
    querystring = parse.urlencode(params)
    req = Request(endpoint_url, querystring.encode(
        'utf-8'), headers=headers, method='POST')
    return urlopen(req).read().decode()


if __name__ == '__main__':

    response = translate("en", "zh-CN", "Hello World!")
    print(response)

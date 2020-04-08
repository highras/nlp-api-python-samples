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
endpoint_host = 'profanity.ilivedata.com'
endpoint_path = '/api/v2/profanity'
endpoint_url = 'https://profanity.ilivedata.com/api/v2/profanity'


def profanity(sentence, classify, user_id, user_name):
    now_date = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

    params = {
        'q': sentence,
        'classify': str(classify),
        'userId': user_id,
        'userName': user_name,
        'timeStamp': now_date,
        'appId': pid
    }
    parameter = 'POST\n'
    parameter += endpoint_host + '\n'
    parameter += endpoint_path + '\n'
    for key in sorted(params.keys()):
        parameter += key + '=' + parse.quote(params.get(key)) + '&'
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
    response = profanity('我日你', 0, '12345678', '李四')
    print(response)
    response = profanity('加微13812123434', 1, '12345678', '李四')
    print(response)

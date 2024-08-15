#!/usr/bin/env python
# -*- coding: utf-8 -*-

import datetime
import base64
import hmac
from hashlib import sha256 as sha256
from urllib.request import Request, urlopen
import json


pid = 'YOUR_PID_GOES_HERE'
secret_key = b'YOUR_SECRETKEY_GOES_HERE'
endpoint_host = 'translate.ilivedata.com'
endpoint_path = '/api/v3/translate'
endpoint_url = 'https://translate.ilivedata.com/api/v3/translate'


def translate(target, sentence):
    now_date = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

    params = {
        'q': sentence,
        'target': target
    }

    query_body = json.dumps(params)
    print(query_body)
    parameter = "POST\n"
    parameter += endpoint_host + "\n"
    parameter += endpoint_path + '\n'
    parameter += sha256(query_body.encode('utf-8')).hexdigest() + "\n"
    parameter += "X-AppId:" + pid + "\n"
    parameter += "X-TimeStamp:" + now_date

    print(parameter)
    signature = base64.b64encode(
        hmac.new(secret_key, parameter.encode('utf-8'), digestmod=sha256).digest())
    print(signature)
    return send(query_body, signature, now_date)


def send(query_body, signature, now_date):
    headers = {
        "X-AppId": pid,
        "X-TimeStamp": now_date,
        "Content-type": "application/json",
        "Authorization": signature,
        "Host": endpoint_host,
        "Connection": "keep-alive"
    }

    req = Request(endpoint_url, query_body.encode(
        'utf-8'), headers=headers, method='POST')
    return urlopen(req).read().decode()


if __name__ == '__main__':

    response = translate("zh-CN", "Hello World!")
    print(response)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import datetime
import base64
import hmac
import json
from hashlib import sha256 as sha256
from urllib.request import Request, urlopen


pid = 'YOUR_PID_GOES_HERE'
secret_key = b'YOUR_SECRETKEY_GOES_HERE'
endpoint_host = 'asr.ilivedata.com'
endpoint_path = '/api/v1/speech/recognize/result'
endpoint_url = 'https://asr.ilivedata.com/api/v1/speech/recognize/result'


def get_result(task_id):
    now_date = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

    params = {
        "taskId": task_id
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


def send(querystring, signature, time_stamp):
    headers = {
        "X-AppId": pid,
        "X-TimeStamp": time_stamp,
        "Content-type": "application/json",
        "Authorization": signature,
        "Host": endpoint_host,
        "Connection": "keep-alive"
    }

    # querystring = parse.urlencode(params)
    req = Request(endpoint_url, querystring.encode(
        'utf-8'), headers=headers, method='POST')
    return urlopen(req).read().decode()


if __name__ == '__main__':

    taskId = "us_c20d0930-72e5-495f-8e60-9d3ef8001840_1614572260528"
    response = get_result(taskId)
    print(response)

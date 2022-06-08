#!/usr/bin/env python
# -*- coding: utf-8 -*-

import datetime
import base64
import hmac
import json
from hashlib import sha256 as sha256
from urllib.request import Request, urlopen
import requests

pid = 'YOUR_PID_GOES_HERE'
secret_key = b'YOUR_SECRETKEY_GOES_HERE'
endpoint_host = 'vsafe.ilivedata.com'
endpoint_path = '/api/v1/video/check/result'
endpoint_url = 'https://vsafe.ilivedata.com/api/v1/video/check/result'


def result(task_id):
    now_date = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

    params = {
        "taskId": task_id,
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
    return send(params, signature, now_date)



def send(querystring, signature, time_stamp):
    headers = {
        "X-AppId": pid,
        "X-TimeStamp": time_stamp,
        "Content-type": "application/json",
        "Authorization": signature,
        "Host": endpoint_host,
        "Connection": "keep-alive"
    }
    req = requests.post(endpoint_url,headers=headers,params=querystring)
    return req.json()



class A:
    def __init__(self,dic):
        for k,v in dic.items:
            setattr(self,k,v)

if __name__ == '__main__':
    task_id = "THE_TASK_ID_FROM_SUBMIT_API"

    response = result(task_id)
    obj = A(response)



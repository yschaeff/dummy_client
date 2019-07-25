#!/usr/bin/env python3

## sample randomness, 

import requests
import os, sys, argparse
import logging as log
import time
import json
from functools import partial

from collections import defaultdict
from random import gauss, randint
from math import pi, sin, sqrt
from time import time as now
import asyncio, pprint

SAMPLE_PERIOD = 1
MEASUREMENT_PERIOD = 5
SUBMIT_PERIOD = 10
SIN_PERIOD = 600
SIN_AMPLITUDE = 200
SIN_NOISE = 10

class Measurement():
    def __init__(self, duration):
        self.duration = duration
        self.channels = {}
    def add(self, channel):
        n, a, d = channel
        self.channels[n] = {"name": n, "average":a, "stddev":d}
    def __repr__(self):
        return f"{self.duration} {self.channels}"
    def serialize(self):
        return list(self.channels.values())

class Message():
    def __init__(self, dev_id, password, token):
        self.dev_id = dev_id
        self.password = password
        self.token = token
        self.measurement = defaultdict(partial(Measurement, MEASUREMENT_PERIOD*1000))
    def add(self, sample):
        t, n, a, d = sample
        mm = self.measurement[int(t)]
        mm.add((n,a,d))
    def __str__(self):
        return f"{self.dev_id} {self.password} {self.token} {self.measurement}"
    def serialize(self):
        l = []
        for t, mm in self.measurement.items():
            l.append({"timestamp":t, "duration":mm.duration, "channels":mm.serialize()})

        return {"device id": self.dev_id, "password": self.password,\
                "token":self.token, "measurement":l}

async def take_sample(samplequeue):
    OFFSET = randint(0, SIN_PERIOD)
    #every second
    while True:
        sample = (now()*2*pi)/SIN_PERIOD
        sample = gauss(sin(sample+OFFSET)*SIN_AMPLITUDE, SIN_NOISE)
        #print(f"push sample {sample}")
        await samplequeue.put(sample)
        await asyncio.sleep(SAMPLE_PERIOD)

def flush_queue(queue):
    r = []
    while not queue.empty():
        r.append(queue.get_nowait())
    print("Found {} samples".format(len(r)))
    return r

async def collect_measurement(channelname, measurementqueue):
    samplequeue = asyncio.Queue()
    asyncio.create_task(take_sample(samplequeue))
    while True:
        samples = flush_queue(samplequeue)
        if samples:
            s_cnt = len(samples)
            s_sum = sum(samples)
            s_avg = s_sum / s_cnt
            s_std = sqrt(sum([(s - s_avg)**2 for s in samples]) / s_cnt)
            measurement = (now(), channelname, s_avg, s_std)
            await measurementqueue.put(measurement)
        await asyncio.sleep(MEASUREMENT_PERIOD)

async def submitter(args, msgqueue):
    if args.no_ssl:
        HOST = f'http://{args.host}:{args.port}/API'
        VERIFY = None
    else:
        HOST = f'https://{args.host}:{args.port}/API'
        VERIFY = args.cert

    if args.no_auth:
        AUTH = None
    else:
        AUTH = (args.user,args.password)

    while True:
        msg = await msgqueue.get()
        js = json.dumps(msg.serialize(), indent=4)
        print(js)
        try:
            loop = asyncio.get_event_loop()
            future1 = loop.run_in_executor(None, partial(requests.post, HOST, data=msg.serialize(), verify=VERIFY, auth=AUTH))
            r = await future1
            #print(response1.text)

            #r = requests.post(HOST, data=msg.serialize(), verify=VERIFY, auth=AUTH)
        except requests.exceptions.ConnectionError as e:
            log.error(f'aborted by host {e}')
            continue
        log.debug(f"response: ({r.status_code}) {r.reason}")
        #if r.status_code != 200:
            #return 10

async def main(args):
    measurementqueue = asyncio.Queue()
    msgqueue = asyncio.Queue()
    asyncio.create_task(collect_measurement("current",   measurementqueue))
    asyncio.create_task(collect_measurement("voltage",   measurementqueue))
    asyncio.create_task(collect_measurement("frequency", measurementqueue))
    asyncio.create_task(submitter(args, msgqueue))
    ## todo every submit period collect all samples
    while True:
        await asyncio.sleep(SUBMIT_PERIOD)
        measurements = flush_queue(measurementqueue)
        if not measurements: continue
        msg = Message("00", "pw", "tok")
        for mm in measurements:
            msg.add(mm)
        await msgqueue.put(msg)

def parse_arguments():
    parser = argparse.ArgumentParser(description="Measurement relay agent", epilog="2019 - KapiteinLabs - yuri@kapiteinlabs.com")
    parser.add_argument("-l", "--log-level", help="Set loglevel",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        type=str.upper, action="store", default="INFO")
    parser.add_argument("-H", "--host", help="IP/hostname to submit to", action="store", type=str, default="localhost")
    parser.add_argument("-P", "--port", help="TCP port to submit to", action="store", type=int, default=80)
    #parser.add_argument("-d", "--device", help="Serial device to sample", action="store", type=str, default=DEFAULT_DEVICE)
    #parser.add_argument("-i", "--submission-interval", help="Interval in seconds between submissions", action="store", type=int, default=D_DEFAULT_SUBMISSION_INTERVAL)
    #parser.add_argument("-s", "--sample-interval", help="Interval in seconds between samples", action="store", type=int, default=D_DEFAULT_SAMPLE_INTERVAL)

    ## HTTP related
    parser.add_argument("-c", "--cert", help="Server certificate", action="store", type=str, default='cert.pem')
    parser.add_argument("-u", "--user", help="HTTP user", action="store", type=str, default='yuri')
    parser.add_argument("-p", "--password", help="HTTP password", action="store", type=str, default='pwd!')
    parser.add_argument("-n", "--no-ssl", help="Disable HTTPS", action="store_true")
    parser.add_argument("-N", "--no-auth", help="Disable HTTP authentication", action="store_true")
    return parser.parse_args()

def setup(args):
    level = getattr(log, args.log_level.upper())
    rootlogger = log.getLogger('')
    rootlogger.setLevel(level)

if __name__ == "__main__":
    log.basicConfig(level=log.INFO)
    args = parse_arguments()
    setup(args)
    asyncio.run(main(args))

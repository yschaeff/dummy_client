#!/usr/bin/env python3

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
import asyncio

D_DEFAULT_SAMPLE_INTERVAL = 1
D_DEFAULT_DOWNSAMPLE_INTERVAL = 10
D_DEFAULT_SUBMISSION_INTERVAL = 60
API = "/API/device/Log"

## parameters for mockup data
SIN_PERIOD = 1800 ## full sinusoid every half hour
SIN_AMPLITUDE = 200
SIN_NOISE = 10

class Measurement():
    def __init__(self, duration):
        self.duration = duration
        self.channels = {}
    def add(self, channel):
        n, a, d = channel
        self.channels[n] = {"name": n, "average":a, "stddev":d}
    def serialize(self):
        return list(self.channels.values())

class Message():
    def __init__(self, dev_id, password, period_ms):
        self.dev_id = dev_id
        self.password = password
        self.token = None
        self.measurement = defaultdict(partial(Measurement, period_ms))
    def add(self, sample):
        t, n, a, d = sample
        mm = self.measurement[int(t)]
        mm.add((n,a,d))
    def serialize(self):
        l = [{"timestamp":t, "duration":mm.duration, "channels":mm.serialize()}
            for t, mm in self.measurement.items()]
        #m = {"device_id": int(self.dev_id), "password": self.password, "measurement":l}
        m = {"device_id": self.dev_id, "password": self.password, "measurement":l}
        if self.token: m["token"] = self.token
        return m

async def take_sample(samplequeue):
    OFFSET = randint(0, SIN_PERIOD)
    while True:
        sample = (now()*2*pi)/SIN_PERIOD
        sample = gauss(sin(sample+OFFSET)*SIN_AMPLITUDE, SIN_NOISE)
        await samplequeue.put(sample)
        await asyncio.sleep(args.sample_interval)

def flush_queue(queue):
    r = []
    while not queue.empty():
        r.append(queue.get_nowait())
    log.debug("Found {} samples".format(len(r)))
    return r

async def collect_measurement(args, channelname, measurementqueue):
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
        await asyncio.sleep(args.downsample_interval)

async def submitter(args, msgqueue):
    TOKEN = None
    if args.no_ssl:
        HOST = f'http://{args.host}:{args.port}{API}'
        VERIFY = None
    else:
        HOST = f'https://{args.host}:{args.port}{API}'
        VERIFY = args.cert

    if args.no_auth:
        AUTH = None
    else:
        AUTH = (args.user, args.password)
    HEADERS = {'Content-type': 'application/json', 'Accept': 'application/json'}
    while True:
        msg = await msgqueue.get()
        msg.token = TOKEN
        log.info(json.dumps(msg.serialize(), indent=4))
        try:
            loop = asyncio.get_event_loop()
            future1 = loop.run_in_executor(None, partial(requests.post, HOST,
                data = json.dumps(msg.serialize()), headers=HEADERS, verify=VERIFY, auth=AUTH))
            r = await future1
        except requests.exceptions.ConnectionError as e:
            log.error(f'aborted by host {e}')
            continue
        log.info(f"response: ({r.status_code})\n\t{r.reason}\n\t{r.text}")
        if r.status_code == 401:
            log.error("Server denied access, clearing token")
            TOKEN = None
        elif r.status_code != 200:
            log.error("submission failed, purging measurement.")
            response = json.loads(r.text)
            if type(response) == str:
                log.error(f"{response} (no JSON!)")
            else:
                for key, value in response.items():
                    log.error(f"{key}: {value}")
        else:
            response = json.loads(r.text)
            for key, value in response.items():
                log.info(f"\t {key}: {value}")
            if "Data" in response:
                T = response["Data"]
                if T != TOKEN:
                    log.info("Token expired and updated")
                    TOKEN = T
                else:
                    log.debug("Token still the same")
            else:
                log.info("keeping old token")

        #TODO get new TOKEN

async def main(args):
    measurementqueue = asyncio.Queue()
    msgqueue = asyncio.Queue()
    asyncio.create_task(collect_measurement(args, "current",   measurementqueue))
    asyncio.create_task(collect_measurement(args, "potential",   measurementqueue))
    asyncio.create_task(collect_measurement(args, "frequency", measurementqueue))
    asyncio.create_task(submitter(args, msgqueue))
    while True:
        await asyncio.sleep(args.submission_interval)
        measurements = flush_queue(measurementqueue)
        if not measurements: continue
        msg = Message(args.user, args.password, args.downsample_interval*1000)
        for mm in measurements:
            msg.add(mm)
        await msgqueue.put(msg)

def parse_arguments():
    parser = argparse.ArgumentParser(description="Measurement relay agent", 
            epilog="2019 - KapiteinLabs - yuri@kapiteinlabs.com")
    parser.add_argument("-l", "--log-level", help="Set loglevel",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        type=str.upper, action="store", default="INFO")
    parser.add_argument("-H", "--host", help="IP/hostname to submit to",
            action="store", type=str, default="localhost")
    parser.add_argument("-P", "--port", help="TCP port to submit to",
            action="store", type=int, default=80)
    #parser.add_argument("-d", "--device", help="Serial device to sample",
        #action="store", type=str, default=DEFAULT_DEVICE)
    parser.add_argument("-i", "--submission-interval",
        help="Interval in seconds between submissions", action="store",
        type=int, default=D_DEFAULT_SUBMISSION_INTERVAL)
    parser.add_argument("-s", "--sample-interval",
        help="Interval in seconds between samples", action="store",
        type=int, default=D_DEFAULT_SAMPLE_INTERVAL)
    parser.add_argument("-d", "--downsample-interval",
        help="Aggragation period", action="store",
        type=int, default=D_DEFAULT_DOWNSAMPLE_INTERVAL)

    ## HTTP related
    parser.add_argument("-c", "--cert", help="Server certificate",
        action="store", type=str, default='cert.pem')
    parser.add_argument("-u", "--user", help="HTTP user", action="store",
        type=str, default='yuri')
    parser.add_argument("-p", "--password", help="HTTP password",
        action="store", type=str, default='pwd!')
    parser.add_argument("-n", "--no-ssl", help="Disable HTTPS",
        action="store_true")
    parser.add_argument("-N", "--no-auth", help="Disable HTTP authentication",
        action="store_true")
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

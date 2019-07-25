#!/bin/bash

NAME=$(hostname)

for i in {1..10}; do
    echo starting device$i
    python3 dummy_client.py --log-level debug --no-ssl --no-auth --host 85.214.92.70 --user device_$NAME_$i --password "super secret"  --submission-interval 30 --sample-interval 1 --downsample-interval 3 2> device_$NAME_$i.log &
    sleep 2
done

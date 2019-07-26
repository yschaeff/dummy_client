#!/bin/bash

for i in "$@"; do
    case $i in
        -h|--help)
            echo "Usage: ./start_many.sh [--help|-h] <START> <COUNT>"
            exit 0
        ;;
        -*)
            echo "invalid option '$i'. Call with --help"
            exit 1
        ;;
        *)
            [[ "$i" =~ ^[0-9]+$ ]] && continue
            echo "expect uint, got '$i'"
            exit 2
    esac
done

START=$1
COUNT=$2

NAME=$(hostname)
PIDS=()

for ((i=0; i<COUNT; i++)); do
    echo -n starting device_${NAME}_$i
    python3 dummy_client.py --log-level debug --no-ssl --no-auth --host 85.214.92.70 --user $i --password "password$i"  --submission-interval 30 --sample-interval 1 --downsample-interval 3 2> device_${NAME}_$i.log &
    PID=$!
    PIDS+="$PID "
    echo " (PID: $PID)"
    sleep 2
done

for i in $PIDS; do
    STATE=$(ps -q $i -o state --no-headers)
    if [ ! "$STATE" == "S" ]; then
        echo "WARNING. PID: $i, state: $STATE"
    fi
done

command=' '
while [ ! "$command" == 'k' ]; do
    echo -n "Enter 'k' to kill all instances\$ "
    read command
done

kill $PIDS
echo checking all pids...
sleep 1

for i in $PIDS; do
    STATE=$(ps -q $i -o state --no-headers)
    if [ $STATE ]; then
        echo "WARNING. Process $PID still running (state: $STATE)"
    fi
done
echo done.

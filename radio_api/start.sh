#!/usr/bin/env bash
# start.sh - This script is called by Colosseum to tell the radio the job is starting.
# No input is accepted.
# STDOUT and STDERR may be logged, but the exit status is always checked.
# The script should return 0 to signify successful execution.

# send "s" to /tmp/mypipe (a named pipe that the incumbent is monitoring)

echo "Beginning of batch job" > /logs/run.log
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
APP_DIR="/root/OAI-Colosseum"

source ${SCRIPT_DIR}/common.sh

if [ "$mode_type" == "core" ]; then
  route add -net 12.1.1.0/24 gw 192.168.70.134 dev demo-oai
fi

echo "[`date`] ${mode_type} start.sh" >> /logs/run.log

echo "[`date`] SCRIPT_DIR ${SCRIPT_DIR}" >> /logs/run.log
echo "[`date`] APP_DIR ${APP_DIR}" >> /logs/run.log

echo "[`date`] Starting 5G ${mode_type} applications" >> /logs/run.log
cd ${APP_DIR}
if [ "$mode_type" == "gnb" ]; then
  python3 ${APP_DIR}/${script_cmd} &
else
  python3 ${APP_DIR}/${script_cmd} >> /logs/run.log &
fi

exit 0
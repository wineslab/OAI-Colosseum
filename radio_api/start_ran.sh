#!/usr/bin/env bash
#Starts OAI RAN gNB or UE based on radio.conf

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
APP_DIR="/root/OAI-Colosseum"

source ${SCRIPT_DIR}/common.sh

echo "READY" > /tmp/NR_STATE

echo "[`date`] Starting 5G ${mode_type} service" >> /logs/run.log
echo "[`date`] Command line ${script_cmd}" >> /logs/run.log
cd ${APP_DIR}
python3 ${APP_DIR}/${script_cmd} >> /logs/run.log

exit 0

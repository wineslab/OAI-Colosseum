#!/usr/bin/env bash
# stop.sh - This script is called by Colosseum to tell the radio the job is ending.
# No input is accepted.
# STDOUT and STDERR may be logged, but the exit status is always checked.
# The script should return 0 to signify successful execution.

echo "STOPPING" > /tmp/NR_STATE

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"

source ${SCRIPT_DIR}/common.sh

echo "[`date`] ${mode_type} stop.sh" >> /logs/run.log

# copy radio.conf and colosseum_config.ini to /logs/
cp ${SCRIPT_DIR}/radio.conf /logs/
cp ${SCRIPT_DIR}/colosseum_config.ini /logs/

echo "[`date`] Copying logs" >> /logs/run.log
if [ "$mode_type" == "ue" ]; then
  systemctl stop oai_ran.service
  cp /root/iperf-ue-DL.log /logs/
  cp /root/iperf-ue-UL.log /logs/
  cp /root/OAI-Colosseum/iperf3_result* /logs/
  cp /root/last_log /logs/nr-ue.log
elif [ "$mode_type" == "gnb" ]; then
  systemctl stop oai_ran.service
  cp /root/last_log /logs/nr-gnb.log
elif [ "$mode_type" == "core" ]; then
  systemctl stop oai_5gc.service
  cp /root/iperf-core-server-ue-* /logs/
  docker logs oai-amf > /logs/amf.log
  docker logs oai-smf > /logs/smf.log
else
  echo "Invalid config file option ${mode_type}." >> /logs/run.log
  exit 1
fi

echo "FINISHED" > /tmp/NR_STATE

exit 0

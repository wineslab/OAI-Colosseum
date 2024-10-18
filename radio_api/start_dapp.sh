#!/bin/bash

DAPP_DIR="/root/spear-dApp"
echo "[`date`] Starting dApp" >> /logs/run.log
echo "[`date`] DAPP_DIR ${DAPP_DIR}" >> /logs/run.log

# create directory needed by dapp
mkdir -p /tmp/dapps

# start dapp
# python3 ${DAPP_DIR}/src/dapp/dapp.py --control --profile --time 2> /logs/dapp_error.log
python3 ${DAPP_DIR}/src/dapp/dapp.py ${dapp_args} 2> /logs/dapp_error.log


#!/usr/bin/env bash
# common.sh - This script host common code to other scripts in this directory.
# No input is accepted.
# STDOUT and STDERR may be logged, but the exit status is always checked.

config_file="${SCRIPT_DIR}/radio.conf"

echo "Scanning config file" >> /logs/run.log
# Check if the config file exists
if [ ! -f "$config_file" ]; then
    echo "Config file not found: $config_file"
    exit 1
fi

# Read the config file line by line
while IFS='=' read -r key value || [[ -n "$line" ]]; do
    # Ignore lines starting with '#' (comments) or empty lines
    if [[ ! "$key" =~ ^[[:space:]]*# && -n "$key" ]]; then
        # Trim whitespace from key and value
        key=$(echo "$key" | awk '{$1=$1};1')
        value=$(echo "$value" | awk '{$1=$1};1')

        # Store key and value in variables
        case "$key" in
            "mode_type") mode_type="$value" ;;
            "dl_iperf_rate") dl_iperf_rate="$value" ;;
            "ul_iperf_rate") ul_iperf_rate="$value" ;;
            "iperf_duration") iperf_duration="$value" ;;
            # Add more cases for other keys as needed
        esac
    fi
done < "$config_file"

script_cmd=""
if [ "$mode_type" == "gnb" ]; then
    script_cmd="ran.py -t donor -m sa"
elif [ "$mode_type" == "ue" ]; then
    script_cmd="auto-test.py -m ue -t ${iperf_duration} -D ${dl_iperf_rate} -U ${ul_iperf_rate}"
elif [ "$mode_type" == "core" ]; then
    script_cmd="auto-test.py -m core-nw"
else
    echo "Invalid config file option ${mode_type}." >> /logs/run.log
    exit 1
fi

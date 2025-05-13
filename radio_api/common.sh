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
            "iperf_protocol") iperf_protocol="$value" ;;
            "timing_advance") timing_advance="$value" ;;
            "near_rt_ric_ip") near_rt_ric_ip="$value" ;;
            "gnb_id") gnb_id="$value" ;;
            # Add more cases for other keys as needed
        esac
    fi
done < "$config_file"

script_cmd=""
if [ "$mode_type" == "gnb" ]; then
    if [ -z ${near_rt_ric_ip+x} ]; then
        script_cmd="auto-test.py -T gnb"
    else
        # check if ric ip is reachable or if we need to setup route to it
        ping -c 1 ${near_rt_ric_ip}
        if [ $? -ne 0 ]; then
          echo "Setting route to Near-RT RIC"
          first_three_ip_octects=$(ip addr show can0 | grep -oE 'inet [0-9\.]+/[0-9]+' | awk '{print $2}' | cut -d '/' -f 1 | awk -F'.' '{print $1"."$2"."$3}')
          route add ${near_rt_ric_ip}/32 gw ${first_three_ip_octects}.1 dev can0

          echo "Running RIC reachability tests"
          ping -c 3 ${near_rt_ric_ip} &> /logs/ric_reachability.log
          echo "" >> /logs/ric_reachability.log
          ncat -zv ${near_rt_ric_ip} --sctp 32224 &>> /logs/ric_reachability.log
        fi

        if [ -z ${gnb_id+x} ]; then
            script_cmd="auto-test.py -T gnb --near_rt_ric_ip ${near_rt_ric_ip}"
        else
            echo "Setting gNB ID to "${gnb_id}
            script_cmd="auto-test.py -T gnb --gnb_id ${gnb_id} --near_rt_ric_ip ${near_rt_ric_ip}"
        fi
    fi
    echo ${script_cmd}
elif [ "$mode_type" == "ue" ]; then
    script_cmd="auto-test.py -T ue -t ${iperf_duration} --iperf_protocol ${iperf_protocol} -D ${dl_iperf_rate} -U ${ul_iperf_rate}"
    if [ -z ${timing_advance+x} ]; then :; else script_cmd=${script_cmd}" --timing_advance ${timing_advance}"; fi
    echo ${script_cmd}
elif [ "$mode_type" == "core" ]; then
    script_cmd="auto-test.py -T core-nw"
else
    echo "Invalid config file option ${mode_type}." >> /logs/run.log
    exit 1
fi

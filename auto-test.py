import subprocess
import signal
import time
import re
import sys
import netifaces
import os
import argparse
from ran import Ran

def handle_sigint(sig, frame):
    print("Stopping the process...")
    sys.exit(0)

def tail(file_path, target_string, max_num_search):
    # Start at the end of the file
    with open(file_path, 'r') as file:
        file.seek(0)  # Go to the beginning of the file

        num_search = 0
        while num_search < max_num_search:
            # Read new lines if available
            new_lines = file.readlines()

            if new_lines:
                # Process the new lines
                for line in new_lines:
                    if re.search(target_string, line):
                        print(f"Found '{target_string}' in line: {line}")
                        return True

            curr_position = file.tell()  # Current file position

            # Check for new lines every 1 second
            time.sleep(3)
            file.seek(0, 2) # Go to last line
            if curr_position == file.tell():
                print("File not updated for more than 1 second")
                return False
            else:
                file.seek(curr_position)
            num_search += 1

    return False

def get_interface_ip(interface_prefix):
    interfaces = netifaces.interfaces()
    for interface in interfaces:
        if interface.startswith(interface_prefix):
            addresses = netifaces.ifaddresses(interface)
            if netifaces.AF_INET in addresses:
                ip_address = addresses[netifaces.AF_INET][0]['addr']
                return ip_address
    return None

def stop_and_kill_subp(process):
    print("Stopping UE")
    process.send_signal(signal.SIGINT)
    time.sleep(1)
    process.send_signal(signal.SIGINT)
    time.sleep(2)
    if process.poll() is None:
        print('Process still running despite sending SIGINT. Force killing.')
        process.send_signal(signal.SIGKILL)
    process.wait()

def run_and_check_conn_established(command_to_run):
    output_filename = '/root/last_log'
    output_file = open(output_filename, "w")
    status_file = '/tmp/NR_STATE'

    # Create a separate thread and run the UE in it
    ueProcess = subprocess.Popen(command_to_run, stdout=output_file, stderr=subprocess.STDOUT)

    time.sleep(5)

    # Perform scanning of logs and run iperf
    target_string = r'Starting sync detection'
    init_sync_started = tail(output_filename, target_string, 100)

    target_string = r'SIB1 decoded'
    sib1_decoded = tail(output_filename, target_string, 100)
    # Set status
    os.system(f'echo "ACTIVE" > {status_file}')

    target_string = r'Interface .* successfully configured, ip address'
    conn_established = tail(output_filename, target_string, 10)

    if not conn_established:
        # Scanning logs failed (maybe UE crashed?)
        stop_and_kill_subp(ueProcess);
        # Restart again
        time.sleep(5)
        print("Restarting UE")
        res, ueProcess = run_and_check_conn_established(command_to_run)

    return True, ueProcess

def start_core_iperf(imsi):
    current_directory = '/root'
    port = int('52'+imsi[-2:])
    print(f"Starting iperf server job for {imsi} in port {port}")
    output_filename = f'{current_directory}/iperf-core-server-ue-{imsi}.log'
    output_file = open(output_filename, "w")
    iperfSrvCmd = ['iperf3', '-s', '-p', f'{port}']
    try:
        iperfSrv = subprocess.Popen(iperfSrvCmd, stdout=output_file, stderr=subprocess.STDOUT)
    except Exception as e:
        print("Error starting server")
        return None

    return iperfSrv

def scan_docker_logs_and_do_stuff(service_name):
    command = f"docker logs {service_name} -f"  # Use `-f` flag for continuous log streaming
    dockerScanPocess = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    signal.signal(signal.SIGINT, handle_sigint)
    new_context = "SMF CONTEXT:"
    get_imsi = "SUPI:"
    dn_ip_address = '192.168.70.135'
    status_file = '/tmp/NR_STATE'
    server_jobs = []

    while True:
        # Read the new logs from the subprocess output
        new_logs = dockerScanPocess.stdout.readline().decode("utf-8")

        if new_logs:
            if new_context in new_logs:
                # Read next line
                new_logs = dockerScanPocess.stdout.readline().decode("utf-8")
                search_index = new_logs.index(get_imsi)

                # Extract the substring after the search string
                imsi = new_logs[search_index + len(get_imsi):].strip()
                print("Found new UE")
                print(imsi)
                # Set status
                os.system(f'echo "ACTIVE" > {status_file}')
                srvJ = start_core_iperf(imsi)
                server_jobs.append(srvJ)
            else:
                continue
        else:
            time.sleep(1)

        # Check if the subprocess has finished, indicating an error or termination
        if dockerScanPocess.poll() is not None:
            print("Scan process finished")
            break

    dockerScanPocess.terminate()
    for j in server_jobs:
        j.terminate()

def run_core_test():
    docker_image_to_scan = 'oai-smf'
    scan_docker_logs_and_do_stuff(docker_image_to_scan)

def run_UE_test(args):
    current_directory = '/root'
    args.mode = 'sa'
    args.type = 'ue'
    ue = Ran(args)
    ue.execute = False
    ue.run()
    print(ue.cmd_stored)
    conn_established, ueProcess = run_and_check_conn_established(ue.cmd_stored)

    if conn_established:
        interface_prefix = 'oaitun'
        ip_address = get_interface_ip(interface_prefix)
        dn_ip_address = '192.168.70.129'
        if ip_address:
            print(f"The IP address of interface {interface_prefix} is: {ip_address}")
            # default route
            add_route_cmd = "route add default gw 12.1.1.1"
            try:
                subprocess.run(add_route_cmd, shell=True, check=True)
                print("Default route added successfully.")
            except subprocess.CalledProcessError as e:
                print(f"Error adding default route: {e}")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")

            # DL iperf
            print("Starting DL iperf job")
            output_filename = f'{current_directory}/iperf-ue-DL.log'
            output_file = open(output_filename, "w")
            #iperfDLcmd = f'iperf3 -u --bind {ip_address} -b {args.dl_iperf_rate}M -c {dn_ip_address} -t {args.iperf_time} -p 52{ue.node_id[1:]} -R'.split()
            iperfDLcmd = f'python3 /root/sierra-wireless-automated-testing/src/iperf/iperf_run.py --type tcp --dir DL --save local --port 52{ue.node_id[1:]} --bind {ip_address}'.split()
            try:
                iperfDL = subprocess.Popen(iperfDLcmd, stdout=output_file, stderr=subprocess.STDOUT)
            except Exception as e:
                print("Error starting DL iperf job")
            iperfDL.wait()
            print("Finished iperf DL job")
            # UL iperf
            print("Starting UL client job")
            output_filename = f'{current_directory}/iperf-ue-UL.log'
            output_file = open(output_filename, "w")
            #iperfULcmd = f'iperf3 -u --bind {ip_address} -b {args.ul_iperf_rate}M -c {dn_ip_address} -t {args.iperf_time} -p 52{ue.node_id[1:]}'.split()
            iperfULcmd = f'python3 /root/sierra-wireless-automated-testing/src/iperf/iperf_run.py --type tcp --dir UL --save local --port 52{ue.node_id[1:]} --bind {ip_address}'.split()
            try:
                iperfUL = subprocess.Popen(iperfULcmd, stdout=output_file, stderr=subprocess.STDOUT)
            except Exception as e:
                print("Error starting UL iperf job")
            iperfUL.wait()
            print("Finished iperf UL job")
        else:
            print(f"No interface found with the prefix {interface_prefix}")
    else:
        stop_and_kill_ue(ueThread)

    # Issue kill signal to the UE
    stop_and_kill_subp(ueProcess)

def run_gnb_test(args):
    args.mode = 'sa'
    args.type = 'donor'
    gnb = Ran(args)
    gnb.execute = False
    gnb.run()
    print(gnb.cmd_stored)
    output_file = open('/root/last_log', "w")
    p = subprocess.Popen(gnb.cmd_stored, stdout=output_file, stderr=subprocess.STDOUT)
    while True:
        if p.poll() is not None:
            print("gNB process ended. Restarting it.")
            p = subprocess.Popen(gnb.cmd_stored, stdout=output_file, stderr=subprocess.STDOUT)
        time.sleep(5)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Parameters to run tests')
    parser.add_argument('-m', '--mode',
                        required=True,
                        choices=['gnb', 'ue', 'core-nw'])
    parser.add_argument('-t', '--iperf_time',
                        default=10,
                        type=int)
    parser.add_argument('-D', '--dl_iperf_rate',
                        default=10,
                        type=int)
    parser.add_argument('-U', '--ul_iperf_rate',
                        default=5,
                        type=int)
    parser.add_argument('-n', '--numerology',
                        default=1,
                        type=int,
                        choices=[0, 1, 2, 3, 4],
                        help='numerology for subcarrier spacing')
    parser.add_argument('-p', '--prb',
                        default=106,
                        type=int)
    parser.add_argument('-c', '--channel',
                        default=0,
                        type=int)
    parser.add_argument('--flash', '-f', default=False, action='store_true')
    args = parser.parse_args()
    args.f1_remote_node = '0.0.0.0'
    args.if_freq = 0
    args.numa = True
    args.gdb = False
    args.flash = False
    args.rfsim = False
    args.scope = False

    if args.mode == 'gnb':
        run_gnb_test(args)
    if args.mode == 'ue':
        run_UE_test(args)
    elif args.mode == 'core-nw':
        run_core_test()
    else:
        print("Unknown mode")

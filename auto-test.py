import subprocess
import threading
import signal
import time
import re
import sys
import netifaces
import os
import argparse
from ran import Ran as UE

def handle_sigint(sig, frame):
    print("Stopping the process...")
    sys.exit(0)

class CommandThread(threading.Thread):
    def __init__(self, command, working_directory):
        super(CommandThread, self).__init__()
        self.command = command
        self.working_directory = working_directory
        self.process = None

    def run(self):
        # Run the command
        self.process = subprocess.Popen(self.command, shell=True, cwd=self.working_directory, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.process.wait()

    def stop(self):
        # Send SIGINT signal to the subprocess
        self.process.send_signal(signal.SIGINT)

    def kill(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()

def tail(file_path, target_string):
    # Start at the end of the file
    with open(file_path, 'r') as file:
        file.seek(0)  # Go to the beginning of the file

        while True:
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

def stop_and_kill_ue(thread):
    print("Stopping UE")
    thread.stop()
    time.sleep(2)
    thread.kill()
    thread.join()

def run_and_check_conn_established(command_to_run):
    current_directory = "/root"
    output_filename = '/root/last_log'

    # Create a separate thread and run the UE in it
    thread = CommandThread(command_to_run, current_directory)
    thread.start()

    # Perform scanning of logs and run iperf
    time.sleep(5)

    target_string = r'Starting sync detection'
    init_sync_started = tail(output_filename, target_string)

    target_string = r'SIB1 decoded'
    sib1_decoded = tail(output_filename, target_string)

    target_string = r'Interface .* successfully configured, ip address'
    conn_established = tail(output_filename, target_string)

    if not conn_established:
        # Scanning logs failed (maybe UE crashed?)
        stop_and_kill_ue(thread);
        # Restart again
        res, thread = run_and_check_conn_established(command_to_run)

    return True, thread

def start_core_iperf(dn_ip_address, ip_address, iperf_time):
    current_directory = os.getcwd()
    print("Starting iperf server job")
    iperfSrvCmd = f'docker exec -it oai-ext-dn iperf -u -s -i 1 -B {dn_ip_address} -t {iperf_time} > {current_directory}/iperf-core-server.log'
    iperfSrvThd = CommandThread(iperfSrvCmd, current_directory)
    iperfSrvThd.start()

    print("Starting iperf client job")
    iperfClntCmd = f'docker exec -it oai-ext-dn iperf -u -i 1 -B {dn_ip_address} -b 30M -c {ip_address} -t {iperf_time} > {current_directory}/iperf-core-client.log'
    iperfClntThd = CommandThread(iperfClntCmd, current_directory)
    iperfClntThd.start()

def scan_docker_logs_and_do_stuff(service_name, iperf_time):
    command = f"docker logs {service_name} -f"  # Use `-f` flag for continuous log streaming
    dockerScanPocess = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    signal.signal(signal.SIGINT, handle_sigint)
    new_ue_string = "PAA, Ipv4 Address:"
    dn_ip_address = '192.168.70.135'

    while True:
        # Read the new logs from the subprocess output
        new_logs = dockerScanPocess.stdout.readline().decode("utf-8")

        if new_logs:
            if new_ue_string in new_logs:
                search_index = new_logs.index(new_ue_string)

                # Extract the substring after the search string
                ip_address = new_logs[search_index + len(new_ue_string):].strip()
                print("Found new UE")
                print(ip_address)
                start_core_iperf(dn_ip_address, ip_address, iperf_time)
            else:
                continue
        else:
            time.sleep(1)

        # Check if the subprocess has finished, indicating an error or termination
        if dockerScanPocess.poll() is not None:
            print("Scan process finished")
            break

    dockerScanPocess.terminate()

def run_core_test(iperf_time):
    current_directory = os.getcwd()
    docker_image_to_scan = 'oai-smf'
    scan_docker_logs_and_do_stuff(docker_image_to_scan, iperf_time)

def run_UE_test(args):
    current_directory = '/root'
    args.mode = 'sa'
    args.type = 'ue'
    ue = UE(args)
    ue.execute = False
    ue.run()
    conn_established, ueThread = run_and_check_conn_established(ue.cmd_stored)

    if conn_established:
        interface_prefix = 'oaitun'
        ip_address = get_interface_ip(interface_prefix)
        dn_ip_address = '192.168.70.135'
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
            # iperf 
            print("Starting iperf server job")
            iperfSrvCmd = f'iperf -u -s -i 1 -B {ip_address} -t {args.iperf_time} > {current_directory}/iperf-UE-server.log'
            iperfSrvThd = CommandThread(iperfSrvCmd, current_directory)
            iperfSrvThd.start()

            print("Starting iperf client job")
            iperfClntCmd = f'iperf -u -i 1 -B {ip_address} -b 3M -c {dn_ip_address} -t {args.iperf_time} > {current_directory}/iperf-UE-client.log'
            iperfClntThd = CommandThread(iperfClntCmd, current_directory)
            iperfClntThd.start()
        else:
            print(f"No interface found with the prefix {interface_prefix}")
    else:
        stop_and_kill_ue(ueThread)

    # Wait for iperf commands to finish
    iperfSrvThd.join()
    print("Finished iperf server job")
    iperfClntThd.join()
    print("Finished iperf client job")
    # Issue kill signal to the UE
    stop_and_kill_ue(ueThread)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Parameters to run tests')
    parser.add_argument('-m', '--mode',
                        required=True,
                        choices=['ue', 'core-nw'])
    parser.add_argument('-t', '--iperf_time',
                        default=10,
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

    if args.mode == 'ue':
        run_UE_test(args)
    elif args.mode == 'core-nw':
        run_core_test(args.iperf_time)
    else:
        print("Unknown mode")

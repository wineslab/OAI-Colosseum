#! /usr/bin/env python
# vim: set fenc=utf8 ts=4 sw=4 et :
#
# Layer 2 network neighbourhood discovery tool
# written by Benedikt Waldvogel (mail at bwaldvogel.de)

from __future__ import absolute_import, division, print_function
from utils.logger import *
import scapy.config
import scapy.layers.l2
import scapy.route
import socket
import math
import errno
import os
import getopt
import sys
import subprocess
import threading
import time


def long2net(arg):
    if (arg <= 0 or arg >= 0xFFFFFFFF):
        raise ValueError("illegal netmask value", hex(arg))
    return 32 - int(round(math.log(0xFFFFFFFF - arg, 2)))


def to_CIDR_notation(bytes_network, bytes_netmask):
    network = scapy.utils.ltoa(bytes_network)
    netmask = long2net(bytes_netmask)
    net = "%s/%s" % (network, netmask)
    if netmask < 16:
        #logging.warning("%s is too big. skipping" % net)
        return None

    return net


def improved_arping(net, iface=None, timeout=2, verbose=False, retry=2):
    """
    Improved ARP ping function that won't hang indefinitely

    Parameters:
    -----------
    net : str
        Network to scan (e.g., "192.168.1.0/24")
    iface : str, optional
        Network interface to use
    timeout : int, optional
        Timeout in seconds (default: 2)
    verbose : bool, optional
        Whether to print verbose output (default: False)
    retry : int, optional
        Number of retries (default: 2)

    Returns:
    --------
    tuple
        (answered packets, unanswered packets)
    """

    # Define result container
    result = [None]

    # Define the target function
    def target_func():
        try:
            result[0] = scapy.layers.l2.arping(
                net, iface=iface, timeout=timeout, verbose=verbose
            )
        except Exception as e:
            result[0] = ([], [])
            logging.error(f"Error in arping: {e}")

    # Create and start thread
    thread = threading.Thread(target=target_func)
    thread.daemon = True
    thread.start()

    # Wait for thread to complete or timeout
    max_wait = timeout * retry
    start_time = time.time()

    while thread.is_alive() and time.time() - start_time < max_wait:
        time.sleep(0.1)

    if thread.is_alive():
        logging.warning(f"ARP scan timed out after {max_wait} seconds")
        return [], []

    # Return the results
    if result[0] is None:
        logging.warning('Non results returned by arping')
        return [], []
    return result[0]


def get_active_nodes_nmap(net, iface, max_trials=10) -> list:

    logging.info('Getting list of active nodes using nmap')

    # SRN IP offset. E.g., SRN 1 has IP .101
    srn_offset = 100

    # flag to check we found at least one node that is not SRN.
    # Otherwise nmap has to be repeated
    nmap_successful = False
    re_runs = -1

    nmap_host_keyword = 'Nmap scan report for '
    nmap_up_keyword = 'Host is up'

    # get net base IP: e.g., if net is 172.30.104.0/24, get 172.30.104.
    net_last = net.split('.')[3]
    net_base_ip = net[:-len(net_last)]
    logging.info('net_last is {}'.format(net_last))
    logging.info('net_base_ip is {}'.format(net_base_ip))

    nmap_command = 'nmap -T4 -sn {}'.format(net)
    logging.info('nmap command is {}'.format(nmap_command))

    # list of active nodes IP addresses
    active_nodes = []
    while not nmap_successful:
        # use a temporary list to store active nodes
        tmp_nodes = []

        re_runs += 1

        if re_runs > max_trials:
            logging.error('No active hosts found by nmap. Returning empty list')
            return []

        logging.info('Starting nmap')
        pipe = subprocess.Popen(nmap_command, shell=True, stdout=subprocess.PIPE).stdout

        # separate lines returned by the above command
        lines = pipe.read().decode("utf-8").splitlines()

        for l_idx in range(len(lines)):
            curr_line = lines[l_idx]
            logging.info('curr_line is {}'.format(curr_line))

            # get SRN num from host IP
            if nmap_host_keyword in curr_line and nmap_up_keyword in lines[l_idx + 1]:
                srn_num = int(curr_line.split(col0_base_ip)[1]) - srn_offset

                # check this is an actual SRN and add it to dictionary
                if srn_num > 0:
                    tmp_nodes.append(curr_line)
                    logging.info('SRN with IP {} is active'.format(curr_line))
                else:
                    # this is not an SRN but is used to check that nmap is successful
                    logging.info('nmap successful')
                    nmap_successful = True

    if len(tmp_nodes) > 0:
        active_nodes = tmp_nodes
    else:
        logging.error('No active hosts found by nmap. Exiting')
        exit(1)

    logging.info('nmap completed, found active nodes {}'.format(active_nodes))
    return active_nodes


def scan_and_print_neighbors(net, interface, timeout=5):
    logging.info('Calling scan_and_print_neighbors function')
    output_scan_and_print = open('/logs/scan_print_output.log', "a")
    error_scan_and_print = open('/logs/scan_print_error.log', "a")
    try:
        logging.info('About to scan network for nodes')
        # ans, unans = scapy.layers.l2.arping(net, iface=interface, timeout=timeout, verbose=False)
        # ans, unans = improved_arping(net, iface=interface, timeout=timeout, verbose=True, retry=2)
        ans = get_active_nodes_nmap(net, iface=interface)
        logging.info('Done scanning network for nodes')
        # logging.info('Got ans: {}'.format(ans.res))
        # logging.info('Got unans: {}'.format(unans.res))
        logging.info('Got ans: {}'.format(ans))
        # for s, r in ans.res:
        for line in ans:
            # line = r.sprintf("%ARP.psrc%")
            # logging.info(line)
            logging.info('Loop node with IP {}'.format(line))
            command = ['route', 'add', '-net', '192.168.70.128/26', 'gw', line, 'dev', 'col0']
            response = subprocess.run(args=command, stdout=output_scan_and_print, stderr=error_scan_and_print).returncode
            command = ['ping', '-c', '1', '-t', '1', '192.168.70.129']
            response = subprocess.run(args=command, stdout=output_scan_and_print, stderr=error_scan_and_print).returncode
            logging.info("For host %s response is %s" % (line, response))
            if response == 0:
                logging.info("IP address of host running CN is %s" % line)
                break
            else:
                os.system("route del -net 192.168.70.128/26")
            # try:
            #     hostname = socket.gethostbyaddr(r.psrc)
            #     logging.info('Got hostname {}'.format(hostname))
            #     line += " " + hostname[0]
            #     logging.info('Got line {}'.format(line))
            # except socket.herror as he:
            #     # failed to resolve
            #     logging.warning('Passing on error: {}'.format(he))
            #     pass
    except socket.error as e:
        logging.error('Got error: {}'.format(e))
        if e.errno == errno.EPERM:     # Operation not permitted
            logging.error("%s. Did you run as root?", e.strerror)
        else:
            raise


def main(interface_to_scan=None):
    logging.info('Calling function to set route to CN')
    output_file_cn_route = open('/logs/cn_route_output.log', "a")
    error_file_cn_route = open('/logs/cn_route_error.log', "a")
    if os.geteuid() != 0:
        logging.error('You need to be root to run this script')
        sys.exit(1)

    for network, netmask, _, interface, address, _ in scapy.config.conf.route.routes:

        if interface_to_scan and interface_to_scan != interface:
            logging.warning('Skipping interface {}'.format(interface))
            continue

        # skip loopback network and default gw
        if network == 0 or interface == 'lo' or address == '127.0.0.1' or address == '0.0.0.0':
            logging.warning('Skipping interface {}'.format(interface))
            continue

        if netmask <= 0 or netmask == 0xFFFFFFFF:
            logging.warning('Skipping interface {} because of netmask {}'.format(interface, netmask))
            continue

        # skip docker interface
        if interface != interface_to_scan \
                and (interface.startswith('docker')
                     or interface.startswith('br-')
                     or interface.startswith('tun')):
            logging.warning("Skipping interface '%s'" % interface)
            continue

        logging.info('Using interface {}'.format(interface))
        logging.info('Before calling to_CIDR_notation')
        net = to_CIDR_notation(network, netmask)
        logging.info('After calling to_CIDR_notation')
        logging.info('Got net {}'.format(net))

        if net:
            found = False
            # temporarily commenting to debug ARP
            # command = ['ping', '-c', '1', '-t', '1', '192.168.70.129']
            # response = subprocess.run(args=command, stdout=output_file_cn_route, stderr=error_file_cn_route).returncode
            # logging.info('Got response from ping: {}'.format(response))
            # if response == 0:
            #     logging.info("Route to CN host exists!")
            #     found = True
            # else:
            #     command = ['route', 'del', '-net', '192.168.70.128/26']
            #     subprocess.run(args=command, stdout=output_file_cn_route, stderr=error_file_cn_route).returncode
            #     found = False

            while not found:
                logging.info('Before calling scan_and_print_neighbors')
                scan_and_print_neighbors(net, interface)
                logging.info('After calling scan_and_print_neighbors')
                command = ['ping', '-c', '1', '-t', '1', '192.168.70.129']
                found = (subprocess.run(args=command, stdout=output_file_cn_route, stderr=error_file_cn_route).returncode) == 0
                logging.info("Found is %s" % found)
                if found:
                    logging.info("Route to core network added!")
                else:
                    logging.info("Route to core network not found. Retrying...")


def usage():
    print("Usage: %s [-i <interface>]" % sys.argv[0])


if __name__ == "__main__":
    try:
        opts, args = getopt.getopt(sys.argv[1:], 'hi:', ['help', 'interface='])
    except getopt.GetoptError as err:
        print(str(err))
        usage()
        sys.exit(2)

    interface = None

    # set logger
    log_filename = os.path.basename(__file__).replace('.py', '.log')
    set_logger(log_filename)

    for o, a in opts:
        if o in ('-h', '--help'):
            usage()
            sys.exit()
        elif o in ('-i', '--interface'):
            interface = a
        else:
            assert False, 'unhandled option'

    main(interface_to_scan=interface)

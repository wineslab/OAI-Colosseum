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
import re
import sys
import subprocess


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


def extract_ip_addresses(nmap_output):
    """
    Extract all IP addresses from nmap output.

    Args:
        nmap_output (str): The nmap output text

    Returns:
        list: List of IP addresses found in the output
    """
    # This regex pattern matches IPv4 addresses
    ip_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}\b'

    # Find all matches in the text
    ip_addresses = re.findall(ip_pattern, nmap_output)

    return ip_addresses


def get_active_nodes_nmap(net, iface, max_trials=10) -> list:

    logging.info('Getting list of active nodes using nmap')

    # SRN IP offset. E.g., SRN 1 has IP .101
    srn_offset = 100

    # flag to check we found at least one node that is not SRN.
    # Otherwise nmap has to be repeated
    nmap_successful = False
    nmap_run = -1

    nmap_command = 'nmap -T4 -sn {}'.format(net)
    logging.info('nmap command is {}'.format(nmap_command))

    # list of active nodes IP addresses
    active_nodes = []
    while not nmap_successful:
        nmap_run += 1

        if nmap_run > max_trials:
            logging.warning('No active hosts found by nmap. Returning empty list')
            return []

        logging.info('nmap run {}'.format(nmap_run))
        pipe = subprocess.Popen(nmap_command, shell=True, stdout=subprocess.PIPE).stdout

        lines = pipe.read().decode("utf-8")
        logging.info('nmap output is {}'.format(lines))
        nmap_ip = extract_ip_addresses(lines)
        logging.info('IP addresses found by nmap: {}'.format(nmap_ip))
        active_nodes = [x for x in nmap_ip if int(x.split('.')[-1]) > srn_offset]

        if active_nodes:
            nmap_successful = True

    logging.info('nmap completed, found active nodes {}'.format(active_nodes))
    return active_nodes


def scan_and_print_neighbors(net, interface, timeout=5):
    try:
        ans, unans = scapy.layers.l2.arping(net, iface=interface, timeout=timeout, verbose=False)
        for s, r in ans.res:
            line = r.sprintf("%ARP.psrc%")
            line = r.sprintf("%ARP.psrc%")
            # logging.info(line)
            command = ['route', 'add', '-net', '192.168.70.128/26', 'gw', line, 'dev', 'col0']
            response = subprocess.run(args=command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
            command = ['ping', '-c', '1', '-t', '1', '192.168.70.129']
            response = subprocess.run(args=command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
            #logging.info("For host %s response is %s" % (line, response))
            if response == 0:
                logging.info("IP address of host running CN is %s" % line)
                break
            else:
                os.system("route del -net 192.168.70.128/26")
            try:
                hostname = socket.gethostbyaddr(r.psrc)
                line += " " + hostname[0]
            except socket.herror:
                # failed to resolve
                pass
    except socket.error as e:
        if e.errno == errno.EPERM:     # Operation not permitted
            logging.error("%s. Did you run as root?", e.strerror)
        else:
            raise


def main(interface_to_scan=None):
    if os.geteuid() != 0:
        print('You need to be root to run this script', file=sys.stderr)
        sys.exit(1)

    for network, netmask, _, interface, address, _ in scapy.config.conf.route.routes:

        if interface_to_scan and interface_to_scan != interface:
            continue

        # skip loopback network and default gw
        if network == 0 or interface == 'lo' or address == '127.0.0.1' or address == '0.0.0.0':
            continue

        if netmask <= 0 or netmask == 0xFFFFFFFF:
            continue

        # skip docker interface
        if interface != interface_to_scan \
                and (interface.startswith('docker')
                     or interface.startswith('br-')
                     or interface.startswith('tun')):
            logging.warning("Skipping interface '%s'" % interface)
            continue

        net = to_CIDR_notation(network, netmask)

        if net:
            found = False
            command = ['ping', '-c', '1', '-t', '1', '192.168.70.129']
            response = subprocess.run(args=command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
            if response == 0:
                logging.info("Route to CN host exists!")
                found = True
            else:
                command = ['route', 'del', '-net', '192.168.70.128/26']
                subprocess.run(args=command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
                found = False
            while not found:
                scan_and_print_neighbors(net, interface)
                command = ['ping', '-c', '1', '-t', '1', '192.168.70.129']
                found = (subprocess.run(args=command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode) == 0
                #logging.info("Found is %s" % found)
                if found:
                    logging.info("Route to core network added!")
                    break
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

import os
import argparse
import json
import nrarfcn as nr
import ipaddress
from dotenv import load_dotenv
from set_route_to_cn import main as set_route

load_dotenv()

USRP_DEV = os.getenv('USRP_DEV')
OAI_PATH = os.getenv('OAI_PATH')
BASE_CONF = os.getenv('BASE_CONF')
USRP_ADDR = os.getenv('USRP_ADDR')
MAIN_DEV = os.getenv('MAIN_DEV')
AMF_IP = os.getenv('AMF_IP')


def pointa_from_ssb(arfcn, prb):
    return arfcn - 12*prb


def get_locationandbandwidth(prb):
    # TODO: check if it's valid for numerology =! 1
    if prb > 133:
        return 275*(275-prb+1)+(275-1-0)
    else:
        return 275*(prb-1)


class Ran:
    def __init__(self, args):
        self.args = args
        self.prb = args.prb
        self.numerology = args.numerology
        self.channel = args.channel
        self.type = args.type
        with open('conf.json', 'r') as fr:
            conf = json.load(fr)
        self.conf = conf[str(self.numerology)][str(self.prb)]
        self.arfcn = self.conf['arfcns'][self.channel]
        self.pointa = pointa_from_ssb(self.arfcn, self.prb)
        self.ssb_frequency = int(nr.get_frequency(self.arfcn)*1e6)
        self.set_main_ip()

    def set_main_ip(self):
        main_ip = os.popen(f"ip -f inet addr show {MAIN_DEV} | grep -Po 'inet \K[\d.]+'").read().strip()
        ipaddress.ip_address(main_ip)
        self.main_ip = main_ip
        self.node_id = main_ip.split('.')[3]

    def run(self):
        if self.type == 'donor':
            self.run_gnb(type='donor')
        elif self.type == 'ue':
            self.run_ue()

    def run_gnb(self, type):
        set_route(MAIN_DEV)
        LABW = get_locationandbandwidth(self.prb)
        pre_path = ""
        if self.args.numa > 0:
            pre_path = f"numactl --cpunodebind=netdev:{USRP_DEV} --membind=netdev:{USRP_DEV} "
        if self.args.gdb > 0:
            # gdb override numa
            pre_path = f'gdb --args '
        executable = f"{OAI_PATH}/nr-softmodem "
        oai_args = [f"-O {BASE_CONF}", "--sa", "--usrp-tx-thread-config 1"]
        if self.prb >= 106 and self.numerology == 1:
            oai_args.append("-E")
        # Set cell name and id
        oai_args += [f'--Active_gNBs "IAB-{self.node_id}"',
                     f'--gNBs.[0].gNB_ID {self.node_id}',
                     f'--gNBs.[0].gNB_name "IAB-{self.node_id}"']
        # Set frequency, prb and BWP Location
        oai_args += [f'--gNBs.[0].servingCellConfigCommon.[0].absoluteFrequencySSB {self.arfcn}',
                     f'--gNBs.[0].servingCellConfigCommon.[0].dl_absoluteFrequencyPointA {self.pointa}',
                     f'--gNBs.[0].servingCellConfigCommon.[0].dl_carrierBandwidth {self.prb}',
                     f'--gNBs.[0].servingCellConfigCommon.[0].ul_carrierBandwidth {self.prb}',
                     f'--gNBs.[0].servingCellConfigCommon.[0].initialDLBWPlocationAndBandwidth {LABW}',
                     f'--gNBs.[0].servingCellConfigCommon.[0].initialULBWPlocationAndBandwidth {LABW}']
        # Set AMF parameters
        # BUG: this cli command is not working, wait for answer from OAI ml
        oai_args += [f'--gNBs.[0].amf_ip_address.[0].ipv4 {AMF_IP}',
                     f'--gNBs.[0].NETWORK_INTERFACES.GNB_INTERFACE_NAME_FOR_NG_AMF {MAIN_DEV}',
                     f'--gNBs.[0].NETWORK_INTERFACES.GNB_INTERFACE_NAME_FOR_NGU {MAIN_DEV}',
                     f'--gNBs.[0].NETWORK_INTERFACES.GNB_IPV4_ADDRESS_FOR_NG_AMF {self.main_ip}',
                     f'--gNBs.[0].NETWORK_INTERFACES.GNB_IPV4_ADDRESS_FOR_FOR_NGU {self.main_ip}']

        # Set USRP addr
        oai_args += [f'--RUs.[0].sdr_addrs "addr={USRP_ADDR}"']
        # Add option to increase the UE stability
        oai_args += [f'--continuous-tx']
        os.system(f"{pre_path} {executable} {' '.join(oai_args)}")

    def run_ue(self):
        pre_path = ""
        if self.args.numa > 0:
            pre_path = f"numactl --cpunodebind=netdev:{USRP_DEV} --membind=netdev:{USRP_DEV}"
        if self.args.gdb > 0:
            # gdb override numa
            pre_path = f'gdb --args'
        executable = f"{OAI_PATH}/nr-uesoftmodem"
        args = ["--dlsch-parallel 8",
                "--sa",
                f"--uicc0.imsi 20899000074{self.node_id[1:]}",
                f'--usrp-args "addr = {USRP_ADDR}"',
                f'--numerology {self.numerology}',
                f'-r {self.prb}',
                f'-s {self.conf["ssb_start"]}',
                '--band 78',
                f'-C {self.ssb_frequency}',
                '--nokrnmod 1',
                '--ue-txgain 0',
                f'-A {self.conf["timing_advance"]}',
                '--clock-source 1',
                '--time-source 1',
                '--ue-fo-compensation']
        if self.prb >= 106 and self.numerology == 1:
            # USRP X3*0 needs to lower the sample rate to 3/4
            args.append("-E")
        print(self.arfcn, self.pointa, self.ssb_frequency)
        os.system(f"{pre_path} {executable} {' '.join(args)}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Parameters to run RAN element')
    parser.add_argument('-n', '--numerology',
                        default=1,
                        type=int,
                        choices=[0, 1, 2, 3, 4],
                        help='numerology for subcarrier spacing')
    parser.add_argument('-p', '--prb',
                        required=True,
                        type=int)
    parser.add_argument('-c', '--channel',
                        required=True,
                        default=0,
                        type=int)
    parser.add_argument('-t', '--type',
                        required=True,
                        choices=['donor', 'relay', 'ue'])
    parser.add_argument('--numa',
                        required=False,
                        default=1,
                        type=int)
    parser.add_argument('--gdb', required=False, default=0, type=int)

    args = parser.parse_args()
    r = Ran(args)
    r.run()

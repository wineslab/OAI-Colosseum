import os
import argparse
import json
from threading import local
import nrarfcn as nr
import sys
import time
from dotenv import load_dotenv
from utils.set_route_to_cn import main as set_route
from utils.x300 import ctrl_socket
load_dotenv()

USRP_DEV = os.getenv('USRP_DEV')
OAI_PATH = os.getenv('OAI_PATH')
BASE_CONF = os.getenv('BASE_CONF')
USRP_ADDR = os.getenv('USRP_ADDR')
MAIN_DEV = os.getenv('MAIN_DEV')
IAB_DEV = os.getenv('IAB_DEV')
AMF_IP = os.getenv('AMF_IP')
VIVADO_PATH = '/opt/vivado_colosseum'


def pointa_from_ssb(arfcn, prb):
    return arfcn - 12*prb


def get_locationandbandwidth(prb):
    # TODO: check if it's valid for numerology =! 1
    if prb > 133:
        return 275*(275-prb+1)+(275-1-0)
    else:
        return 275*(prb-1)


def subst_bindip(local_ip, dev):
    # Workaround while the bug with CLI params is fixed
    os.system(f"""sed -i "/GNB_INTERFACE_NAME_FOR_NG_AMF/ c \    GNB_INTERFACE_NAME_FOR_NG_AMF              = \\"{dev}\\";" {BASE_CONF};""")
    os.system(f"""sed -i "/GNB_INTERFACE_NAME_FOR_NGU/ c \    GNB_INTERFACE_NAME_FOR_NGU              = \\"{dev}\\";" {BASE_CONF};""")
    os.system(f"""sed -i "/GNB_IPV4_ADDRESS_FOR_NG_AMF/ c \    GNB_IPV4_ADDRESS_FOR_NG_AMF              = \\"{local_ip}/24\\";" {BASE_CONF};""")
    os.system(f"""sed -i "/GNB_IPV4_ADDRESS_FOR_NGU/ c \    GNB_IPV4_ADDRESS_FOR_NGU                 = \\"{local_ip}/24\\";" {BASE_CONF};""")


def flash_x310():
    os.system(f"./utils/flash_usrp.sh")


def reset_x310():
    x300 = ctrl_socket(addr=USRP_ADDR)
    x300.poke_print(0x100058, 1)


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
        self.set_ips()

    def set_ips(self):
        self.main_ip = os.popen(f"ip -f inet addr show {MAIN_DEV} | grep -Po 'inet \K[\d.]+'").read().strip()
        self.iab_ip = os.popen(f"ip -f inet addr show {IAB_DEV} | grep -Po 'inet \K[\d.]+'").read().strip()
        self.node_id = self.main_ip.split('.')[3]

    def run(self):
        try:
            os.remove('/root/last_log')
        except:
            pass
        if self.args.flash == 1:
            flash_x310()
            time.sleep(5)
        if self.type == 'donor':
            self.run_gnb(type='donor')
        elif self.type == 'relay':
            self.run_gnb(type='relay')
        elif self.type == 'ue':
            self.run_ue()
        else:
            print("Error")
            exit(0)

    def run_gnb(self, type):
        if type == 'donor':
            local_ip = self.main_ip
            local_dev = MAIN_DEV
            set_route(MAIN_DEV)
        elif type == 'relay':
            local_ip = self.iab_ip
            local_dev = IAB_DEV
        else:
            print("IAB type error")
            exit(0)
        subst_bindip(local_ip, local_dev)

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
        # BUG: this cli command is not working, wait for answer from OAI
        oai_args += [f'--gNBs.[0].amf_ip_address.[0].ipv4 {AMF_IP}',
                     f'--gNBs.[0].NETWORK_INTERFACES.GNB_INTERFACE_NAME_FOR_NG_AMF {local_dev}',
                     f'--gNBs.[0].NETWORK_INTERFACES.GNB_INTERFACE_NAME_FOR_NGU {local_dev}',
                     f'--gNBs.[0].NETWORK_INTERFACES.GNB_IPV4_ADDRESS_FOR_NG_AMF {local_ip}',
                     f'--gNBs.[0].NETWORK_INTERFACES.GNB_IPV4_ADDRESS_FOR_FOR_NGU {local_ip}']

        # Set USRP addr
        oai_args += [f'--RUs.[0].sdr_addrs "addr={USRP_ADDR}"']
        # Add option to increase the UE stability
        oai_args += [f'--continuous-tx']
        os.system(f"""{pre_path} {executable} {' '.join(oai_args)}  2>&1 | tee ~/mylogs/gNB-$(date +"%m%d%H%M").log | tee ~/last_log""")

    def run_ue(self):
        pre_path = ""
        if self.args.numa > 0:
            pre_path = f"numactl --cpunodebind=netdev:{USRP_DEV} --membind=netdev:{USRP_DEV}"
        if self.args.gdb > 0:
            # gdb override numa
            pre_path = f'gdb --args'
        executable = f"{OAI_PATH}/nr-uesoftmodem"
        args = ["--dlsch-parallel 32",
                "--sa",
                f"--uicc0.imsi 20899000074{self.node_id[1:]}",
                f'--usrp-args "addr={USRP_ADDR}"',
                f'--numerology {self.numerology}',
                f'-r {self.prb}',
                # This parameter changes from -s to -ssb after a certain commit ~w42
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
        os.system(f"""{pre_path} {executable} {' '.join(args)} 2>&1 | tee ~/mylogs/UE1-$(date +"%m%d%H%M").log | tee ~/last_log""")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Parameters to run RAN element')
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
    parser.add_argument('-t', '--type',
                        required=True,
                        choices=['donor', 'relay', 'ue'])
    parser.add_argument('--numa',
                        default=True,
                        action='store_true')
    parser.add_argument('--gdb', default=False, action='store_true')
    parser.add_argument('--flash', '-f', default=False, action='store_true')

    args = parser.parse_args()
    r = Ran(args)
    r.run()

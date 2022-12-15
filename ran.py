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
import subprocess
import signal
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


def subst_bindip(local_ip, dev, if_freq, conf_file):
    # Workaround while the bug with CLI params is fixed
    os.system(f"""sed -i "/GNB_INTERFACE_NAME_FOR_NG_AMF/ c \    GNB_INTERFACE_NAME_FOR_NG_AMF              = \\"{dev}\\";" {conf_file};""")
    os.system(f"""sed -i "/GNB_INTERFACE_NAME_FOR_NGU/ c \    GNB_INTERFACE_NAME_FOR_NGU              = \\"{dev}\\";" {conf_file};""")
    os.system(f"""sed -i "/GNB_IPV4_ADDRESS_FOR_NG_AMF/ c \    GNB_IPV4_ADDRESS_FOR_NG_AMF              = \\"{local_ip}/24\\";" {conf_file};""")
    os.system(f"""sed -i "/GNB_IPV4_ADDRESS_FOR_NGU/ c \    GNB_IPV4_ADDRESS_FOR_NGU                 = \\"{local_ip}/24\\";" {conf_file};""")
    os.system(f"""sed -i "/if_freq/ c \if_freq = \\{if_freq}L\\;" {conf_file};""")


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
        self.mode = args.mode
        self.f1_remote_node = args.f1_remote_node
        self.config_file = '/tmp/oai_config.conf'
        if self.mode == 'phy-test':
            self.phytest = args.phytestargs
        with open('conf.json', 'r') as fr:
            self.conf_json = json.load(fr)
        self.conf = self.conf_json[str(self.numerology)][str(self.prb)]
        self.set_if_freq(self.channel)
        self.set_params(arfcn=self.conf['arfcns'][self.channel])

        self.set_ips()
        try:
            os.remove('/root/last_log')
        except:
            pass

    def set_config_file(self, f1_type, local_ip, local_dev):
        os.system(f"cp {BASE_CONF} {self.config_file}")
        subst_bindip(local_ip, local_dev, self.if_freq, self.config_file)
        args = []
        # common for DU and donor (monolithic)
        if f1_type == 'du' or f1_type == 'donor':
            macrlcs = 'MACRLCs = \(\{ \}\)\;'
            os.system(f"echo {macrlcs} >> {self.config_file}")
            args += ['--MACRLCs.[0].num_cc 1',
                     '--MACRLCs.[0].tr_s_preference "local_L1"',
                     '--MACRLCs.[0].pusch_TargetSNRx10 150',
                     '--MACRLCs.[0].pucch_TargetSNRx10 200',
                     '--MACRLCs.[0].ul_prbblack_SNR_threshold 10',
                     '--MACRLCs.[0].ulsch_max_frame_inactivity 0']
            if f1_type == 'du':
                args += ['--MACRLCs.[0].tr_n_preference "f1"',
                         '--MACRLCs.[0].local_n_if_name "col0"',
                         f'--MACRLCs.[0].local_n_address "{self.main_ip}"',
                         f'--MACRLCs.[0].remote_n_address "{self.f1_remote_node}"',
                         '--MACRLCs.[0].local_n_portc 500',
                         '--MACRLCs.[0].local_n_portd 2252',
                         '--MACRLCs.[0].remote_n_portc 501',
                         '--MACRLCs.[0].remote_n_portd 2252']
            elif f1_type == 'donor':
                args += ['--MACRLCs.[0].tr_n_preference "local_RRC"']
            l1s = 'L1s = \(\{ \}\)\;'
            os.system(f"echo {l1s} >> {self.config_file}")
            args += ['--L1s.[0].num_cc 1',
                     '--L1s.[0].tr_n_preference "local_mac"',
                     '--L1s.[0].pusch_proc_threads 32',
                     '--L1s.[0].prach_dtx_threshold 120',
                     '--L1s.[0].pucch0_dtx_threshold 150',
                     '--L1s.[0].ofdm_offset_divisor 8']
            rus = 'RUs = \(\{ \}\)\;'
            os.system(f"echo {rus} >> {self.config_file}")
            args += ['--RUs.[0].local_rf "yes"',
                     '--RUs.[0].nb_tx 1',
                     '--RUs.[0].nb_rx 1',
                     '--RUs.[0].att_tx 0',
                     '--RUs.[0].att_rx 0',
                     '--RUs.[0].bands [78]',
                     '--RUs.[0].max_pdschReferenceSignalPower -27',
                     '--RUs.[0].max_rxgain 114',
                     '--RUs.[0].eNB_instances [0]',
                     '--RUs.[0].bf_weights [0x00007fff, 0x0000, 0x0000, 0x0000]',
                     '--RUs.[0].clock_src "external"',
                     '--RUs.[0].time_src "external"',
                     f'--RUs.[0].sdr_addrs "addr={USRP_ADDR}"',
                     f'--RUs.[0].if_freq {self.if_freq}']
            tss = 'THREAD_STRUCT = \(\{ \}\)\;'
            os.system(f"echo {tss} >> {self.config_file}")
            args += ['--THREAD_STRUCT.[0].parallel_config "PARALLEL_SINGLE_THREAD"',
                     '--THREAD_STRUCT.[0].worker_config "WORKER_ENABLE"']
        elif f1_type == 'cu':
            args += ['--gNBs.[0].tr_s_preference "f1"',
                     '--gNBs.[0].local_s_if_name "col0"',
                     f'--gNBs.[0].local_s_address "{self.main_ip}"',
                     f'--gNBs.[0].remote_s_address "{self.f1_remote_node}"',
                     f'--gNBs.[0].local_s_portc 501',
                     '--gNBs.[0].local_s_portd 2252',
                     '--gNBs.[0].remote_s_portc 500',
                     '--gNBs.[0].remote_s_portd 2252']
        return args

    def set_params(self, arfcn):
        self.arfcn = arfcn
        self.pointa = pointa_from_ssb(self.arfcn, self.prb)
        self.ssb_frequency = int(nr.get_frequency(self.arfcn)*1e6)

    def set_if_freq(self, channel):
        if self.args.if_freq:
            self.if_freq = self.conf['if_freqs'][channel]
        else:
            self.if_freq = 0

    def set_ips(self):
        self.main_ip = os.popen(f"ip -f inet addr show {MAIN_DEV} | grep -Po 'inet \K[\d.]+'").read().strip()
        self.iab_ip = os.popen(f"ip -f inet addr show {IAB_DEV} | grep -Po 'inet \K[\d.]+'").read().strip()
        self.node_id = self.main_ip.split('.')[3]

    def run(self):
        if self.args.flash:
            flash_x310()
            time.sleep(5)
        if self.type == 'donor':
            self.run_gnb(type='donor')
        elif self.type == 'cu':
            self.run_gnb(type='cu')
        elif self.type == 'du':
            self.run_gnb(type='du')
        elif self.type == 'relay':
            self.run_gnb(type='relay')
        elif self.type == 'ue':
            self.run_ue()
        else:
            print("Error")
            exit(0)

    def run_gnb(self, type):
        if type != 'relay':
            local_ip = self.main_ip
            local_dev = MAIN_DEV
            set_route(MAIN_DEV)
        else:
            local_ip = self.iab_ip
            local_dev = IAB_DEV
        f1_cmd_args = self.set_config_file(type, local_ip, local_dev)
        LABW = get_locationandbandwidth(self.prb)
        pre_path = ""
        if self.args.numa > 0:
            pre_path = f"numactl --cpunodebind=netdev:{USRP_DEV} --membind=netdev:{USRP_DEV} "
        if self.args.gdb > 0:
            # gdb override numa
            pre_path = f'gdb --args '
        executable = f"{OAI_PATH}/cmake_targets/ran_build/build/nr-softmodem "
        oai_args = [f"-O {self.config_file}", "--usrp-tx-thread-config 1"]
        if self.prb >= 106 and self.numerology == 1:
            oai_args.append("-E")
        if self.args.rfsim > 0:
            oai_args += ['--rfsim']
        oai_args += [f'--{self.mode}']
        if self.mode == 'phy-test':
            oai_args += [f'{self.phytest}']
        oai_args += [f'--continuous-tx']
        oai_args += ["--thread-pool '-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1'"]
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

        # Set F1 parameters
        oai_args += f1_cmd_args
        # Add option to increase the UE stability
        #os.system(f"""{pre_path} {executable} {' '.join(oai_args)}  2>&1 | tee ~/mylogs/gNB-$(date +"%m%d%H%M").log | tee ~/last_log""")
        os.system(f"""{pre_path} {executable} {' '.join(oai_args)}""")

    def run_ue(self):
        main_exe = f"{OAI_PATH}/cmake_targets/ran_build/build/nr-uesoftmodem"
        pre_path = ""
        if self.args.numa > 0:
            pre_path = f"numactl --cpunodebind=netdev:{USRP_DEV} --membind=netdev:{USRP_DEV}"
        if self.args.gdb > 0:
            # gdb override numa
            pre_path = f'gdb --args'
        args = ["--thread-pool '-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1'",
                f'--{self.mode}',
                f"--uicc0.imsi 20899000074{self.node_id[1:]}",
                f'--usrp-args "addr={USRP_ADDR}"',
                f'--numerology {self.numerology}',
                f'-r {self.prb}',
                # This parameter changes from -s to -ssb after a certain commit ~w42
                f'--ssb {self.conf["ssb_start"]}',
                '--band 78',
                f'-C {self.ssb_frequency}',
                '--nokrnmod 1',
                '--ue-txgain 0',
                f'-A {self.conf["timing_advance"]}',
                '--clock-source 1',
                '--time-source 1',
                '--ue-fo-compensation',
                f'--if_freq {self.if_freq}']
        if self.args.type == 'phy-test':
            args += ["--phy-test"]
        if self.args.rfsim > 0:
            executable = f"RFSIMULATOR=127.0.0.1 {main_exe}"
            args += ["--rfsim"]
        else:
            executable = main_exe
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
                        choices=['donor', 'relay', 'ue', 'scan', 'cu', 'du'])
    parser.add_argument('-F', '--f1_remote_node',
                        help='Address of F1 remote node address')
    parser.add_argument('-m', '--mode',
                        choices=['sa', 'phy-test'],
                        default='sa')
    parser.add_argument('-P', '--phytestargs',
                        type=str,
                        default="\-m9 \-t9 \-M106 \-T106 \-D130175 \-U918400",
                        help='phy-test mode parameters: -D: DLSCH sched bitmap, -U: ULSCH sched bitmap, -m: DL MCS, -t UL MCS, -M: DL PRBs, -T: UL PRBs')
    parser.add_argument('--rfsim',
                        default=False,
                        action='store_true')
    parser.add_argument('--numa',
                        default=True,
                        action='store_false')
    parser.add_argument('--gdb', default=False, action='store_true')
    parser.add_argument('--flash', '-f', default=False, action='store_true')
    parser.add_argument('--if_freq', default=0, type=int)

    args = parser.parse_args()
    r = Ran(args)
    r.run()

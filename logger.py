import sys
import time
import logging
from watchdog.observers import Observer
from watchdog.events import LoggingEventHandler, FileSystemEventHandler
from threading import Lock
import json
import pickle
import re
import docker 
import requests
from pprint import pprint


client = docker.from_env()
rapp = client.containers.get('rapp')
rapp_ip = rapp.attrs['NetworkSettings']['Networks']['nonrtric-docker-net']['IPAddress']
API_ENDPOINT = f'http://{rapp_ip}/api/'

def parse_nrMAC(s):
    ues = {}
    ue = {}
    lines = s.strip().split('\n')
    for line in lines:
        line = line.strip()
        if line.startswith('UE RNTI'):
            # Parse the first line
            print(line)
            m = re.match(
                r'UE RNTI (\S+) CU-UE-ID (\d+) in-sync PH (-?\d+ dB) PCMAX (-?\d+ dBm), average RSRP (-?\d+) \((\d+) meas\)',
                line
            )
            print(m)
            if m:
                ue_id = m.group(1)
                ue |= {
                    'RNTI': ue_id,
                    'CU-UE-ID': int(m.group(2)),
                    'in-sync': True,
                    'PH': m.group(3),
                    'PCMAX': m.group(4),
                    'average RSRP': int(m.group(5)),
                    'average RSRP meas': int(m.group(6))
                }
        elif line.startswith('UE '):
            # Parse subsequent lines
            m = re.match(r'UE (\S+): (.*)', line)
            if m:
                ue_id = m.group(1)
                rest = m.group(2)
                if ue_id not in ues:
                    ues[ue_id] = {}
                if rest.startswith('dlsch_rounds'):
                    m2 = re.match(
                        r'dlsch_rounds (\S+), dlsch_errors (\d+), pucch0_DTX (\d+), BLER ([\d\.]+) MCS \((\d+)\) (\d+)',
                        rest
                    )
                    if m2:
                        ue.update({
                            'dlsch_rounds': m2.group(1).split('/'),
                            'dlsch_errors': int(m2.group(2)),
                            'pucch0_DTX': int(m2.group(3)),
                            'dlsch_bler': float(m2.group(4)),
                            'dlsch_mcs_table': m2.group(5),
                            'dlsch_mcs': int(m2.group(6))
                        })
                elif rest.startswith('ulsch_rounds'):
                    m2 = re.match(
                        r'ulsch_rounds (\S+), ulsch_errors (\d+), ulsch_DTX (\d+), BLER ([\d\.]+) MCS \((\d+)\) (\d+)',
                        rest
                    )
                    if m2:
                        ue.update({
                            'ulsch_rounds': m2.group(1).split('/'),
                            'ulsch_errors': int(m2.group(2)),
                            'ulsch_DTX': int(m2.group(3)),
                            'ulsch_bler': float(m2.group(4)),
                            'ulsch_mcs_table': m2.group(5),
                            'ulsch_mcs': int(m2.group(6))
                        })
                elif rest.startswith('MAC:'):
                    m2 = re.match(r'MAC:\s+TX\s+(\d+)\s+RX\s+(\d+)\s+bytes', rest)
                    if m2:
                        ue['MAC'] = {'TX': int(m2.group(1)), 'RX': int(m2.group(2))}
                elif rest.startswith('LCID'):
                    m2 = re.match(r'LCID (\d+):\s+TX\s+(\d+)\s+RX\s+(\d+)\s+bytes', rest)
                    if m2:
                        lcid = m2.group(1)
                        ue.setdefault('LCID', {})[lcid] = {
                            'TX': int(m2.group(2)),
                            'RX': int(m2.group(3))
                        }
    return ue


def parse_prb_values(lines, start_index):
    """Parses the PRB values spanning multiple lines."""
    prb_values = []
    i = start_index
    n = len(lines)
    while i < n and not lines[i].startswith('max_IO'):
        prb_line = lines[i].strip()
        # Use regex to find numbers including negatives and decimals
        numbers = re.findall(r'[-]?\d+\.?\d*', prb_line)
        prb_values.extend([float(num) for num in numbers])
        i += 1
    return prb_values, i

def parse_io_values(line):
    """Parses the 'max_IO', 'min_I0', and 'avg_I0' line."""
    m = re.match(
        r'max_IO = (\d+) \((\d+)\), min_I0 = (\d+) \((\d+)\), avg_I0 = ([\d\.]+) dB',
        line
    )
    if m:
        return {
            'max_IO': {
                'value': int(m.group(1)),
                'index': int(m.group(2))
            },
            'min_I0': {
                'value': int(m.group(3)),
                'index': int(m.group(4))
            },
            'avg_I0': float(m.group(5))
        }
    return None

def parse_prach_i0(line):
    """Parses the 'PRACH I0' line."""
    m = re.match(r'PRACH I0 = ([\d\.]+) dB', line)
    if m:
        return float(m.group(1))
    return None

def parse_dlsch_line(line):
    """Parses a 'DLSCH RNTI' line."""
    m = re.match(
        r'DLSCH RNTI (\w+): current_Qm (\d+), current_RI (\d+), total_bytes TX (\d+)',
        line
    )
    if m:
        return {
            'RNTI': m.group(1),
            'current_Qm': int(m.group(2)),
            'current_RI': int(m.group(3)),
            'total_bytes_TX': int(m.group(4))
        }
    return None

def parse_ulsch_line(lines, index):
    """Parses an 'ULSCH RNTI' block (two lines)."""
    line1 = lines[index].strip()
    if index + 1 < len(lines):
        line2 = lines[index + 1].strip()
    else:
        line2 = ''
    # Parse the first line
    m = re.match(
        r'ULSCH RNTI (\w+), (\d+): ulsch_power\[0\] ([\d,\.]+) ulsch_noise_power\[0\] ([\d\.]+), sync_pos (\d+)',
        line1
    )
    if m:
        ulsch_entry = {
            'RNTI': m.group(1),
            'some_id': int(m.group(2)),
            'ulsch_power': float(m.group(3).replace(',', '.')),
            'ulsch_noise_power': float(m.group(4)),
            'sync_pos': int(m.group(5))
        }
        # Parse the second line
        m2 = re.match(
            r'round_trials (\d+)\(([\d\.e\-\+]+)\):(\d+)\(([\d\.e\-\+]+)\):(\d+)\(([\d\.e\-\+]+)\):(\d+), '
            r'DTX (\d+), current_Qm (\d+), current_RI (\d+), total_bytes RX/SCHED (\d+)/(\d+)',
            line2
        )
        if m2:
            ulsch_entry.update({
                'round_trials': [
                    {'trials': int(m2.group(1)), 'value': float(m2.group(2))},
                    {'trials': int(m2.group(3)), 'value': float(m2.group(4))},
                    {'trials': int(m2.group(5)), 'value': float(m2.group(6))},
                    {'trials': int(m2.group(7))}
                ],
                'DTX': int(m2.group(8)),
                'current_Qm': int(m2.group(9)),
                'current_RI': int(m2.group(10)),
                'total_bytes_RX': int(m2.group(11)),
                'total_bytes_SCHED': int(m2.group(12))
            })
        return ulsch_entry, index + 2  # Skip the next line as it was parsed
    else:
        return None, index + 1


def parse_nrL1(data):
    """Main function to parse the file content."""
    result = {}
    lines = data.strip().split('\n')
    n = len(lines)
    i = 0  # Line index

    # Ignore 'Blacklisted PRBs' line if present
    if i < n and lines[i].startswith('Blacklisted PRBs'):
        i += 1  # Skip this line

    # Parse PRB values
    prb_values, i = parse_prb_values(lines, i)
    #result['prb_values'] = prb_values

    # Parse 'max_IO', 'min_I0', 'avg_I0' line
    if i < n and lines[i].startswith('max_IO'):
        io_values = parse_io_values(lines[i])
        if io_values:
            result['IO_values'] = io_values
        i += 1

    # Parse 'PRACH I0' line
    if i < n and lines[i].startswith('PRACH I0'):
        prach_i0 = parse_prach_i0(lines[i])
        if prach_i0 is not None:
            result['PRACH_I0'] = prach_i0
        i += 1

    # Initialize lists for DLSCH and ULSCH data
    result['DLSCH'] = []
    result['ULSCH'] = []

    # Parse the remaining lines
    while i < n:
        line = lines[i].strip()
        if line.startswith('DLSCH RNTI'):
            dlsch_entry = parse_dlsch_line(line)
            if dlsch_entry:
                result['DLSCH'].append(dlsch_entry)
            i += 1
        elif line.startswith('ULSCH RNTI'):
            ulsch_entry, new_index = parse_ulsch_line(lines, i)
            if ulsch_entry:
                result['ULSCH'].append(ulsch_entry)
            i = new_index
        else:
            # Skip unknown lines
            i += 1

    return result


def parse_nrRRC(data):
    """Parses the file content and returns a dictionary with UEs and DUs."""
    lines = data.strip().split('\n')
    n = len(lines)
    i = 0
    UEs = []
    DUs = []

    # Regular expression patterns to match lines in the file
    ue_header_pattern = re.compile(
        r'UE (\d+) CU UE ID (\d+) DU UE ID (\d+) RNTI (\w+) random identity (\w+) S-TMSI (\w+):'
    )
    last_rrc_activity_pattern = re.compile(r'last RRC activity: (\d+) seconds ago')
    pdu_session_pattern = re.compile(r'PDU session (\d+) ID (\d+) status (\w+)')
    associated_du_pattern = re.compile(r'associated DU: (.+)')
    du_header_pattern = re.compile(
        r'\[(\d+)\] DU ID (\d+)( \(([^)]+)\))? integrated DU-CU: nrCellID (\d+), PCI (\d+), SSB ARFCN (\d+)'
    )
    tdd_pattern = re.compile(
        r'TDD: band (\d+) ARFCN (\d+) SCS (\d+) \(kHz\) PRB (\d+)'
    )

    # Parse UEs
    while i < n:
        line = lines[i].strip()
        ue_match = ue_header_pattern.match(line)
        if ue_match:
            # Extract UE information
            ue_index = int(ue_match.group(1))
            cu_ue_id = int(ue_match.group(2))
            du_ue_id = int(ue_match.group(3))
            rnti = ue_match.group(4)
            random_identity = ue_match.group(5)
            s_tmsi = ue_match.group(6)

            i += 1  # Move to next line
            last_rrc_activity_seconds = None
            PDU_sessions = []
            associated_DU = None

            # Parse indented lines for additional UE details
            while i < n and lines[i].startswith('    '):
                sub_line = lines[i].strip()
                last_rrc_match = last_rrc_activity_pattern.match(sub_line)
                pdu_session_match = pdu_session_pattern.match(sub_line)
                associated_du_match = associated_du_pattern.match(sub_line)
                if last_rrc_match:
                    last_rrc_activity_seconds = int(last_rrc_match.group(1))
                elif pdu_session_match:
                    session_number = int(pdu_session_match.group(1))
                    ID = int(pdu_session_match.group(2))
                    status = pdu_session_match.group(3)
                    PDU_sessions.append({
                        'session_number': session_number,
                        'ID': ID,
                        'status': status
                    })
                elif associated_du_match:
                    associated_DU = associated_du_match.group(1).strip()
                i += 1

            # Append the UE entry to the list
            UEs.append({
                'UE_index': ue_index,
                'CU_UE_ID': cu_ue_id,
                'DU_UE_ID': du_ue_id,
                'RNTI': rnti,
                'random_identity': random_identity,
                'S_TMSI': s_tmsi,
                'last_RRC_activity_seconds': last_rrc_activity_seconds,
                'PDU_sessions': PDU_sessions,
                'associated_DU': associated_DU
            })
        elif line.endswith('connected DUs'):
            i += 1  # Skip the line and move to DU parsing
            break
        else:
            i += 1

    # Parse DUs
    while i < n:
        line = lines[i].strip()
        du_match = du_header_pattern.match(line)
        if du_match:
            # Extract DU information
            du_index = int(du_match.group(1))
            du_id = int(du_match.group(2))
            name = du_match.group(4) if du_match.group(4) else None
            integrated_du_cu = True  # Since 'integrated DU-CU' is in the pattern
            nrCellID = int(du_match.group(5))
            PCI = int(du_match.group(6))
            SSB_ARFCN = int(du_match.group(7))

            i += 1  # Move to next line
            TDD_band = None
            TDD_ARFCN = None
            TDD_SCS = None
            TDD_PRB = None

            # Parse TDD information if present
            if i < n and lines[i].startswith('    TDD:'):
                tdd_line = lines[i].strip()
                tdd_match = tdd_pattern.match(tdd_line)
                if tdd_match:
                    TDD_band = int(tdd_match.group(1))
                    TDD_ARFCN = int(tdd_match.group(2))
                    TDD_SCS = int(tdd_match.group(3))
                    TDD_PRB = int(tdd_match.group(4))
                i += 1

            # Append the DU entry to the list
            DUs.append({
                'DU_index': du_index,
                'DU_ID': du_id,
                'name': name,
                'integrated_DU_CU': integrated_du_cu,
                'nrCellID': nrCellID,
                'PCI': PCI,
                'SSB_ARFCN': SSB_ARFCN,
                'TDD_band': TDD_band,
                'TDD_ARFCN': TDD_ARFCN,
                'TDD_SCS': TDD_SCS,
                'TDD_PRB': TDD_PRB
            })
        else:
            i += 1

    # Return the parsed data as a dictionary
    return {'UEs': UEs, 'DUs': DUs}


def send_to_api(data, endpoint):
    headers = {'Content-Type': 'application/json'}
    try:
        response = requests.post(API_ENDPOINT+endpoint, json=data, headers=headers)
        response.raise_for_status()
        print('Data sent successfully:', response.json())
    except requests.exceptions.HTTPError as errh:
        print('HTTP Error:', errh)
    except requests.exceptions.ConnectionError as errc:
        print('Error Connecting:', errc)
    except requests.exceptions.Timeout as errt:
        print('Timeout Error:', errt)
    except requests.exceptions.RequestException as err:
        print('An Error Occurred:', err)

class EventHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if '.log' in event.src_path:
            with open(event.src_path, 'r') as fr:
                log_line = {}
                log_line['time'] = time.time()
                log_line['file'] = event.src_path
                log_line['content'] = fr.read()
                if(log_line['file']=='./nrL1_stats.log'):
                    nrL1 = parse_nrL1(log_line['content'])
                    send_to_api(nrL1, "loggerL1/")
                if(log_line['file']=='./nrMAC_stats.log'):
                    nrMAC = []
                    UEs = log_line['content'].split("UE RNTI")
                    for ue in UEs[1:]:
                        j_ue = parse_nrMAC("UE RNTI"+ue)
                        nrMAC.append(j_ue)
                    pprint(nrMAC)
                    send_to_api(nrMAC, "loggerMAC/")
                if(log_line['file']=='./nrRRC_stats.log'):
                    nrRRC = parse_nrRRC(log_line['content'])
                    print(nrRRC)
                    send_to_api(nrRRC, "loggerRRC/")
                #with output_lock:
                #    output_log.write(f"{json.dumps(log_line)}\n")
                #    output_log.flush()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S')
    path = sys.argv[1] if len(sys.argv) > 1 else '.'
    logging.info(f'start watching directory {path!r}')
    observer = Observer()
    event_handler = EventHandler()
    observer.schedule(event_handler, path, recursive=False)
    observer.start()
    output_log = open('all_stats.log', 'w')
    output_lock = Lock()
    log_array = []
    try:
        while True:
            time.sleep(1)
    finally:
        observer.stop()
        observer.join()
        # with open('all_logs.pickle', 'wb') as pf:
        #     pickle.dump(log_array, pf)





#!/usr/bin/env python
#
# Copyright 2010-2014 Ettus Research LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import socket
import struct

########################################################################
# constants
########################################################################
X300_FW_COMMS_UDP_PORT = 49152

X300_FW_COMMS_FLAGS_ACK = 1
X300_FW_COMMS_FLAGS_ERROR = 2
X300_FW_COMMS_FLAGS_POKE32 = 4
X300_FW_COMMS_FLAGS_PEEK32 = 8

X300_FIXED_PORTS = 5

X300_ZPU_MISC_SR_BUS_OFFSET = 0xA000
X300_ZPU_XBAR_SR_BUS_OFFSET = 0xB000

# Settings register bus addresses (hangs off ZPU wishbone bus)
# Multiple by 4 as ZPU wishbone bus is word aligned
X300_SR_NUM_CE = X300_ZPU_MISC_SR_BUS_OFFSET + 4*7
X300_SR_RB_ADDR_XBAR = X300_ZPU_MISC_SR_BUS_OFFSET + 4*128
# Readback addresses
X300_RB_CROSSBAR = X300_ZPU_MISC_SR_BUS_OFFSET + 4*128

#UDP_CTRL_PORT = 49183
UDP_MAX_XFER_BYTES = 1024
UDP_TIMEOUT = 3

#REG_ARGS_FMT = '!LLLLLB15x'
#REG_IP_FMT = '!LLLL20x'
REG_PEEK_POKE_FMT = '!LLLL'

_seq = -1


def seq():
    global _seq
    _seq = _seq+1
    return _seq


########################################################################
# helper functions
########################################################################

def unpack_reg_peek_poke_fmt(s):
    return struct.unpack(REG_PEEK_POKE_FMT, s)  # (flags, seq, addr, data)


def pack_reg_peek_poke_fmt(flags, seq, addr, data):
    return struct.pack(REG_PEEK_POKE_FMT, flags, seq, addr, data)

########################################################################
# Burner class, holds a socket and send/recv routines
########################################################################


class ctrl_socket(object):
    def __init__(self, addr):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(UDP_TIMEOUT)
        self._sock.connect((addr, X300_FW_COMMS_UDP_PORT))
        self.set_callbacks(lambda *a: None, lambda *a: None)
        # self.init_update() #check that the device is there

    def set_callbacks(self, progress_cb, status_cb):
        self._progress_cb = progress_cb
        self._status_cb = status_cb

    def send_and_recv(self, pkt):
        self._sock.send(pkt)
        return self._sock.recv(UDP_MAX_XFER_BYTES)

    def poke_print(self, poke_addr, poke_data):
        print("POKE of address %d(0x%x) with %d(0x%x)" % (poke_addr, poke_addr, poke_data, poke_data))
        return(self.poke(poke_addr, poke_data))

    def poke(self, poke_addr, poke_data):
        out_pkt = pack_reg_peek_poke_fmt(X300_FW_COMMS_FLAGS_POKE32 | X300_FW_COMMS_FLAGS_ACK, seq(), poke_addr, poke_data)
        in_pkt = self.send_and_recv(out_pkt)
        (flags, rxseq, addr, data) = unpack_reg_peek_poke_fmt(in_pkt)
        if flags & X300_FW_COMMS_FLAGS_ERROR == X300_FW_COMMS_FLAGS_ERROR:
            raise Exception("X300 peek of address %d returns error code" % (addr))
        return data

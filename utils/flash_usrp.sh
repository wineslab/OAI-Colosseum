#!/bin/bash

cd /root/vivado_colosseum/
source setupenv.sh
/root/vivado_colosseum/tools/scripts/launch_vivado.sh -mode batch -source /root/vivado_colosseum/tools/scripts/viv_hardware_utils.tcl -nolog -nojournal -tclargs program /usr/local/share/uhd/images/usrp_x310_fpga_HGS.bit | grep -v -E '(^$|^#|\*\*)'


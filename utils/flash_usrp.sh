#!/bin/bash

source /opt/vivado_colosseum/setupenv.sh
/opt/vivado_colosseum/tools/scripts/launch_vivado.sh -mode batch -source /opt/vivado_colosseum/tools/scripts/viv_hardware_utils.tcl -nolog -nojournal -tclargs program /usr/local/share/uhd/images/usrp_x310_fpga_HGS.bit | grep -v -E '(^$|^#|\*\*)'
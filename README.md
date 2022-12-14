# OpenAirInterface on Colosseum

This repository contains some tools and configurations made to run OpenAirInterface (OAI) on the [Colosseum testbed](https://www.northeastern.edu/colosseum/)

## Core

TODO

## RAN

### How to run OAI

1. Install the dependencies using pip `pip -r requirements.txt`
2. Copy the env file and eventually adapt it `cp .env.colosseum .env`
3. Run the UE or the gNB by calling `python ran.py`

### Configuration parameters

- `--numerology` or `-n` sets the subcarrier spacing (0 for 15khz, 1 for 30khz and so on)
- `--prb` or `-p` sets the number of Resource Blocks (24,51,106, etc)
- `--channel` or `-c` sets the channel number. See the conf.json to see the different available channels
- `--type` or `-t` sets the node role among '[ue', 'donor','relay', 'du', 'cu']
- `--gdb` run OAI under gdb for debug purposes
- `--numa` runs OAI under a specific NUMA policy that improves its performances on multiprocessor machines
- `flash` or `-f` flash the USRP using vivado prior to running it.
- `--if_freq` runs the gNB or UE using an intermediate frequency of 1GHz.

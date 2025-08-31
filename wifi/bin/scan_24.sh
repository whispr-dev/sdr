#!/usr/bin/env bash
set -euo pipefail
python3 /home/wofl/sdr/wifi/wifi_scan.py --band 24 --rate 20e6 --nsamp 2000000 --gain 40 --png --outdir /home/wofl/sdr/wifi/out

#!/usr/bin/env bash
set -euo pipefail
python3 /home/wofl/sdr/wifi/wifi_live_fft.py \
  --band 24 --channel 6 \
  --rate 40e6 --fft 4096 --overlap 0.5 \
  --gain 55 --bw 20e6 \
  --lna-path LNAH --lna 30 --tia 9 --pga 16 \
  --wf-rows 240 --avg 0.6

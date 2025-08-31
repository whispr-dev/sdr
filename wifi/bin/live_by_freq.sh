#!/usr/bin/env bash
set -euo pipefail
# Tune directly by frequency (Hz) instead of channel map.
# Example: ch 1 center ~ 2.412 GHz
python3 /home/wofl/sdr/wifi/wifi_live_fft.py \
  --freq 2412000000 \
  --rate 20e6 --fft 4096 --overlap 0.5 \
  --gain 55 --bw 20e6 \
  --lna-path LNAH --lna 30 --tia 9 --pga 16 \
  --wf-rows 240 --avg 0.6

#!/usr/bin/env bash
set -euo pipefail
python3 /home/wofl/sdr/wifi/zigbee_sweep.py \
  --rate 10000000 --gain 55 --lna 30 --tia 9 --pga 16 --lna-path LNAH \
  --seconds 1.5 --nfft 4096 --estimate-period-k 1 --period-seconds 20 \
  --outdir /home/wofl/sdr/wifi/zigbee_out

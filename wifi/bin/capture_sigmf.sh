#!/usr/bin/env bash
set -euo pipefail
# Usage:
#   capture_sigmf.sh <center_Hz> <samp_rate_Hz> <seconds> <gain_dB> <outdir>
# Example (40 MHz around ch6 2437 MHz for 30 s):
#   capture_sigmf.sh 2437000000 40000000 30 55 /home/wofl/sdr/wifi/captures

CF="${1:-2437000000}"
SR="${2:-40000000}"
SECS="${3:-30}"
GAIN="${4:-55}"
OUTDIR="${5:-/home/wofl/sdr/wifi/captures}"

mkdir -p "$OUTDIR"
python3 /home/wofl/sdr/wifi/wifi_record_channel.py \
  --band 24 --channel 6 \
  --rate "$SR" --seconds "$SECS" --gain "$GAIN" \
  --driver lime --outdir "$OUTDIR" \
  --channels /home/wofl/sdr/wifi/wifi_channels_uk.json \
  --bw "$SR" \
  || true

# The recorder names by band/channel; if you want exact CF naming, use --freq variant below:
# python3 /home/wofl/sdr/wifi/wifi_record_channel.py --band 24 --channel 6 ...

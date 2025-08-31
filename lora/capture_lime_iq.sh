#!/usr/bin/env bash
set -euo pipefail

OUTDIR="/home/wofl/sdr/captures"
mkdir -p "$OUTDIR"

FREQ="${FREQ:-868100000}"   # 868.1 MHz
RATE="${RATE:-5000000}"     # 5 MS/s default; try 10000000 or 30720000 if stable
DUR="${DUR:-10}"            # seconds
FMT="${FMT:-cs16}"          # cs16 or cf32
GAIN="${GAIN:-50}"          # or per-stage "LNA,TIA,PGA", e.g., "35,9,20"
BW="${BW:-0}"               # 0 = leave to driver; else e.g. 1500000
ANT="${ANT:-LNAW}"          # Lime ports: LNAW/LNAH/LNAL

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BASE="lime_${FREQ}Hz_${RATE}sps_${DUR}s_${FMT}_${STAMP}"
OUT="$OUTDIR/${BASE}.${FMT}"

echo "[*] Capturing: f=${FREQ} Hz  rate=${RATE} sps  dur=${DUR}s  fmt=${FMT}  gain=${GAIN}  ant=${ANT}"
python3 /home/wofl/sdr/capture_iq_soapysdr.py \
  --device "driver=lime" \
  --freq "$FREQ" \
  --rate "$RATE" \
  --dur "$DUR" \
  --fmt "$FMT" \
  --gain "$GAIN" \
  --ant "$ANT" \
  --out "$OUT" \
  --meta \
  ${BW:+--bw "$BW"}

echo "[+] Wrote $OUT"

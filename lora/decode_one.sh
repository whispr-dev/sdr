#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   /home/wofl/sdr/decode_one.sh /home/wofl/sdr/captures/<file>.cfile|.cs16

infile="${1:-}"
if [[ -z "$infile" || ! -f "$infile" ]]; then
  echo "ERR: input file missing. Usage: decode_one.sh <file.cfile|file.cs16>" >&2
  exit 1
fi

APP="/home/wofl/sdr/lora_rx_from_file.py"
OUTDIR="${OUTDIR:-/home/wofl/sdr/decoded}"
mkdir -p "$OUTDIR"

# sample rate: prefer sidecar JSON, else RATE env, else 1e6
json="${infile}.json"
if [[ -f "$json" ]] && command -v jq >/dev/null 2>&1; then
  RATE="$(jq -r '(.rate_sps // .sample_rate_hz // .sample_rate // 1000000)' "$json")"
else
  RATE="${RATE:-1000000}"
fi

FREQ="${FREQ:-868100000}"
SFS="${SFS:-7 8 9 10 11 12}"
BWS="${BWS:-125e3 250e3 500e3}"
CR="${CR:-4/5}"
SWAPIQ="${SWAPIQ:-0}"

# infer format from extension
ext="${infile##*.}"
case "$ext" in
  cfile|cf32) FMT="cf32" ;;
  cs16)       FMT="s16"  ;;
  *)          FMT="cf32" ;;
esac

base="$(basename "$infile")"
stem="${base%.*}"
args="file=${infile},rate=${RATE},format=${FMT}"

echo "[*] Decoder: $APP"
echo "[*] Input  : $infile"
echo "[*] Rate   : $RATE"
echo "[*] Freq   : $FREQ"
echo "[*] Format : $FMT"
echo "[*] Sweep  : SF=($SFS)  BW=($BWS)  CR=$CR  SWAPIQ=$SWAPIQ"
echo

success=0
for sf in $SFS; do
  for bw in $BWS; do
    tag="sf${sf}_bw${bw//[^0-9]/}"
    outphy="${OUTDIR}/${stem}_${tag}.phy"
    outlog="${OUTDIR}/${stem}_${tag}.log"
    echo " -> SF=$sf BW=$bw"
    set +e
    python3 "$APP" \
      --args="$args" \
      --sf="$sf" --cr="$CR" --bw="$bw" --freq="$FREQ" \
      --output="$outphy" \
      $( [[ "$SWAPIQ" = "1" ]] && echo --swap-iq ) \
      2>&1 | tee "$outlog"
    rc=${PIPESTATUS[0]}
    set -e
    if [[ -s "$outphy" ]]; then
      echo "    OK: $outphy"
      success=1
    else
      rm -f "$outphy"
    fi
  done
done

if [[ "$success" -eq 0 ]]; then
  echo "[!] No packets decoded for $infile. See logs in $OUTDIR/${stem}_*.log"
else
  echo "[+] Done. See $OUTDIR/${stem}_*.phy"
fi

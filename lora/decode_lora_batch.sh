#!/usr/bin/env bash
set -euo pipefail
OUTDIR="${OUTDIR:-/home/wofl/sdr/decoded}"
mkdir -p "$OUTDIR"

shopt -s nullglob
files=(/home/wofl/sdr/captures/*.cfile /home/wofl/sdr/captures/*.cs16)
if (( ${#files[@]} == 0 )); then
  echo "No capture files found under /home/wofl/sdr/captures"
  exit 0
fi

for f in "${files[@]}"; do
  /home/wofl/sdr/decode_one.sh "$f"
done

echo "[*] All files processed. Outputs in $OUTDIR"

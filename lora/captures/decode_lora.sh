#!/usr/bin/env bash
set -euo pipefail

INPUT_DIR="/home/wofl/sdr"
OUTPUT_DIR="/home/wofl/sdr/decoded"
APP="/usr/src/gr-lora_sdr/apps/lora_rx_from_file.py"

mkdir -p "$OUTPUT_DIR"

# spreading factors, bandwidths, coding rate to sweep
SFS=(7 8 9 10 11 12)
BWS=(125e3 250e3 500e3)
CR="4/5"

for infile in "$INPUT_DIR"/lime_*Hz_*sps_*_cf32_*.cfile; do
    [ -f "$infile" ] || continue
    base=$(basename "$infile" .cfile)
    echo "[*] Decoding $base.cfile ..."
    for sf in "${SFS[@]}"; do
        for bw in "${BWS[@]}"; do
            outfile="$OUTPUT_DIR/${base}_sf${sf}_bw${bw}_out.phy"
            echo "    -> SF=$sf BW=$bw CR=$CR => $outfile"
            python3 "$APP" \
                --args="fcd=file=$infile,rate=1000000" \
                --sf=$sf --cr=$CR --bw=$bw --freq=868100000 \
                --output="$outfile" \
                2>&1 | tee "$OUTPUT_DIR/${base}_sf${sf}_bw${bw}.log"
        done
    done
done

echo "[*] All files processed. Outputs in $OUTPUT_DIR"

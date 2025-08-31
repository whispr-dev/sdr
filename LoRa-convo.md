nice catch, fren. let’s set you up with a SoapySDR-driven IQ recorder that targets your LimeSDR Mini 2.0 at 868.1 MHz, with a knob for “as fast as it’ll go,” and produces files Gqrx can play (CS16 or CF32 interleaved IQ).



below are full, ready-to-use artifacts (filenames + absolute paths), plus the exact commands to run.



0\) install deps (Ubuntu/Debian on the SDR box)

\# Bash (WSL/Ubuntu):

sudo apt update

sudo apt install -y \\

&nbsp; gqrx-sdr \\

&nbsp; soapysdr-tools python3-soapysdr python3-numpy \\

&nbsp; soapysdr-module-lms7 \\

&nbsp; limesuite lime-utils





quick hardware sanity:



LimeUtil --find

SoapySDRUtil --probe "driver=lime"



1\) recorder script (SoapySDR → IQ file)

file: /home/wofl/sdr/capture\_iq\_soapysdr.py

\#!/usr/bin/env python3

import argparse, json, time, os, sys

import numpy as np

import SoapySDR

from SoapySDR import SOAPY\_SDR\_RX, SOAPY\_SDR\_CF32, SOAPY\_SDR\_CS16



def parse\_gain(g):

&nbsp;   try:

&nbsp;       return float(g)

&nbsp;   except:

&nbsp;       return None



def main():

&nbsp;   ap = argparse.ArgumentParser(description="LimeSDR Mini IQ capture (SoapySDR) for Gqrx")

&nbsp;   ap.add\_argument("--device", default="driver=lime", help='Soapy device string (default: "driver=lime")')

&nbsp;   ap.add\_argument("--freq", type=float, default=868.1e6, help="Center frequency in Hz (default 868.1e6)")

&nbsp;   ap.add\_argument("--rate", type=float, default=5e6, help="Sample rate in S/s (try 5e6..10e6..30.72e6 if stable)")

&nbsp;   ap.add\_argument("--bw",   type=float, default=None, help="Analog filter bandwidth in Hz (optional)")

&nbsp;   ap.add\_argument("--gain", default="50", help='Overall gain dB or per-stage "LNA,TIA,PGA" (e.g., "35,9,20")')

&nbsp;   ap.add\_argument("--ant",  default="LNAW", help='RX antenna name (Lime: LNAW/LNAH/LNAL). Default LNAW.')

&nbsp;   ap.add\_argument("--dur",  type=float, default=10.0, help="Duration seconds")

&nbsp;   ap.add\_argument("--fmt",  choices=\["cs16","cf32"], default="cs16", help="Output sample format (Gqrx likes both)")

&nbsp;   ap.add\_argument("--out",  required=True, help="Output file path (e.g., /home/wofl/sdr/captures/clip.cs16)")

&nbsp;   ap.add\_argument("--meta", action="store\_true", help="Write JSON sidecar with capture parameters")

&nbsp;   ap.add\_argument("--agc",  action="store\_true", help="Enable AGC (off by default)")

&nbsp;   ap.add\_argument("--dc",   action="store\_true", help="Enable DC offset correction")

&nbsp;   ap.add\_argument("--iqbal",action="store\_true", help="Enable IQ balance correction")

&nbsp;   ap.add\_argument("--buflen", type=int, default=1<<18, help="Stream buffer length (samples per read)")

&nbsp;   args = ap.parse\_args()



&nbsp;   os.makedirs(os.path.dirname(args.out), exist\_ok=True)



&nbsp;   # make device

&nbsp;   sdr = SoapySDR.Device(args.device)



&nbsp;   # set channel 0

&nbsp;   ch = 0

&nbsp;   sdr.setAntenna(SOAPY\_SDR\_RX, ch, args.ant)



&nbsp;   # gains

&nbsp;   if "," in args.gain:

&nbsp;       parts = args.gain.split(",")

&nbsp;       names = \["LNA","TIA","PGA"]

&nbsp;       for name, val in zip(names, parts):

&nbsp;           try:

&nbsp;               sdr.setGainElement(SOAPY\_SDR\_RX, ch, name, float(val))

&nbsp;           except Exception:

&nbsp;               pass

&nbsp;   else:

&nbsp;       g = parse\_gain(args.gain)

&nbsp;       if g is not None:

&nbsp;           sdr.setGain(SOAPY\_SDR\_RX, ch, g)



&nbsp;   # helpers

&nbsp;   try:

&nbsp;       sdr.setFrequency(SOAPY\_SDR\_RX, ch, args.freq)

&nbsp;   except Exception as e:

&nbsp;       print(f"setFrequency failed: {e}", file=sys.stderr); sys.exit(1)



&nbsp;   sdr.setSampleRate(SOAPY\_SDR\_RX, ch, args.rate)

&nbsp;   if args.bw:

&nbsp;       sdr.setBandwidth(SOAPY\_SDR\_RX, ch, args.bw)



&nbsp;   try:

&nbsp;       sdr.setGainMode(SOAPY\_SDR\_RX, ch, bool(args.agc))

&nbsp;   except Exception:

&nbsp;       pass

&nbsp;   try:

&nbsp;       sdr.setDCOffsetMode(SOAPY\_SDR\_RX, ch, bool(args.dc))

&nbsp;   except Exception:

&nbsp;       pass

&nbsp;   try:

&nbsp;       sdr.setIQBalance(SOAPY\_SDR\_RX, ch, 1.0 if args.iqbal else 0.0)

&nbsp;   except Exception:

&nbsp;       pass



&nbsp;   # choose stream format

&nbsp;   if args.fmt == "cf32":

&nbsp;       fmt = SOAPY\_SDR\_CF32

&nbsp;       dtype = np.complex64

&nbsp;   else:

&nbsp;       fmt = SOAPY\_SDR\_CS16

&nbsp;       dtype = np.int16  # we will write I/Q int16 interleaved



&nbsp;   # build and activate stream

&nbsp;   st = sdr.setupStream(SOAPY\_SDR\_RX, fmt, \[ch])

&nbsp;   sdr.activateStream(st)



&nbsp;   # writer

&nbsp;   fout = open(args.out, "wb", buffering=0)



&nbsp;   start = time.time()

&nbsp;   total\_samps = 0



&nbsp;   # helper to write buffer

&nbsp;   def write\_buf(buf):

&nbsp;       nonlocal total\_samps

&nbsp;       if fmt == SOAPY\_SDR\_CF32:

&nbsp;           # Soapy gives np.complex64 directly

&nbsp;           fout.write(buf.astype(np.complex64).view(np.float32).tobytes())

&nbsp;           total\_samps += buf.size

&nbsp;       else:

&nbsp;           # Soapy returns np.int16 interleaved as I and Q already

&nbsp;           # Some drivers return shape (N,2) int16; normalize to 1-D interleaved

&nbsp;           if buf.ndim == 2 and buf.shape\[1] == 2:

&nbsp;               inter = buf.reshape(-1)

&nbsp;               fout.write(inter.tobytes())

&nbsp;               total\_samps += buf.shape\[0]

&nbsp;           else:

&nbsp;               # Already interleaved 1-D int16 stream

&nbsp;               fout.write(buf.tobytes())

&nbsp;               total\_samps += buf.size // 2



&nbsp;   buf = np.empty(args.buflen, dtype=dtype)



&nbsp;   try:

&nbsp;       while (time.time() - start) < args.dur:

&nbsp;           sr = sdr.readStream(st, \[buf], args.buflen, timeoutUs=int(0.5e6))

&nbsp;           if sr.ret > 0:

&nbsp;               write\_buf(buf\[:sr.ret])

&nbsp;           elif sr.ret == 0:

&nbsp;               continue

&nbsp;           else:

&nbsp;               # negative => error code

&nbsp;               print(f"readStream error: {sr.ret}", file=sys.stderr)

&nbsp;               break

&nbsp;   finally:

&nbsp;       sdr.deactivateStream(st)

&nbsp;       sdr.closeStream(st)

&nbsp;       fout.close()



&nbsp;   if args.meta:

&nbsp;       meta = {

&nbsp;           "device": args.device,

&nbsp;           "freq\_hz": args.freq,

&nbsp;           "rate\_sps": args.rate,

&nbsp;           "bandwidth\_hz": args.bw,

&nbsp;           "antenna": args.ant,

&nbsp;           "gain": args.gain,

&nbsp;           "duration\_s": args.dur,

&nbsp;           "format": args.fmt,

&nbsp;           "samples\_captured": int(total\_samps),

&nbsp;           "file": os.path.abspath(args.out),

&nbsp;           "timestamp\_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),

&nbsp;           "agc": bool(args.agc),

&nbsp;           "dc\_correction": bool(args.dc),

&nbsp;           "iq\_balance": bool(args.iqbal),

&nbsp;       }

&nbsp;       with open(args.out + ".json", "w") as jf:

&nbsp;           json.dump(meta, jf, indent=2)



&nbsp;   print(f"Done. Samples: {total\_samps}  ->  {args.out}")



if \_\_name\_\_ == "\_\_main\_\_":

&nbsp;   main()





make it executable:



mkdir -p /home/wofl/sdr/captures

chmod +x /home/wofl/sdr/capture\_iq\_soapysdr.py



2\) convenience launcher (shell)

file: /home/wofl/sdr/capture\_lime\_iq.sh

\#!/usr/bin/env bash

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

BASE="lime\_${FREQ}Hz\_${RATE}sps\_${DUR}s\_${FMT}\_${STAMP}"

OUT="$OUTDIR/${BASE}.${FMT}"



echo "\[\*] Capturing: f=${FREQ} Hz  rate=${RATE} sps  dur=${DUR}s  fmt=${FMT}  gain=${GAIN}  ant=${ANT}"

python3 /home/wofl/sdr/capture\_iq\_soapysdr.py \\

&nbsp; --device "driver=lime" \\

&nbsp; --freq "$FREQ" \\

&nbsp; --rate "$RATE" \\

&nbsp; --dur "$DUR" \\

&nbsp; --fmt "$FMT" \\

&nbsp; --gain "$GAIN" \\

&nbsp; --ant "$ANT" \\

&nbsp; --out "$OUT" \\

&nbsp; --meta \\

&nbsp; ${BW:+--bw "$BW"}



echo "\[+] Wrote $OUT"





make it executable:



chmod +x /home/wofl/sdr/capture\_lime\_iq.sh



3\) run examples

a) safe, solid capture (good for most laptops/USB3)

\# 10 seconds @ 5 MS/s, 868.1 MHz, CS16 interleaved IQ

FREQ=868100000 RATE=5000000 DUR=10 FMT=cs16 GAIN=50 /home/wofl/sdr/capture\_lime\_iq.sh



b) push it harder

\# Try 10 MS/s (watch CPU/USB throughput and dropped samples)

FREQ=868100000 RATE=10000000 DUR=8 FMT=cs16 GAIN=50 /home/wofl/sdr/capture\_lime\_iq.sh





note: LimeSDR Mini 2.0 can clock very high (e.g., 30.72 MS/s), but USB/host stability can be the limiter. if you see readStream underruns or discontinuities, back the rate down (10 → 8 → 6 → 5 MS/s) or reduce --buflen/increase it depending on your RAM/USB behavior.



4\) play in Gqrx



start Gqrx.



in the I/O device dialog, choose “File” device.



pick your file (e.g., /home/wofl/sdr/captures/lime\_868100000Hz\_5000000sps\_10s\_cs16\_\*.cs16).



set Sample rate to the exact rate you captured (e.g., 5000000).



set Filter/demod as desired (or just visualize FFT/waterfall).



if you want the waterfall centered correctly, set “Input frequency” to 868100000 (purely cosmetic for file playback).



Gqrx formats:



cs16 here = signed 16-bit IQ interleaved (I0,Q0,I1,Q1,...) — Gqrx handles this.



If you used cf32, Gqrx also supports 32-bit float IQ (.cfile convention), and you can just rename the extension to .cfile for clarity.



5\) good Lime settings at 868 MHz



Antenna: LNAW works well for 868 MHz.



Gains: start --gain 50 (or per-stage like --gain "35,9,20").



Bandwidth: optional --bw 1500000 or --bw 2000000 to tighten analog filtering around LoRa BW while keeping headroom.



DC/IQ correction: add --dc --iqbal if you see a fat DC spike or IQ imbalance.



quick “as fast as it’ll go” shot



Try (and fall back if it glitches):



\# attempt very high rate (may be unstable on some hosts)

FREQ=868100000 RATE=30720000 DUR=4 FMT=cs16 GAIN=45 /home/wofl/sdr/capture\_lime\_iq.sh

\# if you get overruns, step down:

FREQ=868100000 RATE=20000000 DUR=5 FMT=cs16 GAIN=45 /home/wofl/sdr/capture\_lime\_iq.sh

FREQ=868100000 RATE=10000000 DUR=8 FMT=cs16 GAIN=45 /home/wofl/sdr/capture\_lime\_iq.sh





want me to add an auto-LoRa channel scanner variant that sweeps the EU868 uplink channels and drops a separate file per hit? I can wire it onto the same framework.


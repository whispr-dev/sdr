file: /home/wofl/sdr/lora\_scan\_capture.py

\#!/usr/bin/env python3

"""

EU868 LoRa channel scanner + trigger capture for LimeSDR Mini 2.0 (SoapySDR).



\- Scans a list of center frequencies (default: EU868 LoRaWAN uplink channels).

\- Per channel, listens for bursts using short-time RMS vs adaptive noise floor.

\- On trigger, writes a CS16 interleaved IQ file (Gqrx-friendly) with pre/post roll.

\- Writes a .json sidecar with all capture parameters and trigger stats.



Notes:

\- Designed for LimeSDR Mini 2.0 via SoapySDR (driver=lime).

\- Sample rate defaults to 5e6; you can push higher if your USB/host can handle it.

\- Use LNAW antenna for 868 MHz by default.

\- This is NOT a LoRa decoder. It records IQ so you can analyze/playback later.



Author: you + fren

"""



import argparse

import json

import os

import sys

import time

from collections import deque

from datetime import datetime, timezone



import numpy as np

import SoapySDR

from SoapySDR import SOAPY\_SDR\_RX, SOAPY\_SDR\_CS16



\# ---------- Helpers ----------



def utc\_stamp():

&nbsp;   return datetime.utcnow().replace(tzinfo=timezone.utc).strftime("%Y%m%dT%H%M%SZ")



def db10(x):

&nbsp;   return 10.0 \* np.log10(np.maximum(x, 1e-30))



def moving\_percentile(x, p):

&nbsp;   # Robust percentile for noise floor estimation

&nbsp;   return np.percentile(x, p)



def ensure\_dir(path):

&nbsp;   os.makedirs(path, exist\_ok=True)



def parse\_gain\_string(s):

&nbsp;   """

&nbsp;   Accept either a single numeric gain in dB, or per-stage "LNA,TIA,PGA".

&nbsp;   Returns a dict {mode: 'overall'|'per', overall:float, elems:{LNA,TIA,PGA}}.

&nbsp;   """

&nbsp;   if "," in s:

&nbsp;       parts = s.split(",")

&nbsp;       out = {"mode":"per","elems":{}}

&nbsp;       names = \["LNA","TIA","PGA"]

&nbsp;       for name,val in zip(names,parts):

&nbsp;           out\["elems"]\[name] = float(val)

&nbsp;       return out

&nbsp;   else:

&nbsp;       return {"mode":"overall","overall":float(s)}



\# ---------- Core Scanner ----------



class SoapyLimeScanner:

&nbsp;   def \_\_init\_\_(self, args):

&nbsp;       self.args = args

&nbsp;       self.sdr = SoapySDR.Device(args.device)

&nbsp;       self.ch = 0



&nbsp;       # Configure RF front-end

&nbsp;       self.sdr.setAntenna(SOAPY\_SDR\_RX, self.ch, args.antenna)

&nbsp;       # Gain

&nbsp;       g = parse\_gain\_string(args.gain)

&nbsp;       if g\["mode"] == "overall":

&nbsp;           self.sdr.setGain(SOAPY\_SDR\_RX, self.ch, g\["overall"])

&nbsp;       else:

&nbsp;           for k,v in g\["elems"].items():

&nbsp;               try:

&nbsp;                   self.sdr.setGainElement(SOAPY\_SDR\_RX, self.ch, k, v)

&nbsp;               except Exception:

&nbsp;                   pass



&nbsp;       # Sample rate \& bandwidth

&nbsp;       self.sdr.setSampleRate(SOAPY\_SDR\_RX, self.ch, args.rate)

&nbsp;       if args.bandwidth > 0:

&nbsp;           self.sdr.setBandwidth(SOAPY\_SDR\_RX, self.ch, args.bandwidth)



&nbsp;       # Optional corrections

&nbsp;       try: self.sdr.setGainMode(SOAPY\_SDR\_RX, self.ch, args.agc)

&nbsp;       except Exception: pass

&nbsp;       try: self.sdr.setDCOffsetMode(SOAPY\_SDR\_RX, self.ch, args.dc)

&nbsp;       except Exception: pass

&nbsp;       try: self.sdr.setIQBalance(SOAPY\_SDR\_RX, self.ch, 1.0 if args.iqbal else 0.0)

&nbsp;       except Exception: pass



&nbsp;       # Stream: CS16 interleaved (I,Q int16)

&nbsp;       self.stream = self.sdr.setupStream(SOAPY\_SDR\_RX, SOAPY\_SDR\_CS16, \[self.ch])

&nbsp;       self.buflen = args.buflen

&nbsp;       self.buf = np.empty(self.buflen\*2, dtype=np.int16)  # I,Q interleaved

&nbsp;       self.active = False



&nbsp;       # Pre/post buffers in raw int16 IQ (interleaved)

&nbsp;       self.pre\_int16 = deque(maxlen=int(args.pre\_seconds \* args.rate \* 2))

&nbsp;       self.post\_hold\_samples = int(args.post\_seconds \* args.rate)  # complex samples

&nbsp;       self.max\_capture\_samples = int(args.max\_capture\_s \* args.rate)  # complex samples



&nbsp;       # Energy estimation buffers

&nbsp;       self.win\_samps = max(256, int(args.energy\_window\_s \* args.rate))  # samples per RMS window

&nbsp;       self.hop\_samps = max(128, int(args.energy\_hop\_s    \* args.rate))

&nbsp;       self.recent\_energies = deque(maxlen=args.noise\_est\_windows)

&nbsp;       self.last\_trigger\_time = 0.0



&nbsp;       ensure\_dir(args.outdir)



&nbsp;   def set\_freq(self, freq\_hz):

&nbsp;       self.sdr.setFrequency(SOAPY\_SDR\_RX, self.ch, float(freq\_hz))

&nbsp;       # Small settle

&nbsp;       time.sleep(self.args.tune\_settle\_s)



&nbsp;   def activate(self):

&nbsp;       if not self.active:

&nbsp;           self.sdr.activateStream(self.stream)

&nbsp;           self.active = True



&nbsp;   def deactivate(self):

&nbsp;       if self.active:

&nbsp;           self.sdr.deactivateStream(self.stream)

&nbsp;           self.active = False



&nbsp;   def close(self):

&nbsp;       try:

&nbsp;           self.deactivate()

&nbsp;       finally:

&nbsp;           self.sdr.closeStream(self.stream)



&nbsp;   # --- Energy / trigger logic on raw CS16 buffer ---



&nbsp;   def \_iter\_frames(self):

&nbsp;       """Yield successive chunks of interleaved int16 IQ with timestamps (host time)."""

&nbsp;       while True:

&nbsp;           sr = self.sdr.readStream(self.stream, \[self.buf], self.buflen, timeoutUs=int(500e3))

&nbsp;           t = time.time()

&nbsp;           if sr.ret > 0:

&nbsp;               yield t, self.buf\[:sr.ret\*2]  # int16 interleaved (I,Q)

&nbsp;           elif sr.ret == 0:

&nbsp;               continue

&nbsp;           else:

&nbsp;               # Negative = error code

&nbsp;               print(f"\[readStream] error: {sr.ret}", file=sys.stderr)

&nbsp;               return



&nbsp;   def \_cs16\_to\_rms(self, iq\_int16):

&nbsp;       """

&nbsp;       Compute RMS over a sliding window on interleaved int16 IQ.

&nbsp;       Returns a list of window energies (float) and last tail for overlap handling.

&nbsp;       """

&nbsp;       # Convert to float in \[-1, 1)

&nbsp;       iq = iq\_int16.astype(np.float32).view(np.float32)

&nbsp;       # "view(np.float32)" doesn't convert; we need to interleave to complex quickly:

&nbsp;       # reshape to (N,2) then to complex

&nbsp;       iq\_pairs = iq\_int16.reshape(-1,2).astype(np.float32)

&nbsp;       iq\_pairs /= 32768.0

&nbsp;       i = iq\_pairs\[:,0]

&nbsp;       q = iq\_pairs\[:,1]

&nbsp;       x = i\*i + q\*q  # instantaneous power per sample



&nbsp;       w = self.win\_samps

&nbsp;       h = self.hop\_samps

&nbsp;       if len(x) < w:

&nbsp;           return np.empty(0, dtype=np.float32)



&nbsp;       out = \[]

&nbsp;       for start in range(0, len(x)-w+1, h):

&nbsp;           seg = x\[start:start+w]

&nbsp;           out.append(np.sqrt(np.mean(seg)))

&nbsp;       return np.array(out, dtype=np.float32)



&nbsp;   def \_update\_noise\_floor(self, energies):

&nbsp;       if energies.size == 0:

&nbsp;           return None, None

&nbsp;       # store recent windows for robust floor

&nbsp;       self.recent\_energies.extend(energies.tolist())

&nbsp;       if len(self.recent\_energies) < self.recent\_energies.maxlen:

&nbsp;           return None, None

&nbsp;       noise\_floor = moving\_percentile(self.recent\_energies, self.args.noise\_percentile)

&nbsp;       thr = noise\_floor \* (10\*\*(self.args.trigger\_db\_over\_floor/20.0))

&nbsp;       return noise\_floor, thr



&nbsp;   # --- Recording ---



&nbsp;   def \_write\_cs16(self, fh, chunk):

&nbsp;       fh.write(chunk.tobytes())



&nbsp;   def run\_channel(self, freq\_hz, dwell\_s):

&nbsp;       """

&nbsp;       Monitor a single center frequency for up to dwell\_s.

&nbsp;       On trigger, record CS16 IQ with pre/post roll and max-capture guard.

&nbsp;       Returns number of captures on this channel.

&nbsp;       """

&nbsp;       self.set\_freq(freq\_hz)

&nbsp;       self.activate()



&nbsp;       st = time.time()

&nbsp;       captures = 0



&nbsp;       # clear buffers/energy history for this channel

&nbsp;       self.pre\_int16.clear()

&nbsp;       self.recent\_energies.clear()



&nbsp;       # recording state

&nbsp;       recording = False

&nbsp;       post\_left = 0           # complex samples remaining for post-roll

&nbsp;       wrote\_samples = 0       # complex samples written

&nbsp;       fh = None

&nbsp;       meta = None



&nbsp;       for host\_ts, chunk in self.\_iter\_frames():

&nbsp;           # maintain prebuffer (interleaved int16)

&nbsp;           self.pre\_int16.extend(chunk.tolist())



&nbsp;           # energy windows

&nbsp;           energies = self.\_cs16\_to\_rms(chunk)

&nbsp;           noise\_floor, thr = self.\_update\_noise\_floor(energies)



&nbsp;           # evaluate trigger only once noise floor known

&nbsp;           trig\_now = False

&nbsp;           if noise\_floor is not None:

&nbsp;               # if any window exceeds threshold => trigger

&nbsp;               if energies.size and np.any(energies > thr):

&nbsp;                   trig\_now = True



&nbsp;           # start recording

&nbsp;           if trig\_now and not recording:

&nbsp;               captures += 1

&nbsp;               # Build filenames

&nbsp;               stamp = utc\_stamp()

&nbsp;               base = f"EU868\_{int(freq\_hz)}Hz\_{int(self.args.rate)}sps\_{self.args.fmt}\_{stamp}\_cap{captures:02d}"

&nbsp;               out\_iq = os.path.join(self.args.outdir, base + ".cs16")

&nbsp;               out\_js = out\_iq + ".json"



&nbsp;               fh = open(out\_iq, "wb", buffering=0)

&nbsp;               # Write prebuffer (truncate to full I/Q pairs)

&nbsp;               pre\_arr = np.frombuffer(np.array(self.pre\_int16, dtype=np.int16).tobytes(), dtype=np.int16)

&nbsp;               pre\_arr = pre\_arr\[: (len(pre\_arr)//2)\*2]

&nbsp;               if pre\_arr.size:

&nbsp;                   self.\_write\_cs16(fh, pre\_arr)

&nbsp;                   wrote\_samples = pre\_arr.size // 2

&nbsp;               else:

&nbsp;                   wrote\_samples = 0



&nbsp;               meta = {

&nbsp;                   "device": self.args.device,

&nbsp;                   "freq\_hz": float(freq\_hz),

&nbsp;                   "rate\_sps": float(self.args.rate),

&nbsp;                   "bandwidth\_hz": float(self.args.bandwidth),

&nbsp;                   "antenna": self.args.antenna,

&nbsp;                   "gain": self.args.gain,

&nbsp;                   "format": "cs16",

&nbsp;                   "timestamp\_utc": stamp,

&nbsp;                   "pre\_seconds": float(self.args.pre\_seconds),

&nbsp;                   "post\_seconds": float(self.args.post\_seconds),

&nbsp;                   "energy\_window\_s": float(self.args.energy\_window\_s),

&nbsp;                   "energy\_hop\_s": float(self.args.energy\_hop\_s),

&nbsp;                   "trigger\_db\_over\_floor": float(self.args.trigger\_db\_over\_floor),

&nbsp;                   "noise\_percentile": float(self.args.noise\_percentile),

&nbsp;                   "tune\_settle\_s": float(self.args.tune\_settle\_s),

&nbsp;                   "channel\_list": self.args.channels,

&nbsp;                   "output\_file": out\_iq

&nbsp;               }



&nbsp;               # prime post-hold

&nbsp;               post\_left = self.post\_hold\_samples

&nbsp;               recording = True

&nbsp;               # Reset prebuffer so next capture starts fresh

&nbsp;               self.pre\_int16.clear()



&nbsp;           # continue recording

&nbsp;           if recording:

&nbsp;               # write current chunk

&nbsp;               fh.write(chunk.tobytes())

&nbsp;               wrote\_samples += chunk.size // 2



&nbsp;               # update hold time: if energies are above threshold, reset hold

&nbsp;               if noise\_floor is not None and energies.size and np.any(energies > thr):

&nbsp;                   post\_left = self.post\_hold\_samples

&nbsp;               else:

&nbsp;                   # decrease post-left by complex samples present in this chunk

&nbsp;                   post\_left -= chunk.size // 2



&nbsp;               # stop conditions

&nbsp;               if post\_left <= 0 or wrote\_samples >= self.max\_capture\_samples:

&nbsp;                   fh.close()

&nbsp;                   # write sidecar with counts

&nbsp;                   meta\["samples\_captured\_complex"] = int(wrote\_samples)

&nbsp;                   meta\["duration\_s\_est"] = wrote\_samples / float(self.args.rate)

&nbsp;                   with open(out\_js, "w") as jf:

&nbsp;                       json.dump(meta, jf, indent=2)

&nbsp;                   print(f"\[+] Saved capture: {meta\['output\_file']}  ~{meta\['duration\_s\_est']:.3f}s")

&nbsp;                   recording = False

&nbsp;                   fh = None

&nbsp;                   wrote\_samples = 0

&nbsp;                   post\_left = 0



&nbsp;           # dwell timeout

&nbsp;           if (time.time() - st) >= dwell\_s:

&nbsp;               # if still recording, finalize

&nbsp;               if recording and fh is not None:

&nbsp;                   fh.close()

&nbsp;                   meta\["samples\_captured\_complex"] = int(wrote\_samples)

&nbsp;                   meta\["duration\_s\_est"] = wrote\_samples / float(self.args.rate)

&nbsp;                   with open(out\_js, "w") as jf:

&nbsp;                       json.dump(meta, jf, indent=2)

&nbsp;                   print(f"\[+] Saved capture (dwell end): {meta\['output\_file']}  ~{meta\['duration\_s\_est']:.3f}s")

&nbsp;                   recording = False

&nbsp;               break



&nbsp;       return captures



\# ---------- Main ----------



def main():

&nbsp;   ap = argparse.ArgumentParser(description="EU868 LoRa channel scanner + auto capture (LimeSDR Mini, SoapySDR)")

&nbsp;   ap.add\_argument("--device", default="driver=lime", help='Soapy device string, e.g. "driver=lime"')

&nbsp;   ap.add\_argument("--rate", type=float, default=5e6, help="Sample rate (S/s), e.g. 5e6, 10e6")

&nbsp;   ap.add\_argument("--bandwidth", type=float, default=0.0, help="Analog filter bandwidth (Hz), 0 to leave default")

&nbsp;   ap.add\_argument("--gain", default="50", help='Overall gain dB or per-stage "LNA,TIA,PGA"')

&nbsp;   ap.add\_argument("--antenna", default="LNAW", help="Antenna port (LNAW/LNAH/LNAL). Default LNAW")

&nbsp;   ap.add\_argument("--agc", action="store\_true", help="Enable AGC")

&nbsp;   ap.add\_argument("--dc", action="store\_true", help="Enable DC offset correction")

&nbsp;   ap.add\_argument("--iqbal", action="store\_true", help="Enable IQ balance correction")



&nbsp;   # Channel plan

&nbsp;   ap.add\_argument("--channels", nargs="+", type=float,

&nbsp;                   default=\[868.1e6, 868.3e6, 868.5e6, 867.1e6, 867.3e6, 867.5e6, 867.7e6, 867.9e6],

&nbsp;                   help="List of center freqs in Hz to scan")



&nbsp;   ap.add\_argument("--dwell", type=float, default=6.0, help="Seconds to listen per channel (per pass)")

&nbsp;   ap.add\_argument("--passes", type=int, default=999999, help="Number of scan passes (large number ~= run forever)")

&nbsp;   ap.add\_argument("--tune\_settle\_s", type=float, default=0.05, help="Seconds to wait after tuning")



&nbsp;   # Triggering

&nbsp;   ap.add\_argument("--energy-window-s", type=float, default=0.010, help="RMS window length (s)")

&nbsp;   ap.add\_argument("--energy-hop-s",    type=float, default=0.005, help="RMS hop length (s)")

&nbsp;   ap.add\_argument("--noise-percentile", type=float, default=20.0, help="Percentile for noise floor estimate (robust)")

&nbsp;   ap.add\_argument("--trigger-db-over-floor", type=float, default=8.0, help="Trigger when energy exceeds floor + dB")



&nbsp;   # Capture shaping

&nbsp;   ap.add\_argument("--pre-seconds", type=float, default=0.30, help="Pre-trigger audio to save (s)")

&nbsp;   ap.add\_argument("--post-seconds", type=float, default=0.40, help="Post-trigger hold if energy drops (s)")

&nbsp;   ap.add\_argument("--max-capture-s", type=float, default=4.0, help="Max capture length per hit (s)")



&nbsp;   # IO buffers

&nbsp;   ap.add\_argument("--buflen", type=int, default=(1<<16), help="Samples per stream read (complex, not interleaved count)")

&nbsp;   ap.add\_argument("--outdir", default="/home/wofl/sdr/captures", help="Output directory for IQ files")



&nbsp;   args = ap.parse\_args()



&nbsp;   ensure\_dir(args.outdir)

&nbsp;   print("\[\*] Starting EU868 scan with params:")

&nbsp;   for k,v in sorted(vars(args).items()):

&nbsp;       if k in ("device", "antenna", "gain", "outdir"):

&nbsp;           print(f"    {k}: {v}")

&nbsp;       else:

&nbsp;           print(f"    {k}: {v}")



&nbsp;   scanner = SoapyLimeScanner(args)



&nbsp;   total\_caps = 0

&nbsp;   try:

&nbsp;       for p in range(1, args.passes+1):

&nbsp;           print(f"\[\*] Scan pass {p}/{args.passes} — channel loop")

&nbsp;           for f in args.channels:

&nbsp;               print(f"    \[-] {int(f)} Hz dwell {args.dwell}s ...")

&nbsp;               caps = scanner.run\_channel(f, args.dwell)

&nbsp;               total\_caps += caps

&nbsp;   except KeyboardInterrupt:

&nbsp;       print("\\n\[!] Interrupted by user.")

&nbsp;   finally:

&nbsp;       scanner.close()

&nbsp;       print(f"\[=] Exiting. Total captures: {total\_caps}")



if \_\_name\_\_ == "\_\_main\_\_":

&nbsp;   main()





Make it executable:



chmod +x /home/wofl/sdr/lora\_scan\_capture.py



2\) Shell wrapper with sane defaults

file: /home/wofl/sdr/lora\_scan.sh

\#!/usr/bin/env bash

set -euo pipefail



OUTDIR="${OUTDIR:-/home/wofl/sdr/captures}"

RATE="${RATE:-5000000}"           # 5 MS/s to start. Push higher if stable (e.g. 10000000).

BW="${BW:-0}"                     # analog BW; 0 = leave default, or e.g. 1500000

GAIN="${GAIN:-50}"                # or "35,9,20" per LNA,TIA,PGA

ANT="${ANT:-LNAW}"                # LNAW is the wideband 50-ohm input (good at 868 MHz)

AGC="${AGC:-0}"                   # 1 to enable

DC="${DC:-1}"                     # 1 to enable DC correction

IQBAL="${IQBAL:-1}"               # 1 to enable IQ balance correction



DWELL="${DWELL:-6}"               # seconds per channel, per pass

PASSES="${PASSES:-999999}"        # big number ~ run "forever"

TUNE\_SETTLE="${TUNE\_SETTLE:-0.05}"



\# Trigger params

EWIN="${EWIN:-0.010}"             # energy window (s)

EHOP="${EHOP:-0.005}"             # hop (s)

NOISE\_PCT="${NOISE\_PCT:-20}"      # percentile to estimate floor

TRIG\_DB="${TRIG\_DB:-8.0}"         # dB above floor to trigger



\# Capture shaping

PRE\_S="${PRE\_S:-0.30}"

POST\_S="${POST\_S:-0.40}"

MAX\_CAP\_S="${MAX\_CAP\_S:-4.0}"



\# Channels (Hz) — EU868 LoRaWAN uplink set

CHANNELS="${CHANNELS:-868100000 868300000 868500000 867100000 867300000 867500000 867700000 867900000}"



mkdir -p "$OUTDIR"



python3 /home/wofl/sdr/lora\_scan\_capture.py \\

&nbsp; --device "driver=lime" \\

&nbsp; --rate "$RATE" \\

&nbsp; --bandwidth "$BW" \\

&nbsp; --gain "$GAIN" \\

&nbsp; --antenna "$ANT" \\

&nbsp; --dwell "$DWELL" \\

&nbsp; --passes "$PASSES" \\

&nbsp; --tune\_settle\_s "$TUNE\_SETTLE" \\

&nbsp; --energy-window-s "$EWIN" \\

&nbsp; --energy-hop-s "$EHOP" \\

&nbsp; --noise-percentile "$NOISE\_PCT" \\

&nbsp; --trigger-db-over-floor "$TRIG\_DB" \\

&nbsp; --pre-seconds "$PRE\_S" \\

&nbsp; --post-seconds "$POST\_S" \\

&nbsp; --max-capture-s "$MAX\_CAP\_S" \\

&nbsp; --buflen $((1<<16)) \\

&nbsp; --outdir "$OUTDIR" \\

&nbsp; $( \[ "$AGC" = "1" ] \&\& echo --agc ) \\

&nbsp; $( \[ "$DC" = "1" ] \&\& echo --dc ) \\

&nbsp; $( \[ "$IQBAL" = "1" ] \&\& echo --iqbal ) \\

&nbsp; --channels $CHANNELS





Make it executable:



chmod +x /home/wofl/sdr/lora\_scan.sh



3\) Run it

Straight defaults (robust)

/home/wofl/sdr/lora\_scan.sh



Push sample rate harder (watch USB/CPU; step down if overruns)

RATE=10000000 /home/wofl/sdr/lora\_scan.sh

\# or:

RATE=20000000 /home/wofl/sdr/lora\_scan.sh



Tighten analog filter near LoRa BWs, enable AGC

BW=2000000 AGC=1 /home/wofl/sdr/lora\_scan.sh



More sensitive trigger (lower threshold), longer pre/post

TRIG\_DB=5.5 PRE\_S=0.5 POST\_S=0.6 /home/wofl/sdr/lora\_scan.sh





Captured files land in:



/home/wofl/sdr/captures/EU868\_<freq>Hz\_<rate>sps\_cs16\_<UTC>\_capNN.cs16

/home/wofl/sdr/captures/EU868\_<freq>Hz\_<rate>sps\_cs16\_<UTC>\_capNN.cs16.json





These .cs16 files are Gqrx-ready (File source → set sample rate to the recorded value; center frequency is purely cosmetic in file playback, but we encode it in the filename and JSON).



4\) Tips and tuning



If you see readStream error: -X or get choppy captures at high rates, step down RATE (10e6 → 8e6 → 6e6 → 5e6).



If you see a fat DC spike at center, keep DC=1.



If I/Q looks skewed, keep IQBAL=1.



The trigger is robust but simple. For even cleaner triggering around narrowband LoRa chirps, increase EWIN a bit (e.g., 0.015–0.020 s) so windows smooth over instantaneous fluctuations, and keep TRIG\_DB around 6–10 dB.



want me to add a CSV session log (one line per capture with freq, start time, length, max dB over floor) or a per-channel rotating capture limit? say the word and I’ll wire it in.


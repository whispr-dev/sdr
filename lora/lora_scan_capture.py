#!/usr/bin/env python3
"""
EU868 LoRa channel scanner + trigger capture for LimeSDR Mini 2.0 (SoapySDR).

- Scans a list of center frequencies (default: EU868 LoRaWAN uplink channels).
- Per channel, listens for bursts using short-time RMS vs adaptive noise floor.
- On trigger, writes a CS16 interleaved IQ file (Gqrx-friendly) with pre/post roll.
- Writes a .json sidecar with all capture parameters and trigger stats.

Notes:
- Designed for LimeSDR Mini 2.0 via SoapySDR (driver=lime).
- Sample rate defaults to 5e6; you can push higher if your USB/host can handle it.
- Use LNAW antenna for 868 MHz by default.
- This is NOT a LoRa decoder. It records IQ so you can analyze/playback later.

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
from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CS16

# ---------- Helpers ----------

def utc_stamp():
    return datetime.utcnow().replace(tzinfo=timezone.utc).strftime("%Y%m%dT%H%M%SZ")

def db10(x):
    return 10.0 * np.log10(np.maximum(x, 1e-30))

def moving_percentile(x, p):
    # Robust percentile for noise floor estimation
    return np.percentile(x, p)

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def parse_gain_string(s):
    """
    Accept either a single numeric gain in dB, or per-stage "LNA,TIA,PGA".
    Returns a dict {mode: 'overall'|'per', overall:float, elems:{LNA,TIA,PGA}}.
    """
    if "," in s:
        parts = s.split(",")
        out = {"mode":"per","elems":{}}
        names = ["LNA","TIA","PGA"]
        for name,val in zip(names,parts):
            out["elems"][name] = float(val)
        return out
    else:
        return {"mode":"overall","overall":float(s)}

# ---------- Core Scanner ----------

class SoapyLimeScanner:
    def __init__(self, args):
        self.args = args
        self.sdr = SoapySDR.Device(args.device)
        self.ch = 0

        # Configure RF front-end
        self.sdr.setAntenna(SOAPY_SDR_RX, self.ch, args.antenna)
        # Gain
        g = parse_gain_string(args.gain)
        if g["mode"] == "overall":
            self.sdr.setGain(SOAPY_SDR_RX, self.ch, g["overall"])
        else:
            for k,v in g["elems"].items():
                try:
                    self.sdr.setGainElement(SOAPY_SDR_RX, self.ch, k, v)
                except Exception:
                    pass

        # Sample rate & bandwidth
        self.sdr.setSampleRate(SOAPY_SDR_RX, self.ch, args.rate)
        if args.bandwidth > 0:
            self.sdr.setBandwidth(SOAPY_SDR_RX, self.ch, args.bandwidth)

        # Optional corrections
        try: self.sdr.setGainMode(SOAPY_SDR_RX, self.ch, args.agc)
        except Exception: pass
        try: self.sdr.setDCOffsetMode(SOAPY_SDR_RX, self.ch, args.dc)
        except Exception: pass
        try: self.sdr.setIQBalance(SOAPY_SDR_RX, self.ch, 1.0 if args.iqbal else 0.0)
        except Exception: pass

        # Stream: CS16 interleaved (I,Q int16)
        self.stream = self.sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CS16, [self.ch])
        self.buflen = args.buflen
        self.buf = np.empty(self.buflen*2, dtype=np.int16)  # I,Q interleaved
        self.active = False

        # Pre/post buffers in raw int16 IQ (interleaved)
        self.pre_int16 = deque(maxlen=int(args.pre_seconds * args.rate * 2))
        self.post_hold_samples = int(args.post_seconds * args.rate)  # complex samples
        self.max_capture_samples = int(args.max_capture_s * args.rate)  # complex samples

        # Energy estimation buffers
        self.win_samps = max(256, int(args.energy_window_s * args.rate))  # samples per RMS window
        self.hop_samps = max(128, int(args.energy_hop_s    * args.rate))
        self.recent_energies = deque(maxlen=args.noise_est_windows)
        self.last_trigger_time = 0.0

        ensure_dir(args.outdir)

    def set_freq(self, freq_hz):
        self.sdr.setFrequency(SOAPY_SDR_RX, self.ch, float(freq_hz))
        # Small settle
        time.sleep(self.args.tune_settle_s)

    def activate(self):
        if not self.active:
            self.sdr.activateStream(self.stream)
            self.active = True

    def deactivate(self):
        if self.active:
            self.sdr.deactivateStream(self.stream)
            self.active = False

    def close(self):
        try:
            self.deactivate()
        finally:
            self.sdr.closeStream(self.stream)

    # --- Energy / trigger logic on raw CS16 buffer ---

    def _iter_frames(self):
        """Yield successive chunks of interleaved int16 IQ with timestamps (host time)."""
        while True:
            sr = self.sdr.readStream(self.stream, [self.buf], self.buflen, timeoutUs=int(500e3))
            t = time.time()
            if sr.ret > 0:
                yield t, self.buf[:sr.ret*2]  # int16 interleaved (I,Q)
            elif sr.ret == 0:
                continue
            else:
                # Negative = error code
                print(f"[readStream] error: {sr.ret}", file=sys.stderr)
                return

    def _cs16_to_rms(self, iq_int16):
        """
        Compute RMS over a sliding window on interleaved int16 IQ.
        Returns a list of window energies (float) and last tail for overlap handling.
        """
        # Convert to float in [-1, 1)
        iq = iq_int16.astype(np.float32).view(np.float32)
        # "view(np.float32)" doesn't convert; we need to interleave to complex quickly:
        # reshape to (N,2) then to complex
        iq_pairs = iq_int16.reshape(-1,2).astype(np.float32)
        iq_pairs /= 32768.0
        i = iq_pairs[:,0]
        q = iq_pairs[:,1]
        x = i*i + q*q  # instantaneous power per sample

        w = self.win_samps
        h = self.hop_samps
        if len(x) < w:
            return np.empty(0, dtype=np.float32)

        out = []
        for start in range(0, len(x)-w+1, h):
            seg = x[start:start+w]
            out.append(np.sqrt(np.mean(seg)))
        return np.array(out, dtype=np.float32)

    def _update_noise_floor(self, energies):
        if energies.size == 0:
            return None, None
        # store recent windows for robust floor
        self.recent_energies.extend(energies.tolist())
        if len(self.recent_energies) < self.recent_energies.maxlen:
            return None, None
        noise_floor = moving_percentile(self.recent_energies, self.args.noise_percentile)
        thr = noise_floor * (10**(self.args.trigger_db_over_floor/20.0))
        return noise_floor, thr

    # --- Recording ---

    def _write_cs16(self, fh, chunk):
        fh.write(chunk.tobytes())

    def run_channel(self, freq_hz, dwell_s):
        """
        Monitor a single center frequency for up to dwell_s.
        On trigger, record CS16 IQ with pre/post roll and max-capture guard.
        Returns number of captures on this channel.
        """
        self.set_freq(freq_hz)
        self.activate()

        st = time.time()
        captures = 0

        # clear buffers/energy history for this channel
        self.pre_int16.clear()
        self.recent_energies.clear()

        # recording state
        recording = False
        post_left = 0           # complex samples remaining for post-roll
        wrote_samples = 0       # complex samples written
        fh = None
        meta = None

        for host_ts, chunk in self._iter_frames():
            # maintain prebuffer (interleaved int16)
            self.pre_int16.extend(chunk.tolist())

            # energy windows
            energies = self._cs16_to_rms(chunk)
            noise_floor, thr = self._update_noise_floor(energies)

            # evaluate trigger only once noise floor known
            trig_now = False
            if noise_floor is not None:
                # if any window exceeds threshold => trigger
                if energies.size and np.any(energies > thr):
                    trig_now = True

            # start recording
            if trig_now and not recording:
                captures += 1
                # Build filenames
                stamp = utc_stamp()
                base = f"EU868_{int(freq_hz)}Hz_{int(self.args.rate)}sps_{self.args.fmt}_{stamp}_cap{captures:02d}"
                out_iq = os.path.join(self.args.outdir, base + ".cs16")
                out_js = out_iq + ".json"

                fh = open(out_iq, "wb", buffering=0)
                # Write prebuffer (truncate to full I/Q pairs)
                pre_arr = np.frombuffer(np.array(self.pre_int16, dtype=np.int16).tobytes(), dtype=np.int16)
                pre_arr = pre_arr[: (len(pre_arr)//2)*2]
                if pre_arr.size:
                    self._write_cs16(fh, pre_arr)
                    wrote_samples = pre_arr.size // 2
                else:
                    wrote_samples = 0

                meta = {
                    "device": self.args.device,
                    "freq_hz": float(freq_hz),
                    "rate_sps": float(self.args.rate),
                    "bandwidth_hz": float(self.args.bandwidth),
                    "antenna": self.args.antenna,
                    "gain": self.args.gain,
                    "format": "cs16",
                    "timestamp_utc": stamp,
                    "pre_seconds": float(self.args.pre_seconds),
                    "post_seconds": float(self.args.post_seconds),
                    "energy_window_s": float(self.args.energy_window_s),
                    "energy_hop_s": float(self.args.energy_hop_s),
                    "trigger_db_over_floor": float(self.args.trigger_db_over_floor),
                    "noise_percentile": float(self.args.noise_percentile),
                    "tune_settle_s": float(self.args.tune_settle_s),
                    "channel_list": self.args.channels,
                    "output_file": out_iq
                }

                # prime post-hold
                post_left = self.post_hold_samples
                recording = True
                # Reset prebuffer so next capture starts fresh
                self.pre_int16.clear()

            # continue recording
            if recording:
                # write current chunk
                fh.write(chunk.tobytes())
                wrote_samples += chunk.size // 2

                # update hold time: if energies are above threshold, reset hold
                if noise_floor is not None and energies.size and np.any(energies > thr):
                    post_left = self.post_hold_samples
                else:
                    # decrease post-left by complex samples present in this chunk
                    post_left -= chunk.size // 2

                # stop conditions
                if post_left <= 0 or wrote_samples >= self.max_capture_samples:
                    fh.close()
                    # write sidecar with counts
                    meta["samples_captured_complex"] = int(wrote_samples)
                    meta["duration_s_est"] = wrote_samples / float(self.args.rate)
                    with open(out_js, "w") as jf:
                        json.dump(meta, jf, indent=2)
                    print(f"[+] Saved capture: {meta['output_file']}  ~{meta['duration_s_est']:.3f}s")
                    recording = False
                    fh = None
                    wrote_samples = 0
                    post_left = 0

            # dwell timeout
            if (time.time() - st) >= dwell_s:
                # if still recording, finalize
                if recording and fh is not None:
                    fh.close()
                    meta["samples_captured_complex"] = int(wrote_samples)
                    meta["duration_s_est"] = wrote_samples / float(self.args.rate)
                    with open(out_js, "w") as jf:
                        json.dump(meta, jf, indent=2)
                    print(f"[+] Saved capture (dwell end): {meta['output_file']}  ~{meta['duration_s_est']:.3f}s")
                    recording = False
                break

        return captures

# ---------- Main ----------

def main():
    ap = argparse.ArgumentParser(description="EU868 LoRa channel scanner + auto capture (LimeSDR Mini, SoapySDR)")
    ap.add_argument("--device", default="driver=lime", help='Soapy device string, e.g. "driver=lime"')
    ap.add_argument("--rate", type=float, default=5e6, help="Sample rate (S/s), e.g. 5e6, 10e6")
    ap.add_argument("--bandwidth", type=float, default=0.0, help="Analog filter bandwidth (Hz), 0 to leave default")
    ap.add_argument("--gain", default="50", help='Overall gain dB or per-stage "LNA,TIA,PGA"')
    ap.add_argument("--antenna", default="LNAW", help="Antenna port (LNAW/LNAH/LNAL). Default LNAW")
    ap.add_argument("--agc", action="store_true", help="Enable AGC")
    ap.add_argument("--dc", action="store_true", help="Enable DC offset correction")
    ap.add_argument("--iqbal", action="store_true", help="Enable IQ balance correction")

    # Channel plan
    ap.add_argument("--channels", nargs="+", type=float,
                    default=[868.1e6, 868.3e6, 868.5e6, 867.1e6, 867.3e6, 867.5e6, 867.7e6, 867.9e6],
                    help="List of center freqs in Hz to scan")

    ap.add_argument("--dwell", type=float, default=6.0, help="Seconds to listen per channel (per pass)")
    ap.add_argument("--passes", type=int, default=999999, help="Number of scan passes (large number ~= run forever)")
    ap.add_argument("--tune_settle_s", type=float, default=0.05, help="Seconds to wait after tuning")

    # Triggering
    ap.add_argument("--energy-window-s", type=float, default=0.010, help="RMS window length (s)")
    ap.add_argument("--energy-hop-s",    type=float, default=0.005, help="RMS hop length (s)")
    ap.add_argument("--noise-percentile", type=float, default=20.0, help="Percentile for noise floor estimate (robust)")
    ap.add_argument("--trigger-db-over-floor", type=float, default=8.0, help="Trigger when energy exceeds floor + dB")

    # Capture shaping
    ap.add_argument("--pre-seconds", type=float, default=0.30, help="Pre-trigger audio to save (s)")
    ap.add_argument("--post-seconds", type=float, default=0.40, help="Post-trigger hold if energy drops (s)")
    ap.add_argument("--max-capture-s", type=float, default=4.0, help="Max capture length per hit (s)")

    # IO buffers
    ap.add_argument("--buflen", type=int, default=(1<<16), help="Samples per stream read (complex, not interleaved count)")
    ap.add_argument("--outdir", default="/home/wofl/sdr/captures", help="Output directory for IQ files")

    args = ap.parse_args()

    ensure_dir(args.outdir)
    print("[*] Starting EU868 scan with params:")
    for k,v in sorted(vars(args).items()):
        if k in ("device", "antenna", "gain", "outdir"):
            print(f"    {k}: {v}")
        else:
            print(f"    {k}: {v}")

    scanner = SoapyLimeScanner(args)

    total_caps = 0
    try:
        for p in range(1, args.passes+1):
            print(f"[*] Scan pass {p}/{args.passes} — channel loop")
            for f in args.channels:
                print(f"    [-] {int(f)} Hz dwell {args.dwell}s ...")
                caps = scanner.run_channel(f, args.dwell)
                total_caps += caps
    except KeyboardInterrupt:
        print("\n[!] Interrupted by user.")
    finally:
        scanner.close()
        print(f"[=] Exiting. Total captures: {total_caps}")

if __name__ == "__main__":
    main()

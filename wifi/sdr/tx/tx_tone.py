#!/usr/bin/env python3
import argparse
import math
import signal
import sys
import time

import numpy as np
import SoapySDR
from SoapySDR import SOAPY_SDR_TX, SOAPY_SDR_CF32

# ---------------- Wi-Fi 2.4 GHz helper (centers) ----------------
WIFI24_CENTER_HZ = {
    1: 2412e6, 2: 2417e6, 3: 2422e6, 4: 2427e6, 5: 2432e6, 6: 2437e6,
    7: 2442e6, 8: 2447e6, 9: 2452e6, 10: 2457e6, 11: 2462e6, 12: 2467e6, 13: 2472e6
}

def pick_center(freq_hz: float, band: int, channel: int):
    if freq_hz is not None:
        return float(freq_hz)
    if band == 24 and channel in WIFI24_CENTER_HZ:
        return WIFI24_CENTER_HZ[channel]
    raise SystemExit("Specify --freq or a valid --band 24 --channel {1..13}")

def setup_sdr(center, rate, bw, gain, driver, tx_path, pad=None, iamp=None, antenna=None):
    sdr = SoapySDR.Device(dict(driver=driver))
    ch = 0

    # Select TX RF path for 2.4 GHz if available (BAND2 is typical for Lime at 2.4 GHz)
    # Some Soapy builds use TX_PATH, some TX_BAND.
    for key, val in (("TX_PATH", tx_path), ("TX_BAND", tx_path)):
        try:
            sdr.writeSetting(key, val)
        except Exception:
            pass

    if antenna:
        try:
            sdr.setAntenna(SOAPY_SDR_TX, ch, antenna)
        except Exception:
            pass

    sdr.setSampleRate(SOAPY_SDR_TX, ch, float(rate))
    if bw is None:
        bw = rate
    try:
        sdr.setBandwidth(SOAPY_SDR_TX, ch, float(bw))
    except Exception:
        pass

    # Frequency
    sdr.setFrequency(SOAPY_SDR_TX, ch, float(center))

    # Overall TX gain
    try:
        sdr.setGain(SOAPY_SDR_TX, ch, float(gain))
    except Exception:
        pass

    # Per-stage TX gains (if present)
    # Common Lime names: "PAD" (power amplifier driver), "IAMP"
    for name, val in (("PAD", pad), ("IAMP", iamp)):
        if val is None:
            continue
        try:
            sdr.setGainElement(SOAPY_SDR_TX, ch, name, float(val))
        except Exception:
            pass

    st = sdr.setupStream(SOAPY_SDR_TX, SOAPY_SDR_CF32, [ch])
    sdr.activateStream(st)
    return sdr, st, ch

def main():
    ap = argparse.ArgumentParser(description="LimeSDR-Mini v2: transmit a single complex tone.")
    # Centering
    ap.add_argument("--freq", type=float, help="Absolute center frequency in Hz")
    ap.add_argument("--band", type=int, default=24, help="24 for 2.4 GHz plan")
    ap.add_argument("--channel", type=int, help="Wi-Fi channel (1..13) -> center in Hz")
    # TX/RF
    ap.add_argument("--rate", type=float, default=2e6, help="Sample rate (Hz)")
    ap.add_argument("--bw", type=float, default=None, help="Analog bandwidth (Hz); default=rate")
    ap.add_argument("--gain", type=float, default=40.0, help="Overall TX gain (dB)")
    ap.add_argument("--pad", type=float, help="TX PAD gain (dB) if supported")
    ap.add_argument("--iamp", type=float, help="TX IAMP gain (dB) if supported")
    ap.add_argument("--tx-path", default="BAND2", help="TX path for 2.4 GHz (BAND2 is typical)")
    ap.add_argument("--antenna", default=None, help="TX antenna port name if available")
    ap.add_argument("--driver", default="lime", help="Soapy driver key")
    # Tone & duration
    ap.add_argument("--tone-hz", type=float, default=100e3, help="Baseband tone offset in Hz")
    ap.add_argument("--amplitude", type=float, default=0.2, help="Digital amplitude 0..1 (keep <0.5 to avoid clipping)")
    ap.add_argument("--seconds", type=float, default=5.0, help="Transmit duration (s)")
    args = ap.parse_args()

    if args.rate <= 0:
        raise SystemExit("rate must be > 0")
    if not (0.0 < args.amplitude <= 0.9):
        raise SystemExit("amplitude must be in (0, 0.9]")

    center = pick_center(args.freq, args.band, args.channel)

    # Build one-period chunk of the tone (loop it)
    rate = float(args.rate)
    tone = float(args.tone_hz)
    n = 4096  # buffer size per write
    t = np.arange(n, dtype=np.float32) / rate
    ph = 2 * math.pi * tone * t
    wave = (args.amplitude * (np.cos(ph) + 1j*np.sin(ph))).astype(np.complex64)

    sdr, st, ch = setup_sdr(center, rate, args.bw, args.gain, args.driver, args.tx_path,
                            pad=args.pad, iamp=args.iamp, antenna=args.antenna)

    print(f"TX @ {center/1e6:.3f} MHz, fs={rate/1e6:.3f} Msps, tone={tone/1e3:.1f} kHz, "
          f"gain={args.gain} dB, amp={args.amplitude}")

    stop = False
    def _sig(*_): 
        nonlocal stop; stop = True
    signal.signal(signal.SIGINT, _sig)

    t_end = time.time() + float(args.seconds)
    try:
        while not stop and time.time() < t_end:
            sr = sdr.writeStream(st, [wave], len(wave))
            if hasattr(sr, "ret"):
                if sr.ret <= 0:
                    continue
            elif isinstance(sr, (tuple, list)):
                if len(sr) == 0 or sr[0] <= 0:
                    continue
    finally:
        try:
            sdr.deactivateStream(st)
            sdr.closeStream(st)
        except Exception:
            pass

if __name__ == "__main__":
    main()

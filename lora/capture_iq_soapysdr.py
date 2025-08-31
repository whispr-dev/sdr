#!/usr/bin/env python3
import argparse, json, time, os, sys
import numpy as np
import SoapySDR
from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CF32, SOAPY_SDR_CS16

def parse_gain(g):
    try:
        return float(g)
    except:
        return None

def main():
    ap = argparse.ArgumentParser(description="LimeSDR Mini IQ capture (SoapySDR) for Gqrx")
    ap.add_argument("--device", default="driver=lime", help='Soapy device string (default: "driver=lime")')
    ap.add_argument("--freq", type=float, default=868.1e6, help="Center frequency in Hz (default 868.1e6)")
    ap.add_argument("--rate", type=float, default=5e6, help="Sample rate in S/s (try 5e6..10e6..30.72e6 if stable)")
    ap.add_argument("--bw",   type=float, default=None, help="Analog filter bandwidth in Hz (optional)")
    ap.add_argument("--gain", default="50", help='Overall gain dB or per-stage "LNA,TIA,PGA" (e.g., "35,9,20")')
    ap.add_argument("--ant",  default="LNAW", help='RX antenna name (Lime: LNAW/LNAH/LNAL). Default LNAW.')
    ap.add_argument("--dur",  type=float, default=10.0, help="Duration seconds")
    ap.add_argument("--fmt",  choices=["cs16","cf32"], default="cs16", help="Output sample format (Gqrx likes both)")
    ap.add_argument("--out",  required=True, help="Output file path (e.g., /home/wofl/sdr/captures/clip.cs16)")
    ap.add_argument("--meta", action="store_true", help="Write JSON sidecar with capture parameters")
    ap.add_argument("--agc",  action="store_true", help="Enable AGC (off by default)")
    ap.add_argument("--dc",   action="store_true", help="Enable DC offset correction")
    ap.add_argument("--iqbal",action="store_true", help="Enable IQ balance correction")
    ap.add_argument("--buflen", type=int, default=1<<16, help="Stream numElems per read (complex samples)")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    # open output before SDR (so a crash won’t leave 0-byte file uncreated)
    fout = open(args.out, "wb", buffering=0)

    # make device
    sdr = SoapySDR.Device(args.device)
    ch = 0
    sdr.setAntenna(SOAPY_SDR_RX, ch, args.ant)

    # gains
    if "," in args.gain:
        parts = args.gain.split(",")
        names = ["LNA","TIA","PGA"]
        for name, val in zip(names, parts):
            try:
                sdr.setGainElement(SOAPY_SDR_RX, ch, name, float(val))
            except Exception:
                pass
    else:
        g = parse_gain(args.gain)
        if g is not None:
            sdr.setGain(SOAPY_SDR_RX, ch, g)

    # tune & rates
    try:
        sdr.setFrequency(SOAPY_SDR_RX, ch, args.freq)
    except Exception as e:
        print(f"setFrequency failed: {e}", file=sys.stderr); sys.exit(1)

    sdr.setSampleRate(SOAPY_SDR_RX, ch, args.rate)
    if args.bw:
        sdr.setBandwidth(SOAPY_SDR_RX, ch, args.bw)

    # optional corrections
    try: sdr.setGainMode(SOAPY_SDR_RX, ch, bool(args.agc))
    except Exception: pass
    try: sdr.setDCOffsetMode(SOAPY_SDR_RX, ch, bool(args.dc))
    except Exception: pass
    try: sdr.setIQBalance(SOAPY_SDR_RX, ch, 1.0 if args.iqbal else 0.0)
    except Exception: pass

    # choose stream format
    if args.fmt == "cf32":
        fmt = SOAPY_SDR_CF32
        dtype = np.complex64
        # numElems = complex samples; buffer shape must be [numElems] complex64
        buf = np.empty(args.buflen, dtype=dtype)
    else:
        fmt = SOAPY_SDR_CS16
        dtype = np.int16
        # numElems = complex samples; each complex sample = 2x int16
        # allocate 2*buflen int16 to hold I/Q interleaved
        buf = np.empty(args.buflen * 2, dtype=dtype)

    st = sdr.setupStream(SOAPY_SDR_RX, fmt, [ch])
    sdr.activateStream(st)

    start = time.time()
    total_complex = 0  # count complex samples written

    try:
        while (time.time() - start) < args.dur:
            # numElems arg is in COMPLEX SAMPLES
            sr = sdr.readStream(st, [buf], args.buflen, timeoutUs=int(0.5e6))
            if sr.ret > 0:
                if fmt == SOAPY_SDR_CF32:
                    # view complex64 as float32 interleaved I/Q
                    fout.write(buf[:sr.ret].view(np.float32).tobytes())
                    total_complex += sr.ret
                else:
                    # CS16: driver gave interleaved int16 I/Q in a 1-D array of length 2*ret
                    count = sr.ret * 2
                    fout.write(buf[:count].tobytes())
                    total_complex += sr.ret
            elif sr.ret == 0:
                continue
            else:
                print(f"readStream error: {sr.ret}", file=sys.stderr)
                break
    finally:
        try:
            sdr.deactivateStream(st)
            sdr.closeStream(st)
        finally:
            fout.flush()
            fout.close()

    if args.meta:
        meta = {
            "device": args.device,
            "freq_hz": args.freq,
            "rate_sps": args.rate,
            "bandwidth_hz": args.bw,
            "antenna": args.ant,
            "gain": args.gain,
            "duration_s": args.dur,
            "format": args.fmt,
            "num_complex_samples": int(total_complex),
            "file": os.path.abspath(args.out),
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "agc": bool(args.agc),
            "dc_correction": bool(args.dc),
            "iq_balance": bool(args.iqbal),
            "buflen_complex": args.buflen
        }
        with open(args.out + ".json", "w") as jf:
            json.dump(meta, jf, indent=2)

    print(f"Done. Complex samples: {total_complex} -> {args.out}")

if __name__ == "__main__":
    main()

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
    ap.add_argument("--buflen", type=int, default=1<<18, help="Stream buffer length (samples per read)")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    # make device
    sdr = SoapySDR.Device(args.device)

    # set channel 0
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

    # helpers
    try:
        sdr.setFrequency(SOAPY_SDR_RX, ch, args.freq)
    except Exception as e:
        print(f"setFrequency failed: {e}", file=sys.stderr); sys.exit(1)

    sdr.setSampleRate(SOAPY_SDR_RX, ch, args.rate)
    if args.bw:
        sdr.setBandwidth(SOAPY_SDR_RX, ch, args.bw)

    try:
        sdr.setGainMode(SOAPY_SDR_RX, ch, bool(args.agc))
    except Exception:
        pass
    try:
        sdr.setDCOffsetMode(SOAPY_SDR_RX, ch, bool(args.dc))
    except Exception:
        pass
    try:
        sdr.setIQBalance(SOAPY_SDR_RX, ch, 1.0 if args.iqbal else 0.0)
    except Exception:
        pass

    # choose stream format
    if args.fmt == "cf32":
        fmt = SOAPY_SDR_CF32
        dtype = np.complex64
    else:
        fmt = SOAPY_SDR_CS16
        dtype = np.int16  # we will write I/Q int16 interleaved

    # build and activate stream
    st = sdr.setupStream(SOAPY_SDR_RX, fmt, [ch])
    sdr.activateStream(st)

    # writer
    fout = open(args.out, "wb", buffering=0)

    start = time.time()
    total_samps = 0

    # helper to write buffer
    def write_buf(buf):
        nonlocal total_samps
        if fmt == SOAPY_SDR_CF32:
            # Soapy gives np.complex64 directly
            fout.write(buf.astype(np.complex64).view(np.float32).tobytes())
            total_samps += buf.size
        else:
            # Soapy returns np.int16 interleaved as I and Q already
            # Some drivers return shape (N,2) int16; normalize to 1-D interleaved
            if buf.ndim == 2 and buf.shape[1] == 2:
                inter = buf.reshape(-1)
                fout.write(inter.tobytes())
                total_samps += buf.shape[0]
            else:
                # Already interleaved 1-D int16 stream
                fout.write(buf.tobytes())
                total_samps += buf.size // 2

    buf = np.empty(args.buflen, dtype=dtype)

    try:
        while (time.time() - start) < args.dur:
            sr = sdr.readStream(st, [buf], args.buflen, timeoutUs=int(0.5e6))
            if sr.ret > 0:
                write_buf(buf[:sr.ret])
            elif sr.ret == 0:
                continue
            else:
                # negative => error code
                print(f"readStream error: {sr.ret}", file=sys.stderr)
                break
    finally:
        sdr.deactivateStream(st)
        sdr.closeStream(st)
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
            "samples_captured": int(total_samps),
            "file": os.path.abspath(args.out),
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "agc": bool(args.agc),
            "dc_correction": bool(args.dc),
            "iq_balance": bool(args.iqbal),
        }
        with open(args.out + ".json", "w") as jf:
            json.dump(meta, jf, indent=2)

    print(f"Done. Samples: {total_samps}  ->  {args.out}")

if __name__ == "__main__":
    main()

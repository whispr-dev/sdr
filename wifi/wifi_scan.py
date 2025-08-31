#!/usr/bin/env python3
import argparse, json, time, sys, os
from pathlib import Path

import numpy as np
import SoapySDR
from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CF32

# Optional plotting
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAVE_PLOT = True
except Exception:
    HAVE_PLOT = False

VERSION = "wifi_scan.py v1.2 (fixed dBFS metric + LNA path)"
LIME_MAX_HZ = 3.8e9  # practical top-end for LimeSDR Mini v2

def welch_psd_dbfs(x, nfft=4096, overlap=0.5):
    """Return PSD (dBFS) without self-normalization (for plotting)."""
    x = np.asarray(x)
    win = np.hanning(nfft).astype(np.float32)
    step = max(1, int(nfft * (1.0 - overlap)))
    segs = []
    wpow = (win**2).sum()
    scale = 1.0 / (np.sum(win) if np.sum(win) != 0 else 1.0)
    for i in range(0, len(x) - nfft + 1, step):
        seg = x[i:i+nfft] * win
        # scaled FFT power spectrum
        X = np.fft.fftshift(np.fft.fft(seg))
        pxx = (np.abs(X)**2) / (nfft * wpow + 1e-12)
        segs.append(pxx)
    if not segs:
        return None
    psd = np.mean(np.stack(segs, axis=0), axis=0)
    # Assume Soapy CF32 ~ [-1,1], so full-scale power O(1). Good enough for *relative* dBFS ranking.
    return 10.0 * np.log10(psd + 1e-12)

def channel_rms_dbfs(iq: np.ndarray) -> float:
    """Time-domain RMS power in dBFS (relative to ~full-scale float)."""
    p = np.mean((iq.real**2 + iq.imag**2))
    return float(10.0 * np.log10(p + 1e-12))

def set_lime_gains(sdr, ch: int, overall_gain: float, lna=None, tia=None, pga=None):
    # Try overall first
    try:
        sdr.setGain(SOAPY_SDR_RX, ch, float(overall_gain))
    except Exception:
        pass
    # Optionally set per-stage (if available)
    try:
        if lna is not None: sdr.setGainElement(SOAPY_SDR_RX, ch, "LNA", float(lna))
    except Exception: pass
    try:
        if tia is not None: sdr.setGainElement(SOAPY_SDR_RX, ch, "TIA", float(tia))
    except Exception: pass
    try:
        if pga is not None: sdr.setGainElement(SOAPY_SDR_RX, ch, "PGA", float(pga))
    except Exception: pass

def open_sdr(driver, sample_rate, freq, gain, bw=None, lna_path=None, antenna=None, lna=None, tia=None, pga=None):
    if float(freq) > LIME_MAX_HZ:
        raise RuntimeError(f"Requested freq {freq/1e9:.3f} GHz exceeds LimeSDR Mini v2 limit (~{LIME_MAX_HZ/1e9:.1f} GHz).")
    sdr = SoapySDR.Device(dict(driver=driver))
    ch = 0

    # Antenna path / LNA path (names vary by stack; try both)
    if lna_path:
        for key in ("LNA_PATH", "RX_PATH"):
            try:
                sdr.writeSetting(key, lna_path)
            except Exception:
                pass
    if antenna:
        try:
            sdr.setAntenna(SOAPY_SDR_RX, ch, antenna)
        except Exception:
            pass

    sdr.setSampleRate(SOAPY_SDR_RX, ch, float(sample_rate))
    if bw is not None:
        try:
            sdr.setBandwidth(SOAPY_SDR_RX, ch, float(bw))
        except Exception:
            pass
    sdr.setFrequency(SOAPY_SDR_RX, ch, float(freq))
    set_lime_gains(sdr, ch, overall_gain=gain, lna=lna, tia=tia, pga=pga)
    return sdr

def _read_stream_compat(sdr, st, view, want, timeout_us=1_000_000):
    res = sdr.readStream(st, [view], want, timeoutUs=timeout_us)
    if hasattr(res, "ret"):  # StreamResult object
        return int(res.ret), int(getattr(res, "flags", 0))
    if isinstance(res, (tuple, list)) and len(res) >= 1:  # tuple form
        return int(res[0]), (int(res[1]) if len(res) >= 2 else 0)
    try:
        return int(res), 0
    except Exception:
        return 0, 0

def capture_iq(sdr, num_samples):
    ch = 0
    buf = np.empty(num_samples, dtype=np.complex64)
    st = sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32, [ch])
    sdr.activateStream(st)
    got, timeouts = 0, 0
    while got < num_samples:
        n = min(262144, num_samples - got)
        nread, _ = _read_stream_compat(sdr, st, buf[got:got+n], n)
        if nread > 0:
            got += nread
            timeouts = 0
        else:
            timeouts += 1
            if timeouts > 5:
                break
    sdr.deactivateStream(st)
    sdr.closeStream(st)
    return buf[:got]

def main():
    print(VERSION)
    ap = argparse.ArgumentParser(description="Per-channel Wi-Fi power scan (2.4/5 GHz) for LimeSDR via SoapySDR.")
    ap.add_argument("--channels", default="/home/wofl/sdr/wifi/wifi_channels_uk.json")
    ap.add_argument("--band", choices=["24","5","both"], default="both")
    ap.add_argument("--rate", type=float, default=20e6)
    ap.add_argument("--nsamp", type=int, default=2_000_000)
    ap.add_argument("--gain", type=float, default=50.0)  # a bit hotter by default
    ap.add_argument("--bw", type=float, default=20e6)
    ap.add_argument("--driver", default="lime")
    ap.add_argument("--outdir", default="/home/wofl/sdr/wifi/out")
    ap.add_argument("--png", action="store_true")
    ap.add_argument("--lna-path", default="LNAH", help="Lime LNA path: LNAH (2.4 GHz), LNAW, or LNAL")
    ap.add_argument("--antenna", default=None, help="Optional antenna name if Soapy exposes one (e.g., LNAH/LNAL/LNAW)")
    ap.add_argument("--lna", type=float, default=None, help="Optional LNA dB")
    ap.add_argument("--tia", type=float, default=None, help="Optional TIA dB (e.g., 0/3/9)")
    ap.add_argument("--pga", type=float, default=None, help="Optional PGA dB")
    args = ap.parse_args()

    Path(args.outdir).mkdir(parents=True, exist_ok=True)
    with open(args.channels, "r", encoding="utf-8") as f:
        chmap = json.load(f)

    def band24():
        return sorted([(int(k), int(v)) for k,v in chmap["band_24"]["channels"].items()], key=lambda t:t[0])
    def band5():
        return sorted([(int(k), int(v)) for k,v in chmap["band_5"]["non_dfs_channels"].items()], key=lambda t:t[0])

    todo = []
    if args.band in ("24","both"):
        todo += [("2.4GHz",) + t for t in band24()]
    if args.band in ("5","both"):
        todo += [("5GHz",) + t for t in band5()]

    csv_path = os.path.join(args.outdir, f"wifi_scan_{int(time.time())}.csv")
    with open(csv_path, "w", encoding="utf-8") as csv:
        csv.write("timestamp,band,channel,center_hz,sample_rate,nsamp,rel_power_dbfs\n")

        for band_name, chno, center in todo:
            if float(center) > LIME_MAX_HZ:
                ts = int(time.time())
                csv.write(f"{ts},{band_name},{chno},{center},{int(args.rate)},0,NaN\n")
                csv.flush()
                print(f"[skip] {band_name} ch{chno} @ {center/1e6:.3f} MHz > {LIME_MAX_HZ/1e9:.1f} GHz limit")
                continue

            sdr = open_sdr(
                args.driver, args.rate, center, args.gain, bw=args.bw,
                lna_path=args.lna_path, antenna=args.antenna,
                lna=args.lna, tia=args.tia, pga=args.pga
            )
            iq = capture_iq(sdr, args.nsamp)

            if iq.size:
                rel = channel_rms_dbfs(iq)  # THIS is the per-channel score
                psd_db = welch_psd_dbfs(iq) if args.png and HAVE_PLOT else None
            else:
                rel, psd_db = float("nan"), None

            ts = int(time.time())
            csv.write(f"{ts},{band_name},{chno},{center},{int(args.rate)},{iq.size},{rel:.2f}\n")
            csv.flush()

            if args.png and HAVE_PLOT and psd_db is not None:
                import matplotlib.pyplot as plt
                plt.figure()
                plt.plot(psd_db)
                plt.title(f"{band_name} ch{chno} @ {center/1e6:.3f} MHz")
                plt.xlabel("FFT bin"); plt.ylabel("Power (dBFS)")
                fpng = os.path.join(args.outdir, f"psd_{band_name}_ch{chno}_{center}.png")
                plt.savefig(fpng, dpi=130, bbox_inches="tight")
                plt.close()

    print(f"scan complete -> {csv_path}")

if __name__ == "__main__":
    main()

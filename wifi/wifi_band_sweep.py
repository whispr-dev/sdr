#!/usr/bin/env python3
import argparse, csv, time
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import SoapySDR
from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CF32

WIFI24 = {ch: 2.412e9 + (ch-1)*5e6 for ch in range(1,14)}  # ch1..13

def open_rx(rate, bw, gain, driver, lna_path, lna, tia, pga, antenna, center):
    sdr = SoapySDR.Device(dict(driver=driver))
    ch = 0
    for key in ("LNA_PATH","RX_PATH"):
        try: sdr.writeSetting(key, lna_path)
        except Exception: pass
    if antenna:
        try: sdr.setAntenna(SOAPY_SDR_RX, ch, antenna)
        except Exception: pass
    sdr.setSampleRate(SOAPY_SDR_RX, ch, float(rate))
    if bw is None: bw = rate
    try: sdr.setBandwidth(SOAPY_SDR_RX, ch, float(bw))
    except Exception: pass
    sdr.setFrequency(SOAPY_SDR_RX, ch, float(center))
    try: sdr.setGain(SOAPY_SDR_RX, ch, float(gain))
    except Exception: pass
    for name,val in (("LNA",lna),("TIA",tia),("PGA",pga)):
        if val is None: continue
        try: sdr.setGainElement(SOAPY_SDR_RX, ch, name, float(val))
        except Exception: pass
    st = sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32, [ch])
    sdr.activateStream(st)
    return sdr, st, ch

def read_stream_compat(sdr, st, view, want, timeout_us=1_000_000):
    res = sdr.readStream(st, [view], want, timeoutUs=timeout_us)
    if hasattr(res,"ret"): return int(res.ret), int(getattr(res,"flags",0))
    if isinstance(res,(tuple,list)):
        if not res: return 0,0
        return int(res[0]), int(res[1] if len(res)>1 else 0)
    try: return int(res),0
    except Exception: return 0,0

def psd_frame(iq, nfft):
    win = np.hanning(nfft).astype(np.float32)
    X = np.fft.fftshift(np.fft.fft(iq*win, n=nfft))
    pxx = (np.abs(X)**2) / (nfft + 1e-12)
    return 10.0*np.log10(pxx + 1e-12).astype(np.float32)

def bins_for_range(center_hz, span_hz, nfft, f0, f1):
    bin_bw = span_hz/nfft
    fstart = center_hz - span_hz/2
    b0 = int(np.floor((f0 - fstart)/bin_bw))
    b1 = int(np.ceil((f1 - fstart)/bin_bw))
    b0 = max(0, min(nfft, b0)); b1 = max(0, min(nfft, b1))
    if b1 < b0: b0,b1 = b1,b0
    return b0,b1

def apply_mutes(psd, center_hz, rate_hz, nfft, mute_ranges):
    if not mute_ranges: return psd
    out = psd.copy()
    floor = np.percentile(psd, 5)
    for f0,f1 in mute_ranges:
        b0,b1 = bins_for_range(center_hz, rate_hz, nfft, f0, f1)
        out[b0:b1] = floor
    return out

def sweep(args):
    outdir = Path(args.outdir).expanduser().resolve()
    (outdir / "plots").mkdir(parents=True, exist_ok=True)
    channels = sorted(set(args.channels or list(WIFI24.keys())))
    nfft = int(args.nfft)
    dwell_frames = max(1, int(args.seconds * args.rate / nfft))
    mute_ranges = []
    for mr in (args.mute_range or []):
        a,b = mr.split(":",1); mute_ranges.append((float(a), float(b)))

    results = []
    heat = np.zeros((len(channels), nfft), dtype=np.float32)

    for i, ch in enumerate(channels):
        cf = WIFI24[ch]
        sdr, st, idx = open_rx(args.rate, args.bw, args.gain, args.driver,
                               args.lna_path, args.lna, args.tia, args.pga,
                               args.antenna, cf)
        buf = np.empty(nfft, dtype=np.complex64)
        acc = None
        row = 0
        while row < dwell_frames:
            nread,_ = read_stream_compat(sdr, st, buf, nfft)
            if nread <= 0: continue
            if nread < nfft:
                tmp = np.zeros(nfft, dtype=np.complex64); tmp[:nread] = buf[:nread]
                p = psd_frame(tmp, nfft)
            else:
                p = psd_frame(buf, nfft)
            p = apply_mutes(p, cf, args.rate, nfft, mute_ranges)
            acc = p if acc is None else (0.9*acc + 0.1*p)
            row += 1
        try:
            sdr.deactivateStream(st); sdr.closeStream(st)
        except Exception: pass

        # bandpower over ±9 MHz (≈Wi-Fi 20 MHz channel minus guard)
        width = float(args.bandwidth_hz)
        b0,b1 = bins_for_range(cf, args.rate, nfft, cf - width/2, cf + width/2)
        chan_power = float(np.mean(acc[b0:b1])) if b1>b0 else float(np.mean(acc))

        # occupancy: fraction of bins > floor+thresh within the band
        band = acc[b0:b1] if b1>b0 else acc
        floor = np.percentile(band, 20)
        occ = float(np.mean(band > (floor + float(args.occ_thresh_db))))

        results.append((ch, int(cf), chan_power, occ))
        heat[i,:] = acc

        # per-channel plot
        plt.figure(figsize=(6,3.2))
        plt.plot(acc); plt.title(f"Wi-Fi ch{ch} @ {cf/1e6:.3f} MHz")
        plt.xlabel("FFT bin"); plt.ylabel("Power (dBFS)")
        plt.tight_layout()
        plt.savefig(outdir/"plots"/f"wifi_ch{ch}_{int(cf)}.png")
        plt.close()

    # sort by power high→low
    results.sort(key=lambda x: x[2], reverse=True)

    csv_path = outdir / f"wifi_band_sweep_{int(time.time())}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["wifi_channel","center_hz","avg_power_dbfs","occupancy_0to1"])
        for ch, cf, p, occ in results:
            w.writerow([ch, cf, f"{p:.2f}", f"{occ:.3f}"])

    # heatmap (channels x bins)
    plt.figure(figsize=(10, 6))
    plt.imshow(heat, aspect="auto", origin="lower", vmin=-100, vmax=-40, interpolation="nearest")
    yticks = [f"ch{c}" for c in channels]
    plt.yticks(range(len(channels)), yticks)
    plt.xlabel("FFT bin"); plt.ylabel("Channel")
    plt.title("Wi-Fi 2.4 GHz sweep (muted ranges excised)")
    plt.tight_layout()
    plt.savefig(outdir/"wifi_band_heatmap.png")
    plt.close()

    print("Top channels by power:")
    for ch, cf, p, occ in results[:8]:
        print(f"  ch{ch:02d} @ {cf/1e6:.3f} MHz : {p:.2f} dBFS, occ={occ:.2f}")
    print(f"CSV: {csv_path}")
    print(f"Plots: {outdir/'plots'}")
    print(f"Heatmap: {outdir/'wifi_band_heatmap.png'}")

def main():
    ap = argparse.ArgumentParser(description="Sweep Wi-Fi 2.4 GHz channels (1–13), with mute-ranges to remove narrow interferers.")
    # RF
    ap.add_argument("--rate", type=float, default=20e6, help="Sample rate (Hz). 20e6 covers full Wi-Fi channel.")
    ap.add_argument("--bw", type=float, default=None, help="Analog bandwidth (Hz); default=rate")
    ap.add_argument("--gain", type=float, default=55.0)
    ap.add_argument("--lna", type=float, default=30.0)
    ap.add_argument("--tia", type=float, default=9.0)
    ap.add_argument("--pga", type=float, default=16.0)
    ap.add_argument("--lna-path", default="LNAH")
    ap.add_argument("--antenna", default=None)
    ap.add_argument("--driver", default="lime")
    # Sweep
    ap.add_argument("--channels", nargs="+", type=int, help="Subset like: 1 6 11 (default 1..13)")
    ap.add_argument("--seconds", type=float, default=1.5, help="Dwell per channel (s)")
    ap.add_argument("--nfft", type=int, default=4096)
    ap.add_argument("--outdir", default="/home/wofl/sdr/wifi/wifi_band_out")
    ap.add_argument("--bandwidth-hz", type=float, default=18e6, help="Bandpower width around center (Hz)")
    # Occupancy
    ap.add_argument("--occ-thresh-db", type=float, default=8.0, help="Bins > (floor+thresh) counted as occupied")
    # Mutes
    ap.add_argument("--mute-range", action="append", help="Absolute RF FSTART:FSTOP (Hz), repeatable. Example: 2404000000:2406000000")
    args = ap.parse_args()
    if args.bw is None: args.bw = args.rate
    sweep(args)

if __name__ == "__main__":
    main()

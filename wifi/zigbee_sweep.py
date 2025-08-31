#!/usr/bin/env python3
import argparse, csv, math, os, time
from pathlib import Path
from typing import List, Tuple

import numpy as np
import matplotlib.pyplot as plt

import SoapySDR
from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CF32


###############################################################################
# ZigBee channel plan (2.4 GHz IEEE 802.15.4)
###############################################################################
# ch 11..26 : center = 2405 + 5*(ch-11) MHz  (2 MHz nominal bandwidth)
def zigbee_center_hz(ch: int) -> float:
    if ch < 11 or ch > 26:
        raise ValueError("ZigBee channel must be 11..26")
    return 2.405e9 + (ch - 11) * 5e6


###############################################################################
# SDR helpers
###############################################################################
def open_sdr(freq_hz, rate_hz, gain_db, bw_hz=None, driver="lime",
             lna_path="LNAH", lna=None, tia=None, pga=None, antenna=None):
    sdr = SoapySDR.Device(dict(driver=driver))
    ch = 0

    # RX path for Lime at 2.4 GHz
    for key in ("LNA_PATH", "RX_PATH"):
        try:
            sdr.writeSetting(key, lna_path)
            break
        except Exception:
            pass

    if antenna:
        try: sdr.setAntenna(SOAPY_SDR_RX, ch, antenna)
        except Exception: pass

    sdr.setSampleRate(SOAPY_SDR_RX, ch, float(rate_hz))
    if bw_hz is None: bw_hz = rate_hz
    try: sdr.setBandwidth(SOAPY_SDR_RX, ch, float(bw_hz))
    except Exception: pass

    sdr.setFrequency(SOAPY_SDR_RX, ch, float(freq_hz))

    try: sdr.setGain(SOAPY_SDR_RX, ch, float(gain_db))
    except Exception: pass

    for name, val in (("LNA", lna), ("TIA", tia), ("PGA", pga)):
        if val is None: continue
        try: sdr.setGainElement(SOAPY_SDR_RX, ch, name, float(val))
        except Exception: pass

    st = sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32, [ch])
    sdr.activateStream(st)
    return sdr, st, ch


def close_sdr(sdr, st):
    try:
        sdr.deactivateStream(st)
        sdr.closeStream(st)
    except Exception:
        pass


def read_stream_compat(sdr, st, view, want, timeout_us=1_000_000) -> Tuple[int,int]:
    """
    Soapy returns either a StreamResult with .ret/.flags or a tuple.
    Normalize to (ret, flags).
    """
    res = sdr.readStream(st, [view], want, timeoutUs=timeout_us)
    if hasattr(res, "ret"):
        return int(res.ret), int(getattr(res, "flags", 0))
    if isinstance(res, (tuple, list)):
        if len(res) == 0:
            return 0, 0
        if len(res) == 1:
            return int(res[0]), 0
        return int(res[0]), int(res[1])
    try:
        return int(res), 0
    except Exception:
        return 0, 0


###############################################################################
# DSP
###############################################################################
def hann(n): return np.hanning(n).astype(np.float32)

def psd_db(iq: np.ndarray, nfft: int) -> np.ndarray:
    win = hann(nfft)
    X = np.fft.fftshift(np.fft.fft(iq[:nfft] * win, n=nfft))
    pxx = (np.abs(X) ** 2) / (nfft + 1e-12)
    return 10.0 * np.log10(pxx + 1e-12).astype(np.float32)

def bandpower_db(psd: np.ndarray, cf_hz: float, rate_hz: float,
                 fstart_hz: float, fstop_hz: float) -> float:
    """Average power in [fstart,fstop] around cf (absolute Hz)."""
    nfft = psd.shape[0]
    bin_bw = rate_hz / nfft
    f0 = cf_hz - rate_hz / 2.0
    b0 = max(0, min(nfft, int(np.floor((fstart_hz - f0) / bin_bw))))
    b1 = max(0, min(nfft, int(np.ceil((fstop_hz - f0) / bin_bw))))
    if b1 <= b0: return float(np.mean(psd))
    return float(np.mean(psd[b0:b1]))

def estimate_period_ms(power_series_db: np.ndarray, row_fs_hz: float,
                       fmin_hz=0.5, fmax_hz=10.0):
    """Simple period estimate via peak in rFFT of de-meaned series."""
    x = power_series_db - np.mean(power_series_db)
    if len(x) < 64:
        return None, None
    X = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), d=1.0/row_fs_hz)
    m = (freqs >= fmin_hz) & (freqs <= fmax_hz)
    if not np.any(m):
        return None, None
    idx = np.argmax(np.abs(X[m]) ** 2)
    f0 = float(freqs[m][idx])
    if f0 <= 0:
        return None, None
    return 1000.0 / f0, f0


###############################################################################
# Main sweep
###############################################################################
def sweep_channels(args):
    outdir = Path(args.outdir).expanduser().resolve()
    (outdir / "plots").mkdir(parents=True, exist_ok=True)

    # Choose channels
    if args.channels:
        chs = sorted(set(int(x) for x in args.channels))
    else:
        chs = list(range(11, 27))

    # SDR once; we retune per channel
    sdr, st, ch = open_sdr(freq_hz=zigbee_center_hz(chs[0]), rate_hz=args.rate,
                           gain_db=args.gain, bw_hz=args.bw, driver=args.driver,
                           lna_path=args.lna_path, lna=args.lna, tia=args.tia,
                           pga=args.pga, antenna=args.antenna)
    buf = np.empty(args.nfft, dtype=np.complex64)

    results = []

    # how many frames per channel
    frames_per_ch = max(1, int(args.seconds * args.rate / args.nfft))
    for zbch in chs:
        cf = zigbee_center_hz(zbch)
        sdr.setFrequency(SOAPY_SDR_RX, ch, float(cf))

        # running average PSD
        acc = None
        for _ in range(frames_per_ch):
            nread, _ = read_stream_compat(sdr, st, buf, args.nfft)
            if nread <= 0:
                continue
            if nread < args.nfft:
                tmp = np.zeros(args.nfft, dtype=np.complex64)
                tmp[:nread] = buf[:nread]
                p = psd_db(tmp, args.nfft)
            else:
                p = psd_db(buf, args.nfft)
            acc = p if acc is None else (0.9 * acc + 0.1 * p)

        if acc is None:
            # Nothing read; mark as very low
            chan_p = -120.0
            series = None
        else:
            # channel power in ±1.2 MHz around center (covers 2 MHz)
            chan_p = bandpower_db(acc, cf, args.rate, cf - 1.2e6, cf + 1.2e6)

            # Save plot
            plt.figure(figsize=(6,4))
            plt.plot(acc)
            plt.title(f"ZigBee ch{zbch} @ {cf/1e6:.3f} MHz")
            plt.xlabel("FFT bin")
            plt.ylabel("Power (dBFS)")
            plt.tight_layout()
            plt.savefig(outdir / "plots" / f"zigbee_ch{zbch}_{int(cf)}.png")
            plt.close()

        results.append((zbch, cf, chan_p))

    close_sdr(sdr, st)

    # Rank by power (high to low)
    results.sort(key=lambda x: x[2], reverse=True)

    # Write summary CSV
    csv_path = outdir / f"zigbee_sweep_{int(time.time())}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["zb_channel","center_hz","avg_power_dbfs"])
        for zbch, cf, p in results:
            w.writerow([zbch, int(cf), f"{p:.2f}"])

    print("Top channels by power:")
    for zbch, cf, p in results[:min(len(results), 8)]:
        print(f"  ch{zbch:02d} @ {cf/1e6:.3f} MHz : {p:.2f} dBFS")

    print(f"CSV: {csv_path}")
    print(f"Plots: {outdir/'plots'}")

    # Optional: period estimate on top K channels
    if args.estimate_period_k > 0:
        top = [r[0] for r in results[:min(args.estimate_period_k, len(results))]]
        period_csv = outdir / f"zigbee_periods_{int(time.time())}.csv"
        with open(period_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["zb_channel","center_hz","period_ms","period_hz"])
            for zbch in top:
                pm, pf = estimate_channel_period(zbch, args)
                if pm is None:
                    print(f"ch{zbch}: no clear periodicity")
                else:
                    print(f"ch{zbch}: ~{pm:.1f} ms ({pf:.2f} Hz)")
                w.writerow([zbch, int(zigbee_center_hz(zbch)),
                            "" if pm is None else f"{pm:.2f}",
                            "" if pf is None else f"{pf:.2f}"])
        print(f"Period CSV: {period_csv}")


def estimate_channel_period(zbch: int, args):
    """Acquire a short waterfall and estimate beacon periodicity from center-bin power."""
    cf = zigbee_center_hz(zbch)
    sdr, st, ch = open_sdr(freq_hz=cf, rate_hz=args.rate, gain_db=args.gain,
                           bw_hz=args.bw, driver=args.driver, lna_path=args.lna_path,
                           lna=args.lna, tia=args.tia, pga=args.pga, antenna=args.antenna)
    buf = np.empty(args.nfft, dtype=np.complex64)

    # Waterfall rows
    rows = max(128, int(args.period_seconds * args.rate / args.nfft))
    series = np.zeros(rows, dtype=np.float32)
    bin_bw = args.rate / args.nfft
    f0 = cf - args.rate / 2.0
    k_center = int(np.round((cf - f0) / bin_bw))
    win = np.hanning(args.nfft).astype(np.float32)

    row = 0
    while row < rows:
        nread, _ = read_stream_compat(sdr, st, buf, args.nfft)
        if nread <= 0:
            continue
        if nread < args.nfft:
            tmp = np.zeros(args.nfft, dtype=np.complex64)
            tmp[:nread] = buf[:nread]
            X = np.fft.fftshift(np.fft.fft(tmp * win, n=args.nfft))
        else:
            X = np.fft.fftshift(np.fft.fft(buf * win, n=args.nfft))
        pxx = (np.abs(X) ** 2) / (args.nfft + 1e-12)
        series[row] = 10.0 * np.log10(pxx[k_center] + 1e-12)
        row += 1

    close_sdr(sdr, st)

    row_fs = args.rate / args.nfft  # rows per second
    return estimate_period_ms(series, row_fs, fmin_hz=0.5, fmax_hz=10.0)


def parse_args():
    ap = argparse.ArgumentParser(
        description="Sweep ZigBee (802.15.4) channels 11–26, log power, optional beacon period."
    )
    # RF params (USB2-friendly defaults)
    ap.add_argument("--rate", type=float, default=10e6, help="Sample rate Hz (USB2-safe).")
    ap.add_argument("--bw", type=float, default=None, help="RF bandwidth Hz (default=rate).")
    ap.add_argument("--gain", type=float, default=55.0, help="Total gain dB.")
    ap.add_argument("--lna", type=float, default=30.0)
    ap.add_argument("--tia", type=float, default=9.0)
    ap.add_argument("--pga", type=float, default=16.0)
    ap.add_argument("--lna-path", default="LNAH")
    ap.add_argument("--antenna", default=None)
    ap.add_argument("--driver", default="lime")
    # Sweep control
    ap.add_argument("--channels", nargs="+", help="List like 11 12 13 ... (default 11..26).")
    ap.add_argument("--seconds", type=float, default=1.5, help="Dwell per channel (s).")
    ap.add_argument("--nfft", type=int, default=4096, help="FFT size.")
    ap.add_argument("--outdir", default="/home/wofl/sdr/wifi/zigbee_out", help="Results folder.")
    # Period estimation on strongest K channels
    ap.add_argument("--estimate-period-k", type=int, default=1,
                    help="Estimate beacon periodicity on top-K channels (0 to disable).")
    ap.add_argument("--period-seconds", type=float, default=20.0,
                    help="Capture length for period estimate per channel (s).")
    return ap.parse_args()


def main():
    args = parse_args()
    if args.bw is None:
        args.bw = args.rate
    sweep_channels(args)


if __name__ == "__main__":
    main()

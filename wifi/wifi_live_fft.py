#!/usr/bin/env python3
import argparse
import json
import time
from pathlib import Path
import numpy as np
import SoapySDR
from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CF32

import matplotlib
matplotlib.use("TkAgg")  # or "Qt5Agg" if you prefer; change if needed
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

VERSION = "wifi_live_fft.py v1.0"
LIME_MAX_HZ = 3.8e9  # LimeSDR Mini v2 practical upper limit

def dbfs(x):
    return 10.0 * np.log10(np.maximum(x, 1e-12))

def welch_psd(iq, nfft=4096, overlap=0.5, window="hann"):
    """Welch PSD (linear). No self-norm to 0 dB."""
    iq = np.asarray(iq)
    if window == "hann":
        win = np.hanning(nfft).astype(np.float32)
    else:
        win = np.ones(nfft, dtype=np.float32)
    step = max(1, int(nfft * (1.0 - overlap)))
    segs = []
    wpow = (win**2).sum()
    for i in range(0, len(iq) - nfft + 1, step):
        seg = iq[i:i+nfft] * win
        X = np.fft.fftshift(np.fft.fft(seg))
        pxx = (np.abs(X)**2) / (nfft * wpow + 1e-12)
        segs.append(pxx)
    if not segs:
        return None
    return np.mean(np.stack(segs, axis=0), axis=0)

def set_lime_gains(sdr, ch, overall, lna=None, tia=None, pga=None):
    try:
        sdr.setGain(SOAPY_SDR_RX, ch, float(overall))
    except Exception:
        pass
    try:
        if lna is not None:
            sdr.setGainElement(SOAPY_SDR_RX, ch, "LNA", float(lna))
    except Exception:
        pass
    try:
        if tia is not None:
            sdr.setGainElement(SOAPY_SDR_RX, ch, "TIA", float(tia))
    except Exception:
        pass
    try:
        if pga is not None:
            sdr.setGainElement(SOAPY_SDR_RX, ch, "PGA", float(pga))
    except Exception:
        pass

def open_lime(driver, rate, freq, gain, bw=None, lna_path=None, antenna=None, lna=None, tia=None, pga=None):
    if float(freq) > LIME_MAX_HZ:
        raise RuntimeError(f"freq {freq/1e9:.3f} GHz > LimeSDR Mini v2 limit")
    sdr = SoapySDR.Device(dict(driver=driver))
    ch = 0
    # path & antenna
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
    sdr.setSampleRate(SOAPY_SDR_RX, ch, float(rate))
    if bw is not None:
        try:
            sdr.setBandwidth(SOAPY_SDR_RX, ch, float(bw))
        except Exception:
            pass
    sdr.setFrequency(SOAPY_SDR_RX, ch, float(freq))
    set_lime_gains(sdr, ch, overall=gain, lna=lna, tia=tia, pga=pga)
    return sdr

def _read_stream_compat(sdr, st, view, want, timeout_us=500000):
    res = sdr.readStream(st, [view], want, timeoutUs=timeout_us)
    if hasattr(res, "ret"):
        return int(res.ret), int(getattr(res, "flags", 0))
    if isinstance(res, (tuple, list)) and len(res) >= 1:
        return int(res[0]), (int(res[1]) if len(res) >= 2 else 0)
    try:
        return int(res), 0
    except Exception:
        return 0, 0

def ringpush(img, row):
    """Push a new row (1D) into a 2D image (scroll up)."""
    img[:-1, :] = img[1:, :]
    img[-1, :] = row
    return img

def load_channels_json(path):
    with open(path, "r", encoding="utf-8") as f:
        j = json.load(f)
    band24 = sorted([(int(k), int(v)) for k, v in j["band_24"]["channels"].items()], key=lambda t: t[0])
    try:
        band5 = sorted([(int(k), int(v)) for k, v in j["band_5"]["non_dfs_channels"].items()], key=lambda t: t[0])
    except Exception:
        band5 = []
    return band24, band5

def main():
    ap = argparse.ArgumentParser(description="Live spectrum + waterfall for LimeSDR (2.4 GHz Wi-Fi).")
    ap.add_argument("--channels", default="/home/wofl/sdr/wifi/wifi_channels_uk.json")
    ap.add_argument("--band", choices=["24","5"], default="24")
    ap.add_argument("--channel", type=int, default=6, help="Wi-Fi channel number when using --band")
    ap.add_argument("--freq", type=float, default=None, help="Override center frequency in Hz (takes precedence).")
    ap.add_argument("--rate", type=float, default=20e6)
    ap.add_argument("--fft", type=int, default=4096)
    ap.add_argument("--overlap", type=float, default=0.5)
    ap.add_argument("--avg", type=float, default=0.6, help="EMA factor for spectrum (0..1, higher=stickier).")
    ap.add_argument("--wf-rows", type=int, default=200, help="Waterfall height (rows of history).")
    ap.add_argument("--gain", type=float, default=55.0)
    ap.add_argument("--bw", type=float, default=20e6)
    ap.add_argument("--driver", default="lime")
    ap.add_argument("--lna-path", default="LNAH")
    ap.add_argument("--antenna", default=None)
    ap.add_argument("--lna", type=float, default=30.0)
    ap.add_argument("--tia", type=float, default=9.0)
    ap.add_argument("--pga", type=float, default=16.0)
    args = ap.parse_args()

    band24, band5 = load_channels_json(args.channels)
    if args.freq is None:
        if args.band == "24":
            fmap = dict(band24)
        else:
            fmap = dict(band5)
        if args.channel not in fmap:
            raise SystemExit(f"channel {args.channel} not in map for band {args.band}")
        cf = float(fmap[args.channel])
    else:
        cf = float(args.freq)

    print(VERSION)
    print(f"Center: {cf/1e6:.3f} MHz  SR: {args.rate/1e6:.2f} Msps  FFT: {args.fft}  gain: {args.gain}  LNA_PATH: {args.lna_path}")

    sdr = open_lime(args.driver, args.rate, cf, args.gain, bw=args.bw,
                    lna_path=args.lna_path, antenna=args.antenna,
                    lna=args.lna, tia=args.tia, pga=args.pga)
    ch = 0
    st = sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32, [ch])
    sdr.activateStream(st)

    # Buffers
    block = max(args.fft * 4, 262144)  # capture a chunk per frame
    iq = np.empty(block, dtype=np.complex64)
    avg_spec = None  # EMA of dBFS spectrum
    wf = np.full((args.wf_rows, args.fft), -120.0, dtype=np.float32)

    # Matplotlib set-up
    fig = plt.figure(figsize=(10, 7))
    gs = fig.add_gridspec(2, 1, height_ratios=[1, 2], hspace=0.08)

    ax0 = fig.add_subplot(gs[0, 0])
    spec_line, = ax0.plot(np.arange(args.fft), np.full(args.fft, -120.0), lw=1.0)
    ax0.set_xlim(0, args.fft-1)
    ax0.set_ylim(-100, -40)
    ax0.set_ylabel("Power (dBFS)")
    title = ax0.set_title(f"{('2.4GHz' if args.band=='24' else '5GHz')} ch{args.channel} @ {cf/1e6:.3f} MHz")

    ax1 = fig.add_subplot(gs[1, 0])
    im = ax1.imshow(wf, origin="lower", aspect="auto", vmin=-100, vmax=-40, interpolation="nearest")
    cbar = fig.colorbar(im, ax=ax1, pad=0.01)
    cbar.set_label("dBFS")
    ax1.set_ylabel("Time")
    ax1.set_xlabel("FFT bin")

    # Key bindings
    state = {"running": True, "gain": args.gain, "avg": args.avg, "center": cf}

    def on_key(event):
        nonlocal sdr, st, avg_spec
        if event.key in ("q", "escape"):
            state["running"] = False
        elif event.key in ("+", "="):
            state["avg"] = min(0.98, state["avg"] + 0.05)
            print(f"avg -> {state['avg']:.2f}")
        elif event.key in ("-", "_"):
            state["avg"] = max(0.0, state["avg"] - 0.05)
            print(f"avg -> {state['avg']:.2f}")
        elif event.key == "g":
            state["gain"] = max(0.0, state["gain"] - 1.0)
            print(f"gain -> {state['gain']:.1f} dB")
            set_lime_gains(sdr, ch, state["gain"], args.lna, args.tia, args.pga)
        elif event.key == "G":
            state["gain"] = min(70.0, state["gain"] + 1.0)
            print(f"gain -> {state['gain']:.1f} dB")
            set_lime_gains(sdr, ch, state["gain"], args.lna, args.tia, args.pga)
        elif event.key == "left":
            state["center"] -= 1e6
            try:
                sdr.setFrequency(SOAPY_SDR_RX, ch, float(state["center"]))
                avg_spec = None
                print(f"tuned -> {state['center']/1e6:.3f} MHz")
            except Exception as e:
                print(f"tune fail: {e}")
                state["center"] += 1e6
        elif event.key == "right":
            state["center"] += 1e6
            if state["center"] > LIME_MAX_HZ:
                state["center"] -= 1e6
            else:
                try:
                    sdr.setFrequency(SOAPY_SDR_RX, ch, float(state["center"]))
                    avg_spec = None
                    print(f"tuned -> {state['center']/1e6:.3f} MHz")
                except Exception as e:
                    print(f"tune fail: {e}")
                    state["center"] -= 1e6

    fig.canvas.mpl_connect("key_press_event", on_key)

    def grab_block():
        got = 0
        timeouts = 0
        while got < block:
            n = min(262144, block - got)
            nread, _ = _read_stream_compat(sdr, st, iq[got:got+n], n, timeout_us=500000)
            if nread > 0:
                got += nread
                timeouts = 0
            else:
                timeouts += 1
                if timeouts > 3:
                    break
        return iq[:got]

    def update(_frame):
        nonlocal avg_spec, wf
        if not state["running"]:
            plt.close(fig)
            return

        data = grab_block()
        if data.size < args.fft:
            return

        pxx = welch_psd(data, nfft=args.fft, overlap=args.overlap)
        if pxx is None:
            return
        spec_db = dbfs(pxx)

        if avg_spec is None:
            avg_spec = spec_db.copy()
        else:
            alpha = float(state["avg"])
            avg_spec = alpha * avg_spec + (1.0 - alpha) * spec_db

        spec_line.set_ydata(avg_spec)
        wf = ringpush(wf, avg_spec.astype(np.float32))
        im.set_data(wf)
        title.set_text(f"{('2.4GHz' if args.band=='24' else '5GHz')} ch{args.channel} @ {state['center']/1e6:.3f} MHz  "
                       f"gain {state['gain']:.1f} dB  avg {state['avg']:.2f}")
        return spec_line, im, title

    ani = FuncAnimation(fig, update, interval=60, blit=False)
    try:
        plt.show()
    finally:
        try:
            sdr.deactivateStream(st)
        except Exception:
            pass
        try:
            sdr.closeStream(st)
        except Exception:
            pass

if __name__ == "__main__":
    main()

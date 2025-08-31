#!/usr/bin/env python3
import argparse, math, signal, sys, time, threading
from pathlib import Path
from typing import List, Tuple, Optional

import numpy as np
import matplotlib.pyplot as plt

import SoapySDR
from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_TX, SOAPY_SDR_CF32

def read_stream_compat(sdr, st, view, want, timeout_us=1_000_000):
    res = sdr.readStream(st, [view], want, timeoutUs=timeout_us)
    if hasattr(res, "ret"): return int(res.ret), int(getattr(res,"flags",0))
    if isinstance(res,(tuple,list)):
        if not res: return 0,0
        return int(res[0]), int(res[1] if len(res)>1 else 0)
    try: return int(res),0
    except Exception: return 0,0

def write_stream_compat(sdr, st, buf):
    res = sdr.writeStream(st, [buf], len(buf))
    if hasattr(res, "ret"): return int(res.ret)
    if isinstance(res, (tuple, list)): return int(res[0]) if res else 0
    try: return int(res)
    except Exception: return 0

def hann(n): return np.hanning(n).astype(np.float32)

def stft_frame(iq: np.ndarray, nfft: int, window: np.ndarray) -> np.ndarray:
    X = np.fft.fftshift(np.fft.fft(iq * window, n=nfft))
    pxx = (np.abs(X)**2) / (nfft + 1e-12)
    return 10.0*np.log10(pxx + 1e-12).astype(np.float32)

def bins_for_range(center_hz: float, span_hz: float, nfft: int, fstart: float, fstop: float):
    bin_bw = span_hz / nfft
    f0 = center_hz - span_hz/2
    b0 = int(np.floor((fstart - f0)/bin_bw))
    b1 = int(np.ceil((fstop  - f0)/bin_bw))
    b0 = max(0, min(nfft, b0)); b1 = max(0, min(nfft, b1))
    if b1 < b0: b0,b1 = b1,b0
    return b0, b1

def make_device(driver: str, serial: Optional[str]):
    args = {"driver": driver}
    if serial:
        args["serial"] = serial
    return SoapySDR.Device(args)

# ------------------- TX worker (shares one device) -------------------

class TxWorker(threading.Thread):
    def __init__(self, sdr, ch, args, stop_evt: threading.Event):
        super().__init__(daemon=True)
        self.sdr = sdr
        self.ch = ch
        self.a = args
        self.stop_evt = stop_evt
        self.st = None

    def run(self):
        a = self.a
        tx_fc = float(a.tx_freq if a.tx_freq is not None else a.freq)

        # path
        for key in ("TX_PATH","TX_BAND"):
            try: self.sdr.writeSetting(key, a.tx_path)
            except Exception: pass
        if a.tx_antenna:
            try: self.sdr.setAntenna(SOAPY_SDR_TX, self.ch, a.tx_antenna)
            except Exception: pass

        # TX rates/gains
        self.sdr.setSampleRate(SOAPY_SDR_TX, self.ch, float(a.tx_rate))
        bw = float(a.tx_bw if a.tx_bw is not None else a.tx_rate)
        try: self.sdr.setBandwidth(SOAPY_SDR_TX, self.ch, bw)
        except Exception: pass
        self.sdr.setFrequency(SOAPY_SDR_TX, self.ch, tx_fc)
        try: self.sdr.setGain(SOAPY_SDR_TX, self.ch, float(a.tx_gain))
        except Exception: pass
        for name,val in (("PAD",a.pad),("IAMP",a.iamp)):
            if val is None: continue
            try: self.sdr.setGainElement(SOAPY_SDR_TX, self.ch, name, float(val))
            except Exception: pass

        self.st = self.sdr.setupStream(SOAPY_SDR_TX, SOAPY_SDR_CF32, [self.ch])
        self.sdr.activateStream(self.st)
        print(f"[TX] center={tx_fc/1e6:.3f} MHz  fs={a.tx_rate/1e6:.3f} Msps  mode={a.tx_mode}")

        try:
            if a.tx_mode == "tone":
                n = 4096
                t = np.arange(n, dtype=np.float32) / float(a.tx_rate)
                ph = 2*np.pi*float(a.tone_hz)*t
                wave = (a.amplitude*(np.cos(ph)+1j*np.sin(ph))).astype(np.complex64)
                t_end = time.time() + a.seconds if a.seconds>0 else None
                while not self.stop_evt.is_set() and (t_end is None or time.time()<t_end):
                    if write_stream_compat(self.sdr, self.st, wave) <= 0: continue
            elif a.tx_mode == "file":
                path = Path(a.iq).expanduser()
                iq = np.fromfile(path, dtype=np.complex64)
                if iq.size == 0: print("[TX] empty file"); return
                rms = np.sqrt(np.mean(np.abs(iq)**2))
                if rms>0: iq = (iq*(a.amplitude/(4.0*rms))).astype(np.complex64)
                idx, n = 0, 4096
                t_end = time.time() + a.seconds if a.seconds>0 else None
                while not self.stop_evt.is_set() and (t_end is None or time.time()<t_end):
                    chunk = iq[idx:idx+n]
                    if chunk.size < n:
                        if not a.loop:
                            if chunk.size>0: write_stream_compat(self.sdr, self.st, chunk)
                            break
                        need = n - chunk.size
                        chunk = np.concatenate([chunk, iq[:need]])
                        idx = need
                    else:
                        idx += n
                    if write_stream_compat(self.sdr, self.st, chunk) <= 0: continue
            else:
                print("[TX] mode off; nothing transmitted.")
        finally:
            if self.st:
                try: self.sdr.deactivateStream(self.st); self.sdr.closeStream(self.st)
                except Exception: pass
            print("[TX] stopped")

# ------------------- RX viewer (shares one device) -------------------

class RxViewer:
    def __init__(self, sdr, ch, args, stop_evt: threading.Event):
        self.sdr = sdr
        self.ch = ch
        self.a = args
        self.stop_evt = stop_evt

        self.center = float(args.freq)
        self.rate   = float(args.rate)
        self.bw     = float(args.bw if args.bw is not None else self.rate)
        self.nfft   = int(args.fft)

        # RX path
        for key in ("LNA_PATH","RX_PATH"):
            try: self.sdr.writeSetting(key, args.lna_path)
            except Exception: pass
        if args.rx_antenna:
            try: self.sdr.setAntenna(SOAPY_SDR_RX, self.ch, args.rx_antenna)
            except Exception: pass

        self.sdr.setSampleRate(SOAPY_SDR_RX, self.ch, self.rate)
        try: self.sdr.setBandwidth(SOAPY_SDR_RX, self.ch, self.bw)
        except Exception: pass
        self.sdr.setFrequency(SOAPY_SDR_RX, self.ch, self.center)
        try: self.sdr.setGain(SOAPY_SDR_RX, self.ch, float(args.gain))
        except Exception: pass
        for name,val in (("LNA",args.lna),("TIA",args.tia),("PGA",args.pga)):
            if val is None: continue
            try: self.sdr.setGainElement(SOAPY_SDR_RX, self.ch, name, float(val))
            except Exception: pass

        self.st = self.sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32, [self.ch])
        self.sdr.activateStream(self.st)

        self.buf = np.empty(self.nfft, dtype=np.complex64)
        self.win = hann(self.nfft)
        self.alpha = float(args.avg)
        self.psd_avg = None
        self.wf_rows = int(args.wf_rows)
        self.wf = np.full((self.wf_rows, self.nfft), -120.0, dtype=np.float32)

        self.fig, (self.ax_psd, self.ax_wf) = plt.subplots(
            2,1, figsize=(10,6), gridspec_kw=dict(height_ratios=[1,2])
        )
        self.fig.canvas.manager.set_window_title("LimeSDR TX+RX Live")

        self.psd_line, = self.ax_psd.plot(np.zeros(self.nfft, dtype=np.float32))
        self.ax_psd.set_ylim(-100, -40); self.ax_psd.set_xlim(0, self.nfft-1)
        self.ax_psd.set_ylabel("Power (dBFS)")
        self.update_title()

        self.im = self.ax_wf.imshow(self.wf, aspect="auto", origin="lower",
                                    vmin=-100, vmax=-40, interpolation="nearest")
        self.ax_wf.set_xlabel("FFT bin"); self.ax_wf.set_ylabel("Time")

        # markers
        self.markers = self.a.marker or []
        self.marker_art = []
        for f in self.markers:
            bx = self.rf_to_bin(float(f))
            self.marker_art.append(self.ax_psd.axvline(bx, ls="--", lw=1, alpha=0.6))
            self.ax_wf.axvline(bx, ls="--", lw=0.8, alpha=0.6)

        self.mute_ranges = parse_mute_ranges(self.a.mute_range)
        self.mute_bins = []
        self.recompute_mute_bins()

        self.fig.canvas.mpl_connect("key_press_event", self.on_key)
        signal.signal(signal.SIGINT, self.sigint)

    def update_title(self):
        self.ax_psd.set_title(f"RX @ {self.center/1e6:.3f} MHz  fs={self.rate/1e6:.2f} Msps  "
                              f"gain {self.a.gain:.1f} dB  avg {self.alpha:.2f}")

    def rf_to_bin(self, f_hz: float) -> int:
        f0 = self.center - self.rate/2
        k = int(np.round((f_hz - f0)/(self.rate/self.nfft)))
        return max(0, min(self.nfft-1, k))

    def recompute_mute_bins(self):
        self.mute_bins.clear()
        for f0,f1 in self.mute_ranges:
            b0,b1 = bins_for_range(self.center, self.rate, self.nfft, f0, f1)
            self.mute_bins.append((b0,b1))

    def apply_mutes(self, psd):
        if not self.mute_bins: return psd
        out = psd.copy()
        floor = np.percentile(psd, 5)
        for b0,b1 in self.mute_bins:
            out[b0:b1] = floor
        return out

    def on_key(self, ev):
        step = float(self.a.step_hz)
        if ev.key == "left":
            self.center -= step
        elif ev.key == "right":
            self.center += step
        elif ev.key == "up":
            self.a.gain = min(70.0, self.a.gain + 2.0)
            self.sdr.setGain(SOAPY_SDR_RX, self.ch, self.a.gain)
        elif ev.key == "down":
            self.a.gain = max(0.0, self.a.gain - 2.0)
            self.sdr.setGain(SOAPY_SDR_RX, self.ch, self.a.gain)
        elif ev.key in ("q","escape"):
            self.sigint(); return
        else:
            return
        self.sdr.setFrequency(SOAPY_SDR_RX, self.ch, float(self.center))
        self.recompute_mute_bins()
        for ln, f in zip(self.marker_art, self.markers):
            bx = self.rf_to_bin(float(f)); ln.set_xdata([bx,bx])
        self.update_title()

    def sigint(self,*_):
        self.stop_evt.set()
        plt.close("all")
        try: self.sdr.deactivateStream(self.st); self.sdr.closeStream(self.st)
        except Exception: pass
        sys.exit(0)

    def loop(self):
        while plt.fignum_exists(self.fig.number) and not self.stop_evt.is_set():
            nread,_ = read_stream_compat(self.sdr, self.st, self.buf, self.nfft)
            if nread <= 0: continue
            if nread < self.nfft:
                tmp = np.zeros(self.nfft, dtype=np.complex64); tmp[:nread] = self.buf[:nread]
                psd = stft_frame(tmp, self.nfft, self.win)
            else:
                psd = stft_frame(self.buf, self.nfft, self.win)
            psd = self.apply_mutes(psd)
            if self.psd_avg is None: self.psd_avg = psd
            else: self.psd_avg = (1.0-self.alpha)*self.psd_avg + self.alpha*psd
            self.wf = np.roll(self.wf, -1, axis=0); self.wf[-1,:] = psd
            self.psd_line.set_ydata(self.psd_avg); self.im.set_data(self.wf)
            plt.pause(0.001)
        self.sigint()

def parse_mute_ranges(vals: Optional[List[str]]):
    out=[]
    for v in vals or []:
        if ":" not in v: raise argparse.ArgumentTypeError("mute-range must be FSTART:FSTOP (Hz)")
        a,b=v.split(":",1); out.append((float(a),float(b)))
    return out

def main():
    ap = argparse.ArgumentParser(description="LimeSDR-Mini v2 full-duplex: TX (tone/file) + live RX waterfall (single device).")
    ap.add_argument("--driver", default="lime")
    ap.add_argument("--serial", help="Lime serial to select specific device")

    # RX
    ap.add_argument("--freq", type=float, required=True, help="RX center frequency (Hz)")
    ap.add_argument("--rate", type=float, default=10e6, help="RX sample rate (Hz)")
    ap.add_argument("--bw", type=float, default=None, help="RX analog bandwidth (Hz); default=rate")
    ap.add_argument("--gain", type=float, default=55.0)
    ap.add_argument("--lna", type=float, default=30.0)
    ap.add_argument("--tia", type=float, default=9.0)
    ap.add_argument("--pga", type=float, default=16.0)
    ap.add_argument("--lna-path", default="LNAH")
    ap.add_argument("--rx-antenna", default=None)

    # TX
    ap.add_argument("--tx-mode", choices=["off","tone","file"], default="tone")
    ap.add_argument("--tx-freq", type=float, help="TX center (Hz). Defaults to --freq")
    ap.add_argument("--tx-rate", type=float, default=2e6, help="TX sample rate (Hz)")
    ap.add_argument("--tx-bw", type=float, default=None, help="TX analog bandwidth (Hz); default=tx-rate")
    ap.add_argument("--tx-gain", type=float, default=35.0, help="TX overall gain (dB)")
    ap.add_argument("--tx-path", default="BAND2", help="Lime TX path for 2.4 GHz")
    ap.add_argument("--tx-antenna", default=None)
    ap.add_argument("--pad", type=float, help="TX PAD gain dB")
    ap.add_argument("--iamp", type=float, help="TX IAMP gain dB")
    ap.add_argument("--tone-hz", type=float, default=100e3, help="tone offset (baseband) Hz")
    ap.add_argument("--amplitude", type=float, default=0.2, help="TX digital amplitude 0..1 (keep ≤0.5)")
    ap.add_argument("--iq", help="path to cf32_le file (for --tx-mode file)")

    # Plot & control
    ap.add_argument("--fft", type=int, default=4096)
    ap.add_argument("--wf-rows", type=int, default=240)
    ap.add_argument("--avg", type=float, default=0.6)
    ap.add_argument("--step-hz", type=float, default=1e6)
    ap.add_argument("--mute-range", action="append", help="mute absolute RF FSTART:FSTOP (Hz), repeatable")
    ap.add_argument("--marker", action="append", type=float, help="vertical marker at RF Hz, repeatable")

    # misc
    ap.add_argument("--seconds", type=float, default=0.0, help="TX duration (0 = until Ctrl-C)")
    ap.add_argument("--loop", action="store_true", help="loop file playback")

    args = ap.parse_args()

    # Single device for both directions
    sdr = make_device(args.driver, args.serial)
    rx_ch = 0
    tx_ch = 0

    stop_evt = threading.Event()

    # start TX thread
    tx_thr = TxWorker(sdr, tx_ch, args, stop_evt)
    tx_thr.start()

    # start RX viewer (blocks until window closes)
    viewer = RxViewer(sdr, rx_ch, args, stop_evt)
    viewer.loop()

if __name__ == "__main__":
    main()

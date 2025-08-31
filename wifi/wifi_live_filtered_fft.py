#!/usr/bin/env python3
import argparse
import signal
import sys
import time
from typing import List, Tuple

import numpy as np
import matplotlib.pyplot as plt

import SoapySDR
from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CF32


###############################################################################
# SDR helpers
###############################################################################

def open_sdr(freq, rate, gain, bw=None, driver="lime", lna_path="LNAH",
             lna=None, tia=None, pga=None, antenna=None):
    sdr = SoapySDR.Device(dict(driver=driver))
    ch = 0

    # Frontend path (Lime: LNAH for 2.4 GHz)
    try:
        sdr.writeSetting("LNA_PATH", lna_path)
    except Exception:
        try:
            sdr.writeSetting("RX_PATH", lna_path)
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

    # Coarse total gain
    try:
        sdr.setGain(SOAPY_SDR_RX, ch, float(gain))
    except Exception:
        pass

    # Optional per-stage gains
    for name, val in (("LNA", lna), ("TIA", tia), ("PGA", pga)):
        if val is None:
            continue
        try:
            sdr.setGainElement(SOAPY_SDR_RX, ch, name, float(val))
        except Exception:
            pass

    return sdr


def read_stream_compat(sdr, st, view, want, timeout_us=1_000_000):
    """
    Soapy returns either a StreamResult object with .ret/.flags or a tuple.
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
# DSP helpers
###############################################################################

def stft_frame(iq: np.ndarray, nfft: int, window: np.ndarray) -> np.ndarray:
    X = np.fft.fftshift(np.fft.fft(iq * window, n=nfft))
    pxx = np.abs(X) ** 2
    # Convert to dBFS-ish; normalize by nfft to keep scale stable
    psd = 10.0 * np.log10(pxx / (nfft + 1e-12) + 1e-12).astype(np.float32)
    return psd


def build_window(nfft: int) -> np.ndarray:
    return np.hanning(nfft).astype(np.float32)


def bins_for_range(center_hz: float, span_hz: float, nfft: int,
                   fstart_hz: float, fstop_hz: float) -> Tuple[int, int]:
    """
    Map absolute [fstart,fstop] to FFT bin indices (inclusive low, exclusive high).
    fft bins are fftshifted: bin 0 = center - span/2.
    """
    bin_bw = span_hz / nfft
    f0 = center_hz - span_hz / 2.0
    b_start = int(np.floor((fstart_hz - f0) / bin_bw))
    b_stop = int(np.ceil((fstop_hz - f0) / bin_bw))
    b_start = max(0, min(nfft, b_start))
    b_stop = max(0, min(nfft, b_stop))
    if b_stop < b_start:
        b_start, b_stop = b_stop, b_start
    return b_start, b_stop


###############################################################################
# Viewer
###############################################################################

class LiveViewer:
    def __init__(self, args):
        self.args = args
        self.center_hz = float(args.freq) if args.freq is not None else None
        self.rate = float(args.rate)
        self.bw = float(args.bw) if args.bw is not None else self.rate
        self.gain = float(args.gain)

        if self.center_hz is None and args.band == 24 and args.channel is not None:
            # Wi-Fi 2.4 GHz channels (1/6/11 etc.)
            self.center_hz = 2.412e9 + (args.channel - 1) * 5e6
        elif self.center_hz is None:
            raise SystemExit("You must pass --freq or --band 24 --channel N")

        self.mute_ranges = args.mute_range or []
        self.markers = args.marker or []

        # SDR
        self.sdr = open_sdr(self.center_hz, self.rate, self.gain, bw=self.bw,
                            driver=args.driver, lna_path=args.lna_path,
                            lna=args.lna, tia=args.tia, pga=args.pga,
                            antenna=args.antenna)
        self.ch = 0
        self.nfft = int(args.fft)
        self.hop = self.nfft  # non-overlapped; we average in time instead
        self.window = build_window(self.nfft)
        self.buf = np.empty(self.nfft, dtype=np.complex64)

        self.st = self.sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32, [self.ch])
        self.sdr.activateStream(self.st)

        # Plot
        self.fig, (self.ax_psd, self.ax_wf) = plt.subplots(
            2, 1, figsize=(10, 6), gridspec_kw=dict(height_ratios=[1, 2])
        )
        self.fig.canvas.manager.set_window_title("LimeSDR Live FFT + Waterfall")

        # Waterfall buffer (rows x bins)
        self.wf_rows = int(args.wf_rows)
        self.wf = np.full((self.wf_rows, self.nfft), -120.0, dtype=np.float32)
        self.im = self.ax_wf.imshow(
            self.wf, aspect="auto", origin="lower",
            vmin=-100, vmax=-40, interpolation="nearest"
        )
        self.ax_wf.set_ylabel("Time")
        self.ax_wf.set_xlabel("FFT bin")

        # PSD line
        self.psd_line, = self.ax_psd.plot(np.zeros(self.nfft, dtype=np.float32))
        self.ax_psd.set_ylim(-100, -40)
        self.ax_psd.set_ylabel("Power (dBFS)")
        self.ax_psd.set_title(f"2.4GHz ch{args.channel} @ {self.center_hz/1e6:.3f} MHz  "
                              f"gain {self.gain:.1f} dB  avg {args.avg:.2f}")

        # Marker lines (draw once; we’ll just leave them)
        self.marker_artists = []
        for f in self.markers:
            bx = self.rf_to_bin(float(f))
            ln = self.ax_psd.axvline(bx, linestyle="--", linewidth=1.0, alpha=0.6)
            self.marker_artists.append(ln)
            self.ax_wf.axvline(bx, linestyle="--", linewidth=0.8, alpha=0.6)

        # Keyboard
        self.fig.canvas.mpl_connect("key_press_event", self.on_key)

        # Running average
        self.alpha = float(args.avg)
        self.psd_avg = None

        # Pre-compute mute masks (bin index ranges, recomputed on retune)
        self.mute_idx: List[Tuple[int, int]] = []
        self.recompute_mute_bins()

        # graceful exit
        signal.signal(signal.SIGINT, self.sigint)

    def sigint(self, *_):
        try:
            self.sdr.deactivateStream(self.st)
            self.sdr.closeStream(self.st)
        finally:
            plt.close("all")
            sys.exit(0)

    def rf_to_bin(self, f_hz: float) -> int:
        f0 = self.center_hz - self.rate / 2.0
        k = int(np.round((f_hz - f0) / (self.rate / self.nfft)))
        return max(0, min(self.nfft - 1, k))

    def recompute_mute_bins(self):
        self.mute_idx.clear()
        if not self.mute_ranges:
            return
        for (fstart, fstop) in self.mute_ranges:
            b0, b1 = bins_for_range(self.center_hz, self.rate, self.nfft, fstart, fstop)
            self.mute_idx.append((b0, b1))

    def apply_mutes(self, psd_db: np.ndarray) -> np.ndarray:
        """
        Return a copy with muted ranges set to the local floor (so they vanish
        in the waterfall and don’t bias the average).
        """
        if not self.mute_idx:
            return psd_db
        out = psd_db.copy()
        floor = np.percentile(psd_db, 5)  # robust-ish floor estimate
        for b0, b1 in self.mute_idx:
            out[b0:b1] = floor
        return out

    def on_key(self, ev):
        step = float(self.args.step_hz)
        redraw_mutes = False

        if ev.key == "left":
            self.center_hz -= step
            redraw_mutes = True
        elif ev.key == "right":
            self.center_hz += step
            redraw_mutes = True
        elif ev.key == "up":
            self.gain = min(70.0, self.gain + 2.0)
            self.sdr.setGain(SOAPY_SDR_RX, self.ch, self.gain)
        elif ev.key == "down":
            self.gain = max(0.0, self.gain - 2.0)
            self.sdr.setGain(SOAPY_SDR_RX, self.ch, self.gain)
        elif ev.key in ("q", "escape"):
            self.sigint()

        if redraw_mutes:
            self.sdr.setFrequency(SOAPY_SDR_RX, self.ch, float(self.center_hz))
            self.recompute_mute_bins()
            # shift marker lines to new bin positions
            for ln, f in zip(self.marker_artists, self.markers):
                ln.set_xdata([self.rf_to_bin(float(f)), self.rf_to_bin(float(f))])

            self.ax_psd.set_title(
                f"2.4GHz ch{self.args.channel} @ {self.center_hz/1e6:.3f} MHz  "
                f"gain {self.gain:.1f} dB  avg {self.alpha:.2f}"
            )

    def loop(self):
        # read/compute/plot
        while plt.fignum_exists(self.fig.number):
            nread, _ = read_stream_compat(self.sdr, self.st, self.buf, self.nfft)
            if nread <= 0:
                continue
            if nread < self.nfft:
                # zero-pad rare short reads
                frame = np.zeros(self.nfft, dtype=np.complex64)
                frame[:nread] = self.buf[:nread]
            else:
                frame = self.buf

            psd = stft_frame(frame, self.nfft, self.window)
            psd_muted = self.apply_mutes(psd)

            # running average for PSD line
            if self.psd_avg is None:
                self.psd_avg = psd_muted
            else:
                self.psd_avg = (1.0 - self.alpha) * self.psd_avg + self.alpha * psd_muted

            # update waterfall (roll up)
            self.wf = np.roll(self.wf, -1, axis=0)
            self.wf[-1, :] = psd_muted

            # draw
            self.psd_line.set_ydata(self.psd_avg)
            self.im.set_data(self.wf)

            # autoscale x once (0..nfft-1)
            self.ax_psd.set_xlim(0, self.nfft - 1)
            self.ax_wf.set_xlim(0, self.nfft - 1)

            plt.pause(0.001)  # yield to UI thread

        # out of the loop = window closed
        self.sigint()


###############################################################################
# CLI
###############################################################################

def parse_mute_ranges(vals: List[str]) -> List[Tuple[float, float]]:
    out = []
    for v in vals or []:
        if ":" not in v:
            raise argparse.ArgumentTypeError("mute-range must be FSTART:FSTOP in Hz")
        a, b = v.split(":", 1)
        out.append((float(a), float(b)))
    return out


def main():
    ap = argparse.ArgumentParser(description="Live FFT + waterfall with mute ranges and markers.")
    # Centering
    ap.add_argument("--freq", type=float, help="Center frequency (Hz).")
    ap.add_argument("--band", type=int, default=24, help="Band hint (24 for 2.4 GHz).")
    ap.add_argument("--channel", type=int, help="Wi-Fi channel number (1/6/11 etc.)")
    # RF and DSP
    ap.add_argument("--rate", type=float, default=20e6, help="Sample rate (Hz).")
    ap.add_argument("--bw", type=float, help="RF bandwidth (Hz). Defaults to --rate.")
    ap.add_argument("--gain", type=float, default=55.0, help="Total gain (dB).")
    ap.add_argument("--lna", type=float, default=30.0)
    ap.add_argument("--tia", type=float, default=9.0)
    ap.add_argument("--pga", type=float, default=16.0)
    ap.add_argument("--lna-path", default="LNAH")
    ap.add_argument("--antenna", default=None)
    ap.add_argument("--driver", default="lime")
    # FFT/plot
    ap.add_argument("--fft", type=int, default=4096)
    ap.add_argument("--wf-rows", type=int, default=240)
    ap.add_argument("--avg", type=float, default=0.6, help="EMA factor [0..1] for PSD smoothing.")
    ap.add_argument("--step-hz", type=float, default=1e6, help="Arrow-key tuning step (Hz).")
    # New features
    ap.add_argument("--mute-range", action="append",
                    help="Mute absolute RF range 'FSTART:FSTOP' (Hz). May be repeated.")
    ap.add_argument("--marker", type=float, action="append",
                    help="Draw a vertical marker at absolute RF (Hz). May be repeated.")

    args = ap.parse_args()
    args.mute_range = parse_mute_ranges(args.mute_range)

    viewer = LiveViewer(args)
    viewer.loop()


if __name__ == "__main__":
    main()

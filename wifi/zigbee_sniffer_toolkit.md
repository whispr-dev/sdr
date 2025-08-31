SDR Wi-Fi / ZigBee Sniffer Toolkit

This toolkit provides scripts and helpers to capture, visualize, and analyze 2.4 GHz band activity using a LimeSDR Mini v2 (or compatible SoapySDR device). It is designed for quick inspection of Wi-Fi, ZigBee (802.15.4), and other ISM-band signals.

Requrements

Python 3.9+
numpy, matplotlib
SoapySDR Python bindings
(optional) sigmf for recording in SigMF format

Make sure LimeSuite and SoapySDR are installed on your system (apt install limesuite soapysdr-tools on Ubuntu/Debian).

Scripts
1. wifi_scan.py
Scans Wi-Fi channels and logs power/FFT snapshots to CSV and plots.
`python3 wifi_scan.py --band 24 --channels 1 6 11 --rate 20000000 --nsamp 4096`
Outputs:
wifi_scan_TIMESTAMP.csv with per-channel powers
PSD plots per channel in plots/

2. wifi_record_channel.py
Record IQ data to file (SigMF format if available).
`bash bin/capture_sigmf.sh 2437000000 40000000 30 55 captures/`
This captures 30 s of IQ at 40 Msps, centered at 2437 MHz (Wi-Fi ch6), gain 55 dB.
Output: captures/wifi_24_ch6_2437000000_<EPOCH>.sigmf-data + .sigmf-meta

3. analyze/periodic_bin_finder.py
Look for periodic energy (e.g. ZigBee beacons) in a capture.
```
python3 analyze/periodic_bin_finder.py \
  --basename captures/wifi_24_ch6_2437000000_1756604205 \
  --center-hz 2437000000 --rate 40000000 --nfft 4096 --top-bins 10
```
  
4. analyze/cfile_to_sigmf.py
Convert .cfile + .json pairs into SigMF .sigmf-data/.sigmf-meta.
`python3 analyze/cfile_to_sigmf.py --cfile mycapture.cfile --meta mycapture.json1`

5. wifi_live_fft.py (NEW)
Interactive live FFT + waterfall viewer.
Features:
Arrow-key retuning
Gain up/down
Smoothing average
NEW: --mute-range and --marker options
```
ython3 wifi_live_fft.py \
  --freq 2437000000 --rate 40000000 --bw 40000000 \
  --gain 55 --fft 4096 --wf-rows 300 --avg 0.6 --step-hz 1000000 \
  --mute-range 2404000000:2406000000 \
  --marker 2405000000
```
USB2 cleaner capture (10 Msps):
```
python3 wifi_live_fft.py \
  --freq 2437000000 --rate 10000000 --bw 10000000 \
  --gain 55 --fft 4096 --avg 0.6 \
  --mute-range 2404000000:2406000000 --marker 2405000000
```
Controls
`←` / `→` tune center by step size (--step-hz, default 1 MHz)
`↑` / `↓` gain ±2 dB
`q` or `Esc` quit

Example
When you mute 2405 MHz, the ZigBee beacon vanishes from the plot, leaving you a clean Wi-Fi view. The dashed marker still shows its true frequency.
```
Directory Layout

sdr_toolkit/
├── bin/
│   ├── scan_24.sh
│   ├── scan_5.sh
│   └── capture_sigmf.sh
├── wifi/
│   ├── wifi_scan.py
│   ├── wifi_record_channel.py
│   ├── wifi_live_fft.py   # live viewer with mute/marker
├── analyze/
│   ├── periodic_bin_finder.py
│   └── cfile_to_sigmf.py
├── captures/              # IQ + SigMF
├── plots/                 # auto-generated PSD plots
├── csvs/                  # channel scan CSV logs
└── README.md
```

Tips
- Use USB2.0 mode when inspecting 2.4 GHz. USB3 radiates spurs in the Wi-Fi band.0
- For Wi-Fi inspection, center at 2412, 2437, 2462 MHz (ch1,6,11).
- For ZigBee/smart-meter beacons, check 2405 MHz (ch11) upward in 5 MHz steps.
- Run on battery for cleanest floor (mains adapters can inject wideband hash).

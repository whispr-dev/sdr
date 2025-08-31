# LimeSDR Mini v2 Wi-Fi Exploration Toolkit
```
note: LimeSDR Mini v2 max usable RF is ~3.8 GHz; 5 GHz Wi-Fi centers are beyond hardware range without an external downconverter.
  band_24:
    channel_bw_hz: 20000000
    channels:
      1:  2412000000
      2:  2417000000
      3:  2422000000
      4:  2427000000
      5:  2432000000
      6:  2437000000
      7:  2442000000
      8:  2447000000
      9:  2452000000
      10: 2457000000
      11: 2462000000
      12: 2467000000
      13: 2472000000


  band_5:
    channel_bw_hz: 20000000
    non_dfs_channels:
      36: 5180000000
      40: 5200000000
      44: 5220000000
      48: 5240000000
```

README.md (extended with visuals)
LimeSDR Mini v2 Wi-Fi Exploration Toolkit

This repo contains helper scripts to capture, visualize, and analyze 2.4 GHz Wi-Fi and other signals using the LimeSDR Mini v2.0 with SoapySDR. It supports both live spectrum/waterfall viewing and record-to-disk workflows with SigMF or raw .cfile formats.

📦 Prerequisites

Install LimeSuite + SoapySDR + rx_tools:
```
sudo apt-get update
sudo apt-get install -y git build-essential cmake pkg-config \
    limesuite limesuite-udev limesuite-gtk \
    soapysdr-module-lms7 soapysdr-tools \
    sox pulseaudio-utils alsa-utils
```
Check that your LimeSDR is detected:
```
LimeUtil --find
SoapySDRUtil --probe="driver=lime"
```
Optional: build rx_tools for simple IQ/FM commands:
```
git clone https://github.com/rxseger/rx_tools.git
cd rx_tools && mkdir build && cd build
cmake ..
make -j$(nproc)
sudo make install
sudo ldconfig

```
see:

```
📂 Directory Layout

sdr/
 ├── bin/                # shell wrappers for quick use
 │   ├── capture_sigmf.sh
 │   ├── capture_cfile.sh
 │   └── ...
 ├── wifi/
 │   ├── wifi_record_channel.py
 │   ├── wifi_record_freq_lite.py
 │   └── wifi_live_fft.py
 └── analyze/
     ├── periodic_bin_finder.py
     ├── fix_sigmf_meta.py
     └── fix_sigmf_meta_batch.py
```

🟢 Live Viewing
Run a live FFT + waterfall:
`python3 /home/wofl/sdr/wifi/wifi_live_fft.py --freq 2437000000 --rate 40000000 --gain 55`

← / → arrow keys: retune center frequency.
Top subplot = averaged FFT.
Bottom subplot = waterfall (time vs frequency).
Look for broad humps (~20 MHz wide) = Wi-Fi channels.
Thin repeating lines often indicate narrowband interferers (ZigBee, USB3 noise, etc.).
Example: Wi-Fi bursts on channel 6
Notice the broad “raised floor” ~20 MHz wide — that’s Wi-Fi OFDM.
💾 Capturing IQ Data
1. SigMF Recorder

Wrapper script:
`bash /home/wofl/sdr/bin/captwifi_24_ch6_2437000000_<epoch>.sigmf-data   # raw IQ
wifi_24_ch6_2437000000_<epoch>.sigmf-meta   # metadata
ure_sigmf.sh <center_Hz> <samp_rate_Hz> <seconds> <gain_dB> <outdir>`
Example:
`/home/wofl/sdr/bin/capture_sigmf.sh 2437000000 40000000 30 55 /home/wofl/sdr/wifi/captures`

Output:
```
wifi_24_ch6_2437000000_<epoch>.sigmf-data   # raw IQ
wifi_24_ch6_2437000000_<epoch>.sigmf-meta   # metadata
```

2. Lightweight .cfile Recorder
If you don’t want SigMF:
`/home/wofl/sdr/bin/capture_cfile.sh 2437000000 40000000 30 55 /home/wofl/sdr/wifi/captures`

Output:
`iq_2437000000Hz_40000000sps_30s_<epoch>.cfile   # raw IQ`
`iq_2437000000Hz_40000000sps_30s_<epoch>.json    # metadata`


🛠 Meta File Fixes
If a .sigmf-data exists but no .sigmf-meta:

Single File
```
python3 /home/wofl/sdr/analyze/fix_sigmf_meta.py \
  /home/wofl/sdr/wifi/captures/wifi_24_ch6_2437000000_1756604205.sigmf-data \
  --rate 40000000 --center 2437000000
```

Batch Mode
Process all captures in a folder:
```
python3 /home/wofl/sdr/analyze/periodic_bin_finder.py \
  --basename /home/wofl/sdr/wifi/captures/wifi_24_ch6_2437000000_1756604205 \
  --nfft 4096 --top-bins 10
```

Output (console + CSV):
```
Top periodic bins:
  2452.123 MHz  (bin 2871)  ~1.00 ms period  power 3.45e+04
  2439.876 MHz  (bin 1982)  ~102.40 ms period power 2.11e+04
```

Interpretation:
~1 ms periodicity → often USB/SMPS interference.
~102 ms periodicity → Wi-Fi beacon frames.
Wide humps instead of lines → real Wi-Fi packet bursts.

Example: Single periodic source
Thin vertical stripes, evenly spaced = one strong periodic interferer (not Wi-Fi packets).

⚡️ Quick Tips
Always ignore the DC spike in the center bin — that’s an SDR artifact.
Arrow keys in live mode let you sweep across channels.
Use --bw equal to the sample rate for flatter passband.
For Wi-Fi: interesting centers are 2412, 2437, 2462 MHz (channels 1/6/11).
If signals vanish with antenna unplugged, they’re real RF; if they stay, they’re local noise/artifacts.

🔮 Next Steps
Add multi-channel sweeps (ch1/ch6/ch11 loop).
Build a GTK/Qt front-end for live tuning.
Auto-decode 802.11 beacons with gr-wifi (future work).

📝 License
MIT — do as you wish, fren.







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

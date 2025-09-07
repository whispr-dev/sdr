How this slots into your Wi-Fi analyzer

Capture (this tool): lock onto a single channel at 20 MS/s CF32, save chunked I/Q.

Channel conditioned buffer: optional DC notch, frequency fine-tune, AGC, and resampler (e.g., rational resample if your decoder prefers 20.0e6 exactly).

802.11 OFDM pipeline: your existing demod layer consumes CF32 blocks. Keep this process boundary clean (e.g., ZeroMQ or shared memory ring).

MAC parsing: radiotap-like metadata you compute (timestamp, RSSI, CFO, SNR) + payload; hand to your MAC analyzer/PCAP writer.

Multiplexed sweeps: either run N processes with different centers (requires multiple tuners/ADC BW), or do a sweep scheduler that parks per-channel for X ms to detect beacons, then focuses on the busiest.

Remote RF farm: use SoapyRemote to centralize capture; keep demod/analysis on a GPU box. 
GitHub

Must-set controls (quick checklist)

setSampleRate(RX, ch, 20e6)

setBandwidth(RX, ch, 22e6–25e6)

setFrequency(RX, ch, 2412e6 + 5e6*(n-1)) (n=1..13; 14=2484e6) 
Wikipedia

setGain(RX, ch, G) start ~40–50, then tune; avoid AGC at first.

setDCOffsetMode(RX, ch, true) if supported.

setIQBalance(RX, ch, {0,0}) if supported.

setupStream(RX, SOAPY_SDR_CF32); getStreamMTU(); handle SOAPY_SDR_OVERFLOW. 
pothosware.github.io
+1

Optional Python variant (quick start, same behavior)

If you want a Python sibling for rapid prototyping, I can drop a full wifi_capture.py too — but the C++ above is the robust backbone you’ll want under your analyzer.

If you want next: I can wire this to a ZeroMQ ring and give you a clean C API header (libsoapywifi.h) so your demod/decoder can subscribe to CF32 blocks with timestamps, or emit SigMF directly for tooling compatibility. Also happy to add a sweep mode and beacon sniffer to auto-map active channels.

Refs: official SoapySDR C++/C API docs and SoapyRemote. 
GitHub
+1
pothosware.github.io
+1
# Wi-Fi Packet Capture and Analysis with SoapySDR and Scapy

import time
import numpy as np
import SoapySDR
import struct
from scapy.all import Ether, Dot11, RadioTap, Raw, hexdump

# --- User-defined parameters ---
SAMPLE_RATE = 10e6  # Hz
CENTER_FREQ = 2.412e9  # Hz (This is Wi-Fi Channel 1)
SSID_TO_FIND = "your_ssid_here"
CAPTURE_FILE = "wifi_capture.bin"
CAPTURE_DURATION_SECONDS = 5

def capture_wifi_data(duration_seconds):
    """
    Captures raw IQ data from the SDR and saves it to a file.

    Args:
        duration_seconds (int): The duration of the capture in seconds.
    """
    print("Searching for SDR devices...")
    try:
        if not hasattr(SoapySDR, 'Device'):
            raise AttributeError("module 'SoapySDR' has no attribute 'Device'.")
        results = SoapySDR.Device.enumerate("driver=lime")
    except AttributeError as e:
        print(f"Error: {e}")
        return

    if not results:
        print("No SoapySDR devices found with driver 'lime'.")
        return

    sdr_info = results[0]
    print(f"Found SDR device: {sdr_info['label']}")

    sdr = SoapySDR.Device(sdr_info)
    sdr.setGain(SoapySDR.SOAPY_SDR_RX, 0, 50)
    sdr.setSampleRate(SoapySDR.SOAPY_SDR_RX, 0, SAMPLE_RATE)
    sdr.setFrequency(SoapySDR.SOAPY_SDR_RX, 0, CENTER_FREQ)
    
    stream = sdr.setupStream(SoapySDR.SOAPY_SDR_RX, SoapySDR.SOAPY_SDR_CF32, [0], {})
    sdr.activateStream(stream)

    buffer_size = 8192
    rx_buffer = np.zeros(buffer_size, dtype=np.complex64)
    num_samples_to_capture = int(SAMPLE_RATE * duration_seconds)
    total_samples_captured = 0

    print(f"Starting {duration_seconds} second capture to '{CAPTURE_FILE}'...")
    
    with open(CAPTURE_FILE, "wb") as f:
        while total_samples_captured < num_samples_to_capture:
            sr = sdr.readStream(stream, [rx_buffer], buffer_size, timeoutUs=1000000)
            ret = sr.ret
            if ret > 0:
                # Write the raw bytes of the complex samples to the file
                f.write(rx_buffer[:ret].tobytes())
                total_samples_captured += ret
            else:
                print(f"Error reading stream: {ret}")
                break

    sdr.deactivateStream(stream)
    sdr.closeStream(stream)
    print(f"Capture finished. Saved {total_samples_captured} samples.")

def parse_wifi_packets_from_file(filepath):
    """
    Attempts to parse raw bytes from a file as Wi-Fi packets using Scapy.

    Args:
        filepath (str): The path to the binary file containing raw IQ samples.
    """
    try:
        with open(filepath, "rb") as f:
            raw_data = f.read()

        # NOTE: This is a conceptual step. Directly parsing raw IQ samples as a
        # Wi-Fi packet is not possible. A real-world solution requires a
        # specialized demodulation block (e.g., in a library like GNU Radio)
        # to produce a stream of packets that Scapy can parse.
        # However, this demonstrates the *correct tool* for the job.

        print(f"\nAttempting to parse '{filepath}' with Scapy...")
        
        # In a real scenario, you would be feeding a stream of demodulated bytes.
        # This is a placeholder to show the syntax.
        # Here we're just trying to parse a small chunk of the file
        # which will likely not align with a packet boundary.
        
        # Let's take a small chunk of the raw data to "pretend" it's a packet
        # This is for demonstration purposes only.
        chunk = raw_data[1000:2000]

        try:
            # We first try to parse it with the RadioTap header, common for Wi-Fi.
            # Then Dot11 is the IEEE 802.11 Wi-Fi protocol layer.
            packet = RadioTap(chunk)
            
            # Print a summary of the decoded packet
            print("\n--- Scapy Packet Summary ---")
            packet.summary()
            
            print("\n--- Packet Hex Dump ---")
            hexdump(packet)

        except Exception as e:
            print(f"Scapy failed to parse the data. This is expected as the data is raw IQ samples, not a demodulated packet stream.")
            print(f"Error: {e}")
            print("\nTo do this properly, you need a demodulator that outputs a stream of 802.11 frames, which Scapy can then analyze.")

    except FileNotFoundError:
        print(f"Error: The file '{filepath}' was not found.")

if __name__ == "__main__":
    # First, capture some raw data from the SDR.
    capture_wifi_data(CAPTURE_DURATION_SECONDS)

    # Then, attempt to parse the captured data.
    parse_wifi_packets_from_file(CAPTURE_FILE)

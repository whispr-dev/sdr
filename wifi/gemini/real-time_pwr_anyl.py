# Real-time signal analysis with SoapySDR and numpy FFT

import time
import numpy as np
import SoapySDR
import struct

# --- User-defined parameters ---
SAMPLE_RATE = 20e6  # Hz (Must be higher than the bandwidth of the signal you want to analyze)
CENTER_FREQ = 2.412e9  # Hz (Wi-Fi Channel 1)

def listen_and_analyze():
    """
    Listens for Wi-Fi signals using the SDR, performs a real-time FFT, and
    analyzes the signal's power.
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

    # Open the device and configure it
    sdr = SoapySDR.Device(sdr_info)
    sdr.setGain(SoapySDR.SOAPY_SDR_RX, 0, 50)
    sdr.setSampleRate(SoapySDR.SOAPY_SDR_RX, 0, SAMPLE_RATE)
    sdr.setFrequency(SoapySDR.SOAPY_SDR_RX, 0, CENTER_FREQ)
    
    stream = sdr.setupStream(SoapySDR.SOAPY_SDR_RX, SoapySDR.SOAPY_SDR_CF32, [0], {})
    sdr.activateStream(stream)

    buffer_size = 8192
    rx_buffer = np.zeros(buffer_size, dtype=np.complex64)

    print(f"Listening on {CENTER_FREQ/1e9} GHz...")

    try:
        while True:
            sr = sdr.readStream(stream, [rx_buffer], buffer_size, timeoutUs=100000)
            ret = sr.ret
            
            if ret > 0:
                # --- This is the core signal processing step! ---
                # 1. Take the received IQ samples and perform a Fast Fourier Transform.
                #    The FFT shifts the signal from the time domain to the frequency domain.
                fft_result = np.fft.fft(rx_buffer)

                # 2. Calculate the power of each frequency component.
                #    We square the absolute value of the FFT result to get the power.
                power = np.abs(fft_result)**2
                
                # 3. Calculate the average power of the entire received signal.
                #    This gives us a single value to monitor.
                avg_power = np.mean(power)

                # 4. Convert the average power to a decibel (dB) scale for easier reading.
                #    The dB scale is logarithmic and more intuitive for signal strength.
                power_db = 10 * np.log10(avg_power) if avg_power > 0 else -100
                
                print(f"Average Signal Power: {power_db:.2f} dB")
                time.sleep(0.5)

            else:
                print(f"Error reading stream: {ret}")

    except KeyboardInterrupt:
        print("\nStopping listener.")
    finally:
        # Clean up the stream and close the device
        sdr.deactivateStream(stream)
        sdr.closeStream(stream)

if __name__ == "__main__":
    listen_and_analyze()

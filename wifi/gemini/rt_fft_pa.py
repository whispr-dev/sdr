# Real-time FFT power analysis to find the strongest signal in a band.

import time
import numpy as np
import SoapySDR
import struct

# --- User-defined parameters ---
SAMPLE_RATE = 20e6  # Hz (Must be higher than the bandwidth of the signal you want to analyze)
CENTER_FREQ = 2.44e9  # Hz (This is a good spot to check for multiple Wi-Fi channels)

def find_strongest_signal():
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
                # 1. Take the received IQ samples and perform a Fast Fourier Transform.
                fft_result = np.fft.fft(rx_buffer)

                # 2. Shift the zero-frequency component to the center of the array.
                #    This makes the visualization and analysis more intuitive.
                fft_shifted = np.fft.fftshift(fft_result)

                # 3. Calculate the power of each frequency component.
                power_spectrum = np.abs(fft_shifted)**2
                
                # 4. Find the frequency bin with the maximum power.
                max_power_idx = np.argmax(power_spectrum)

                # 5. Calculate the corresponding frequency in Hz.
                #    The frequency step is SAMPLE_RATE / buffer_size.
                freq_step = SAMPLE_RATE / buffer_size
                strongest_freq_offset = (max_power_idx - buffer_size / 2) * freq_step
                strongest_freq = CENTER_FREQ + strongest_freq_offset
                
                # 6. Convert the power to a decibel (dB) scale for easier reading.
                max_power_db = 10 * np.log10(power_spectrum[max_power_idx]) if power_spectrum[max_power_idx] > 0 else -100
                
                print(f"Strongest Signal: {strongest_freq/1e9:.4f} GHz | Power: {max_power_db:.2f} dB")
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
    find_strongest_signal()

# This script uses the SoapySDR library to perform a conceptual "power scan"
# of a Wi-Fi band. It is a conceptual example and does not perform full
# Wi-Fi signal decoding, as that is a very complex process. Instead, it
# demonstrates how to control a software-defined radio (SDR) and read raw
# signal data.

import SoapySDR
from SoapySDR import * # Import all functions
import numpy as np

def scan_wifi_band(freq_start, freq_end, step_size, sample_rate, gain):
    # Find all LimeSDR devices connected to the system.
    # The "driver=lime" argument specifies we are looking for LimeSDR devices.
    results = SoapySDR.Device.enumerate("driver=lime")
    if not results:
        print("No LimeSDR device found!")
        return
    
    # Create the device handle for the first device found.
    # SoapySDR.Device(results[0]) creates an instance of the SDR device.
    sdr = SoapySDR.Device(results[0])
    
    try:
        # Set the sample rate for the receiver.
        # This determines the bandwidth of the signal we are receiving at any given time.
        # Here we use the default channel 0 for the receiver.
        sdr.setSampleRate(SOAPY_SDR_RX, 0, sample_rate)

        # Set the center frequency. This is the starting point for our scan.
        # The corrected line: 'setFrequency' expects the frequency as a float.
        sdr.setFrequency(SOAPY_SDR_RX, 0, freq_start)

        # Set the gain. A higher gain amplifies the received signal.
        sdr.setGain(SOAPY_SDR_RX, 0, gain)
        
        # Create a stream object for receiving data.
        # SOAPY_SDR_CF32 means we will receive complex 32-bit float data.
        rx_stream = sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
        
        # Activate the stream to start receiving data.
        sdr.activateStream(rx_stream)
        
        print("Scanning...")
        
        # Loop through the frequency range, stepping by the defined size.
        for freq in np.arange(freq_start, freq_end, step_size):
            # Tune the SDR to the current frequency in the loop.
            sdr.setFrequency(SOAPY_SDR_RX, 0, freq)
            
            # Create a numpy array to store the IQ samples.
            rx_buff = np.zeros(1024, dtype=np.complex64)
            
            # Read samples from the device into the buffer.
            # This is a blocking call that will wait until data is available.
            sr = sdr.readStream(rx_stream, [rx_buff], len(rx_buff), timeoutUs=100000)
            
            # This part of the code is for conceptual signal analysis.
            # We calculate the average power of the signal at the current frequency.
            # A higher power value indicates a stronger signal at this frequency.
            avg_power = np.mean(np.abs(rx_buff)**2)
            
            # Convert power to dB for a more meaningful scale.
            power_db = 10 * np.log10(avg_power) if avg_power > 0 else -100
            
            # Print the frequency and its corresponding signal power.
            print(f"Frequency: {freq/1e9:.3f} GHz | Average Power: {power_db:.2f} dB")
        
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        # Deactivate and close the stream and device to free up resources.
        if 'sdr' in locals() and sdr:
            if 'rx_stream' in locals() and rx_stream:
                sdr.deactivateStream(rx_stream)
                sdr.closeStream(rx_stream)
            sdr.close()
        print("Scan finished.")

# Example usage with corrected parameters
scan_wifi_band(
    freq_start=2.412e9,  # 2.412 GHz (Wi-Fi Channel 1)
    freq_end=2.484e9,    # 2.484 GHz (Wi-Fi Channel 14)
    step_size=5e6,       # 5 MHz step size
    sample_rate=20e6,    # 20 Msps
    gain=50,
)

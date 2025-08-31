# Ddemodulation script
import time
import numpy as np
import SoapySDR

# User-defined parameters
SAMPLE_RATE = 10e6  # Hz
CENTER_FREQ = 2.4e9  # Hz
SSID_TO_FIND = "your_ssid_here"  # Replace with the SSID you want to find

def demodulate_wifi(samples, sample_rate):
    """
    Demodulates Wi-Fi signals from IQ samples and attempts to identify SSIDs.
    This is a simplified example. A full demodulator would be much more complex.
    
    Args:
        samples (numpy.ndarray): The complex IQ samples.
        sample_rate (float): The sample rate in Hz.
        
    Returns:
        list: A list of detected SSIDs.
    """
    # Placeholder for a more complex demodulation process.
    # In a real-world scenario, this would involve:
    # 1. Synchronization (Preamble detection)
    # 2. Channel estimation
    # 3. OFDM demodulation (FFT)
    # 4. QAM decoding
    # 5. MAC header parsing to find the SSID.
    
    print("Demodulating Wi-Fi signals...")
    detected_ssids = []
    
    # A simple and very naive placeholder for finding an SSID.
    # This is not a real-world solution, but illustrates the concept.
    if SSID_TO_FIND in "some_decoded_data_from_the_signal":
        detected_ssids.append(SSID_TO_FIND)
    
    return detected_ssids

def listen_for_ssid(ssid):
    """
    Listens for a specific Wi-Fi SSID using the SDR.
    
    Args:
        ssid (str): The SSID to listen for.
    """
    global SSID_TO_FIND
    SSID_TO_FIND = ssid
    
    # Check for available SDR devices
    print("Searching for SDR devices...")
    try:
        # The correct way to enumerate devices is as a static method of the SoapySDR.Device class.
        if not hasattr(SoapySDR, 'Device'):
            raise AttributeError("module 'SoapySDR' has no attribute 'Device'. This indicates an issue with your Python bindings or installation.")
        
        results = SoapySDR.Device.enumerate("driver=lime")
    except AttributeError as e:
        print(f"Error: {e}")
        print("Please ensure your SoapySDR Python bindings are correctly installed and linked to your hardware drivers. You may need to reinstall the python-soapysdr package.")
        return

    if not results:
        print("No SoapySDR devices found with driver 'lime'. Please ensure your hardware is connected.")
        return

    # Select the first device found
    sdr_info = results[0]
    print(f"Found SDR device: {sdr_info['label']}")

    # Open the device using the correct constructor
    sdr = SoapySDR.Device(sdr_info)

    # Set gain, sample rate, and frequency BEFORE activating the stream
    sdr.setGain(SoapySDR.SOAPY_SDR_RX, 0, 50)  # Set the gain
    sdr.setSampleRate(SoapySDR.SOAPY_SDR_RX, 0, SAMPLE_RATE)
    sdr.setFrequency(SoapySDR.SOAPY_SDR_RX, 0, CENTER_FREQ)
    
    # Set up the stream
    stream = sdr.setupStream(SoapySDR.SOAPY_SDR_RX, SoapySDR.SOAPY_SDR_CF32, [0], {})
    sdr.activateStream(stream)

    # Create a buffer for the samples
    buffer_size = 8192  # Must be a power of 2
    rx_buffer = np.zeros(buffer_size, dtype=np.complex64)

    print(f"Listening for SSID: '{ssid}' at {CENTER_FREQ/1e9} GHz...")

    try:
        # Loop to continuously read from the SDR
        for _ in range(10):  # Read 10 blocks of samples as an example
            sr = sdr.readStream(stream, [rx_buffer], buffer_size, timeoutUs=100000)
            ret = sr.ret  # Returns the number of samples read or a negative error code
            
            if ret > 0:
                print(f"Read {ret} samples.")
                detected_ssids = demodulate_wifi(rx_buffer[:ret], SAMPLE_RATE)
                if detected_ssids:
                    print(f"Detected SSID: {detected_ssids}")
                    return
            else:
                print(f"Error reading stream: {ret}")

    finally:
        # Clean up the stream and close the device
        sdr.deactivateStream(stream)
        sdr.closeStream(stream)

# Main execution
if __name__ == "__main__":
    # Call the main function to listen for the SSID.
    listen_for_ssid("your_ssid_here")

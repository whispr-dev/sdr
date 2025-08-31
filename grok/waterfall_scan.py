import subprocess
import re

def scan_wifi(interface="wlan0"):
    try:
        # Run iwlist to scan Wi-Fi networks
        result = subprocess.run(["iwlist", interface, "scanning"], capture_output=True, text=True)
        output = result.stdout

        # Parse SSIDs and signal strengths
        networks = []
        cells = output.split("Cell ")[1:]  # Split by cell
        for cell in cells:
            ssid = re.search(r"ESSID:\"(.*?)\"", cell)
            signal = re.search(r"Signal level=(-?\d+) dBm", cell)
            if ssid and signal:
                networks.append({"SSID": ssid.group(1), "Signal": signal.group(1)})
        
        # Print results
        if networks:
            print("Detected Wi-Fi Networks:")
            for net in networks:
                print(f"SSID: {net['SSID']}, Signal Strength: {net['Signal']} dBm")
        else:
            print("No Wi-Fi networks detected.")
    except Exception as e:
        print(f"Error scanning Wi-Fi: {e}")

if __name__ == "__main__":
    # Replace 'wlan0' with your Wi-Fi interface name
    scan_wifi("wlan0")

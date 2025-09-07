# WSL/Ubuntu example
sudo apt-get update
sudo apt-get install -y cmake g++ libsoapysdr-dev soapysdr-tools
# also install your device module, e.g.:
#   sudo apt-get install -y soapysdr-module-lms7  # LimeSDR
#   sudo apt-get install -y soapysdr-module-rtlsdr
mkdir -p /home/wofl/sdr/soapywifi/build && cd /home/wofl/sdr/soapywifi/build
cmake -S .. -B . -DCMAKE_BUILD_TYPE=Release
cmake --build . -j
./wifi_capture --args driver=lime --chan 6 --rate 20e6 --bw 25e6 --gain 45 --secs 10 --out ./captures

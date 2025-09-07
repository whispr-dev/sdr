pacman -S --needed mingw-w64-x86_64-soapysdr mingw-w64-x86_64-cmake mingw-w64-x86_64-toolchain
mkdir -p /c/sdr/soapywifi/build && cd /c/sdr/soapywifi/build
cmake -G "Ninja" -S .. -B . -DCMAKE_BUILD_TYPE=Release
cmake --build . -j
./wifi_capture.exe --args driver=lime --chan 1 --rate 20e6 --bw 25e6 --gain 45 --secs 10 --out ./captures

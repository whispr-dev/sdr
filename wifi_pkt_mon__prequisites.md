Complete Setup for Wi-Fi Packet Monitoring

This guide will walk you through setting up your environment from scratch to run the wifi_pkt_mon.py script. We'll install all dependencies, build the necessary GNU Radio module, and configure the Python environment correctly to avoid past issues.
1. Install System Prerequisites

First, make sure you have the essential tools and libraries for building from source.

sudo apt-get update
sudo apt-get install git cmake build-essential libboost-all-dev libgnuradio-dev

2. Set Up Your Python Virtual Environment

Navigate to your project directory and create a fresh virtual environment. This keeps your project's dependencies isolated and clean.

cd /home/wofl/sdr/wifi/gemini/
python3 -m venv wifiscan-py311
source wifiscan-py311/bin/activate

3. Clone and Build the gr-ieee802-11 Module

We need to get the gr-ieee802-11 module and build it for your system. We will use the master branch for better compatibility with modern GNU Radio versions.

git clone [https://github.com/bastibl/gr-ieee802-11.git](https://github.com/bastibl/gr-ieee802-11.git)
cd gr-ieee802-11
mkdir build
cd build
cmake ..
make -j$(nproc)
sudo make install

4. Configure the Python Path

This is the most critical step to ensure your virtual environment can find the module we just installed. We will create a direct symbolic link from your virtual environment's site-packages directory to the system-installed module.

cd /home/wofl/sdr/wifi/gemini/wifiscan-py311/lib/python3.12/site-packages/
ln -s /usr/local/lib/python3.12/dist-packages/ieee802_11

5. Run the Corrected Script

Now that everything is installed and linked correctly, you can use the final, corrected version of your script. I've included it in a separate file on the right side of the screen.

cd /home/wofl/sdr/wifi/gemini/
python3 wifi_pkt_mon.py

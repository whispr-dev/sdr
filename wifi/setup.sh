#!/usr/bin/env bash
set -euo pipefail

sudo apt-get update
# Core SDR bits
sudo apt-get install -y limesuite limesuite-udev limesuite-gtk \
  soapysdr-tools soapysdr-module-lms7 \
  python3 python3-pip python3-venv

# Python stack (user install)
python3 -m pip install --user --upgrade pip
python3 -m pip install --user numpy matplotlib sigmf SoapySDR
echo "Done. If using WSL: ensure your Lime is passed through and udev rules are fine."

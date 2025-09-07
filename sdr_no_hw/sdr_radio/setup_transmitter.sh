#!/usr/bin/env bash
# Save with LF line endings.
set -euo pipefail
IFS=$'\n\t'

# ================================================================
# Auto-detect environment & base path
# Priority:
#   1) SDR_BASE env var (explicit override)
#   2) Existing directory checks (/mnt/d/... for WSL, /d/... for Git Bash, /cygdrive/d/... for Cygwin)
#   3) Fallback: $HOME/code/sdr/sdr_no_hw
# ================================================================
detect_base() {
  # explicit override
  if [[ -n "${SDR_BASE:-}" ]]; then
    echo "${SDR_BASE}"
    return
  fi

  # WSL detection
  if grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null; then
    if [[ -d /mnt/d/code/sdr/sdr_no_hw ]]; then
      echo "/mnt/d/code/sdr/sdr_no_hw"
      return
    fi
  fi

  # Git Bash / MSYS / MinGW
  case "${OSTYPE:-}" in
    msys*|cygwin*|win32*|mingw*)
      if [[ -d /d/code/sdr/sdr_no_hw ]]; then
        echo "/d/code/sdr/sdr_no_hw"
        return
      fi
      if [[ -d /cygdrive/d/code/sdr/sdr_no_hw ]]; then
        echo "/cygdrive/d/code/sdr/sdr_no_hw"
        return
      fi
    ;;
  esac

  # Try likely paths even if not detected
  if [[ -d /mnt/d/code/sdr/sdr_no_hw ]]; then
    echo "/mnt/d/code/sdr/sdr_no_hw"
    return
  fi
  if [[ -d /d/code/sdr/sdr_no_hw ]]; then
    echo "/d/code/sdr/sdr_no_hw"
    return
  fi
  if [[ -d /cygdrive/d/code/sdr/sdr_no_hw ]]; then
    echo "/cygdrive/d/code/sdr/sdr_no_hw"
    return
  fi

  # Fallback to HOME
  echo "${HOME}/code/sdr/sdr_no_hw"
}

ROOT_BASE="$(detect_base)"
PROJECT_ROOT="${ROOT_BASE}/AM_sdr_pico2_final"
USER_SOURCE_DIR="${ROOT_BASE}/sdr_radio"
OUTPUT_DIR="${ROOT_BASE}/firmware"

MPY_VERSION="v1.25.0"
BOARD="RPI_PICO2"

# Tools (override via env if desired)
WGET_BIN="$(command -v wget || true)"
CURL_BIN="$(command -v curl || true)"
GIT_BIN="$(command -v git || true)"
MAKE_BIN="$(command -v make || true)"

bail() { printf "FATAL: %s\n" "$*" >&2; exit 1; }
say()  { printf "%s\n" "$*"; }

need() {
  command -v "$1" >/dev/null 2>&1 || bail "missing required tool: $1"
}

download() {
  local url="$1" out="$2"
  if [[ -n "${WGET_BIN}" ]]; then
    wget -q -O "$out" "$url"
  elif [[ -n "${CURL_BIN}" ]]; then
    curl -L --silent --show-error -o "$out" "$url"
  else
    bail "neither wget nor curl available to download: $url"
  fi
}

# ================================================================
# Sanity checks
# ================================================================
need git
need sed
need awk
need "${MAKE_BIN:-make}"

# Ensure base directories exist (create if fallback path)
mkdir -p "${ROOT_BASE}" "${OUTPUT_DIR}"

[[ -d "${USER_SOURCE_DIR}" ]] || bail "User source directory not found: ${USER_SOURCE_DIR}"

say "--- START: Definitive build (manual vendor + correct paths) ---"
say "ROOT_BASE      = ${ROOT_BASE}"
say "PROJECT_ROOT   = ${PROJECT_ROOT}"
say "USER_SOURCE_DIR= ${USER_SOURCE_DIR}"
say "OUTPUT_DIR     = ${OUTPUT_DIR}"
say "BOARD          = ${BOARD}"
say "MPY_VERSION    = ${MPY_VERSION}"

# ================================================================
# [1/6] Setup project structure
# ================================================================
say "--- [1/6] Setting up project structure"
rm -rf "${PROJECT_ROOT}"
mkdir -p "${PROJECT_ROOT}"

# ================================================================
# [2/6] Clone MicroPython and submodules (plus pico-extras)
# ================================================================
say "--- [2/6] Cloning MicroPython @ ${MPY_VERSION}"
git clone --depth 1 -b "${MPY_VERSION}" https://github.com/micropython/micropython.git "${PROJECT_ROOT}/micropython"
cd "${PROJECT_ROOT}/micropython"
git submodule update --init --recursive

# pico-extras as a submodule
if [[ ! -d "lib/pico-extras" ]]; then
  git submodule add https://github.com/raspberrypi/pico-extras.git lib/pico-extras
fi
git submodule update --init lib/pico-extras

# ================================================================
# [3/6] Manual vendoring of CMSIS_5
# ================================================================
say "--- [3/6] Vendoring CMSIS_5"
mkdir -p ./lib/vendor/CMSIS_5
download "https://github.com/ARM-software/CMSIS_5/archive/refs/tags/5.9.0.zip" "cmsis.zip"
unzip -q "cmsis.zip" -d ./lib/vendor/
mv ./lib/vendor/CMSIS_5-5.9.0/* ./lib/vendor/CMSIS_5/
rm -f "cmsis.zip"
rm -rf ./lib/vendor/CMSIS_5-5.9.0/

ARM_MATH_PATH="./lib/vendor/CMSIS_5/CMSIS/DSP/Include/arm_math.h"
say "Verifying arm_math.h at: ${ARM_MATH_PATH}"
[[ -f "${ARM_MATH_PATH}" ]] || bail "arm_math.h not found after vendoring"

# ================================================================
# [4/6] Create module directory and copy your sources
# ================================================================
say "--- [4/6] Creating sdr_radio module and copying user sources"
MODULE_PATH="./extmod/sdr_radio"
mkdir -p "${MODULE_PATH}"
cp -f "${USER_SOURCE_DIR}"/* "${MODULE_PATH}/"

# ================================================================
# [5/6] Patch build files for the module + CMSIS-DSP
# ================================================================
say "--- [5/6] Patching MicroPython build files for rp2 port"
cd ./ports/rp2

# 5a) Ensure mpconfigport.h includes our module define
if ! grep -q "MICROPY_PY_SDR_RADIO" mpconfigport.h 2>/dev/null; then
  cp mpconfigport.h mpconfigport.h.bak
  {
    printf "\n// Enable the custom sdr_radio module\n"
    printf "#define MICROPY_PY_SDR_RADIO (1)\n"
  } >> mpconfigport.h
fi

# 5b) Append a CMake block once to include our sources and headers
if ! grep -q "### SDR_RADIO CMAKE BLOCK BEGIN" CMakeLists.txt 2>/dev/null; then
  cp CMakeLists.txt CMakeLists.txt.bak
  cat >> CMakeLists.txt <<'CMAKE_EOF'

### SDR_RADIO CMAKE BLOCK BEGIN
# --- Customization for sdr_radio module ---
# Include paths (module + MicroPython + CMSIS-DSP + pico-extras audio)
include_directories(
    ${MICROPY_DIR}/extmod/sdr_radio
    ${MICROPY_DIR}/py
    ${MICROPY_DIR}/ports/rp2
    ${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/DSP/Include
    ${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/DSP/PrivateInclude
    ${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/Core/Include
    ${MICROPY_DIR}/lib/pico-extras/src/rp2_common/pico_audio_i2s/include
    ${MICROPY_DIR}/lib/pico-extras/src/common/pico_audio/include
    ${MICROPY_DIR}/lib/pico-extras/src/common/pico_util_buffer/include
)

# Curated CMSIS-DSP sources (roll-up C files)
set(CMSIS_DSP_SOURCES
    ${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/DSP/Source/BasicMathFunctions/BasicMathFunctions.c
    ${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/DSP/Source/CommonTables/CommonTables.c
    ${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/DSP/Source/ComplexMathFunctions/ComplexMathFunctions.c
    ${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/DSP/Source/ControllerFunctions/ControllerFunctions.c
    ${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/DSP/Source/FastMathFunctions/FastMathFunctions.c
    ${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/DSP/Source/FilteringFunctions/FilteringFunctions.c
    ${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/DSP/Source/MatrixFunctions/MatrixFunctions.c
    ${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/DSP/Source/StatisticsFunctions/StatisticsFunctions.c
    ${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/DSP/Source/SupportFunctions/SupportFunctions.c
    ${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/DSP/Source/TransformFunctions/TransformFunctions.c
    ${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/DSP/Source/QuaternionMathFunctions/QuaternionMathFunctions.c
)

# Add our module + CMSIS-DSP sources to MicroPython build
list(APPEND MICROPY_SOURCE_PORT
    ${MICROPY_DIR}/extmod/sdr_radio/sdr_radio.c
    ${CMSIS_DSP_SOURCES}
)
list(APPEND MICROPY_SOURCE_QSTR ${MICROPY_DIR}/extmod/sdr_radio/sdr_radio.c)
### SDR_RADIO CMAKE BLOCK END

CMAKE_EOF
fi

# ================================================================
# [6/6] Build firmware
# ================================================================
say "--- [6/6] Building MicroPython firmware for ${BOARD}"
"${MAKE_BIN:-make}" -j4 BOARD="${BOARD}"

FIRMWARE_UF2="build-${BOARD}/firmware.uf2"
[[ -f "${FIRMWARE_UF2}" ]] || bail "firmware not built: ${FIRMWARE_UF2}"

mkdir -p "${OUTPUT_DIR}"
cp -f "${FIRMWARE_UF2}" "${OUTPUT_DIR}/"
ls -l "${OUTPUT_DIR}/firmware.uf2" || true

if command -v arm-none-eabi-nm >/dev/null 2>&1; then
  if arm-none-eabi-nm "build-${BOARD}/firmware.elf" | grep -q "sdr_radio"; then
    say "SUCCESS: sdr_radio symbols present in firmware.elf"
  else
    say "WARNING: sdr_radio symbols not found (check your module name/file)."
  fi
else
  say "NOTE: arm-none-eabi-nm not found; skipping ELF symbol check."
fi

say ""
say "--- BUILD COMPLETE ---"
say "Firmware: ${OUTPUT_DIR}/firmware.uf2"
say "To flash: Hold BOOTSEL on Pico 2, power cycle; copy 'firmware.uf2' to the new USB drive."

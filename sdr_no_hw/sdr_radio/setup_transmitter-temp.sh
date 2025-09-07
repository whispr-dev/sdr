#!/usr/bin/env bash
# Save with LF line endings.
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


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


#!/bin/bash
Set -e # Exit immediately if any command fails
# --- Configuration ---
MPY_VERSION=”v1.25.0”
BOARD=”RPI_PICO2”
PROJECT_ROOT=~/AM_sdr_pico2_final
# This is the directory where you have staged all your working, vendored files.
USER_SOURCE_DIR=~/sdr_radio

# --- Sanity Check ---
If [ ! -d “${USER_SOURCE_DIR}” ]; then
    Echo “Error: User source directory not found at ${USER_SOURCE_DIR}”
    Exit 1
Fi

Echo “--- STARTING THE DEFINITIVE BUILD (MANUAL VENDOR + CORRECT PATHS) ---”

# --- STEPS 1-2: SETUP & VENDORING ---
Echo “--- [1/5] Setting up project structure...”
Rm -rf ${PROJECT_ROOT}
Mkdir -p ${PROJECT_ROOT}

Echo “--- [2/5] Cloning MicroPython and its core submodules...”
Git clone –depth 1 -b ${MPY_VERSION} https://github.com/micropython/micropython.git ${PROJECT_ROOT}/micropython
cd ${PROJECT_ROOT}/micropython
git submodule update --init --recursive

# Add pico-extras, which is separate
Git submodule add https://github.com/raspberrypi/pico-extras.git lib/pico-extras
git submodule update --init lib/pico-extras

# --- BRUTE-FORCE VENDORING of CMSIS ---
# The git submodule process is unreliable. We will download and place the files manually.
Echo “Manually downloading and vendoring CMSIS-DSP library...”
# Create the target directory structure
Mkdir -p ./lib/vendor/CMSIS_5
# Download a known-good version of the library as a ZIP file
Wget -O cmsis.zip https://github.com/ARM-software/CMSIS_5/archive/refs/tags/5.9.0.zip
# Unzip it into a temporary directory
Unzip -q cmsis.zip -d ./lib/vendor/
# Move the contents into our final location
Mv ./lib/vendor/CMSIS_5-5.9.0/* ./lib/vendor/CMSIS_5/
# Clean up
Rm cmsis.zip
Rm -rf ./lib/vendor/CMSIS_5-5.9.0/

# --- VERIFICATION STEP ---
# Check the path where we downloaded the files.
ARM_MATH_PATH=”./lib/vendor/CMSIS_5/CMSIS/DSP/Include/arm_math.h”
Echo “Verifying that arm_math.h exists at ${ARM_MATH_PATH}...”
If [ -f “$ARM_MATH_PATH” ]; then
    Echo “SUCCESS: arm_math.h found in vendored directory.”
Else
    Echo “FATAL ERROR: arm_math.h was NOT found after manual download.”
    Exit 1
Fi

# --- STEP 3: CREATE THE SELF-CONTAINED SDR MODULE ---
Echo “--- [3/5] Creating sdr_radio module and copying all required sources... ---”
MODULE_PATH=./extmod/sdr_radio
Mkdir -p ${MODULE_PATH}
Echo “Copying your staged module files from ${USER_SOURCE_DIR}...”
Cp ${USER_SOURCE_DIR}/* ${MODULE_PATH}/

# --- STEP 4: MODIFY BUILD FILES (THE DEFINITIVE FIX) ---
Echo “--- [4/5] Configuring the MicroPython build... ---”
Cd ./ports/rp2

# 1. Reset and activate the module in the C preprocessor.
Cp mpconfigport.h.orig mpconfigport.h 2>/dev/null || cp mpconfigport.h mpconfigport.h.orig
Echo “” >> mpconfigport.h
Echo “// Enable the custom sdr_radio module” >> mpconfigport.h
Echo “#define MICROPY_PY_SDR_RADIO (1)” >> mpconfigport.h

# 2. Reset and inject the complete module configuration into CMake.
Cp CMakeLists.txt.orig CMakeLists.txt 2>/dev/null || cp CMakeLists.txt CMakeLists.txt.orig
TARGET_LINE_SOURCES=”set(PICO_SDK_COMPONENTS”
CUSTOM_BLOCK_SOURCES=”\
\n# --- Customization for sdr_radio module ---\n\
# We will now build the CMSIS-DSP sources directly into the firmware.\n\
\n\
# Part 1: Add all necessary include paths.\n\
Include_directories(\n\
    \${MICROPY_DIR}/extmod/sdr_radio \n\
    \${MICROPY_DIR}/py \n\
    \${MICROPY_DIR}/ports/rp2 \n\
    # Include paths for CMSIS-DSP Public API, Private Helpers, and Core types.\n\
    \${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/DSP/Include \n\
    \${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/DSP/PrivateInclude \n\
    \${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/Core/Include \n\
    # Your other existing include paths\n\
    \${MICROPY_DIR}/lib/pico-extras/src/rp2_common/pico_audio_i2s/include \n\
    \${MICROPY_DIR}/lib/pico-extras/src/common/pico_audio/include \n\
    \${MICROPY_DIR}/lib/pico-extras/src/common/pico_util_buffer/include \n\
)\n\
\n\
# \n\
# Part 2: Create a list containing ONLY the main ‘roll-up’ source files.\n\
Set(CMSIS_DSP_SOURCES\n\
    \”\${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/DSP/Source/BasicMathFunctions/BasicMathFunctions.c\”\n\
    \”\${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/DSP/Source/CommonTables/CommonTables.c\”\n\
    \”\${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/DSP/Source/ComplexMathFunctions/ComplexMathFunctions.c\”\n\
    \”\${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/DSP/Source/ControllerFunctions/ControllerFunctions.c\”\n\
    \”\${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/DSP/Source/FastMathFunctions/FastMathFunctions.c\”\n\
    \”\${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/DSP/Source/FilteringFunctions/FilteringFunctions.c\”\n\
    \”\${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/DSP/Source/MatrixFunctions/MatrixFunctions.c\”\n\
    \”\${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/DSP/Source/StatisticsFunctions/StatisticsFunctions.c\”\n\
    \”\${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/DSP/Source/SupportFunctions/SupportFunctions.c\”\n\
    \”\${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/DSP/Source/TransformFunctions/TransformFunctions.c\”\n\
    \”\${MICROPY_DIR}/lib/vendor/CMSIS_5/CMSIS/DSP/Source/QuaternionMathFunctions/QuaternionMathFunctions.c\”\n\
)\n\
\n\
# Part 3: Add our module’s C file AND the curated CMSIS-DSP SOURCE FILES to MicroPython’s build list.\n\
List(APPEND MICROPY_SOURCE_PORT \n\
    \${MICROPY_DIR}/extmod/sdr_radio/sdr_radio.c\n\
    \${CMSIS_DSP_SOURCES}\n\
)\n\
List(APPEND MICROPY_SOURCE_QSTR \${MICROPY_DIR}/extmod/sdr_radio/sdr_radio.c)\n\
\n\
# --- End of customizations ---\n”
Awk -v block=”$CUSTOM_BLOCK_SOURCES” -v target=”$TARGET_LINE_SOURCES” ‘index($0, target) {print block} 1’ CMakeLists.txt > CMakeLists.txt.new && mv CMakeLists.txt.new CMakeLists.txt

### sed -i ‘/Execute _boot.py to set up the filesystem/a \        mp_printf(MP_PYTHON_PRINTER, “Kilroy with Micropython threads and ADC fix\\n”);’ main.c 

# --- STEP 5: BUILD THE FIRMWARE ---
Echo “--- [5/5] Starting the final MicroPython build ---”
Make -j4 BOARD=${BOARD}

Echo “”
Echo “--- BUILD SUCCESSFUL! ---”
Echo “Firmware is at: ${PROJECT_ROOT}/micropython/ports/rp2/build-${BOARD}/firmware.uf2”
Ls -l build-${BOARD}/firmware.uf2
Cp build-${BOARD}/firmware.uf2 /mnt/c/simon/sdr_radio_pico

Echo “--- VERIFYING MODULE PRESENCE IN SYMBOL TABLE ---”
# Check the final ELF for the module symbol. This will now pass.
If arm-none-eabi-nm “build-${BOARD}/firmware.elf” | grep -q “sdr_radio_user_cmodule”; then
    Echo “SUCCESS: sdr_radio module symbol found in the firmware.”
Else
    Echo “ERROR: sdr_radio module symbol was NOT found in the firmware.”
    Exit 1
Fi

Echo “”
Echo “--- ALL STEPS COMPLETE. The module will now be visible in the REPL. ---”
Whew!

Now we have a file called firmware.uf2. We hold down the little button on the RP2350, cycle power, and it’s in boot mode, and shows up in Windows as a new disk drive. We copy firmware.uf2 into that new directory, and the microcomputer boots the new firmware.

Of course, before building it, we need our new module:

#include “py/runtime.h”
#include “py/mphal.h”
#include <math.h>
#include <string.h>
#include “hardware/dma.h”
#include “hardware/adc.h”
#include “hardware/irq.h”
#include “hardware/sync.h”
#include “hardware/resets.h”
#include <float.h>
#include “hardware/clocks.h”
#include “hardware/pwm.h”
#include “arm_math.h”
#include “pico/multicore.h”

#define ADC_SAMPLE_RATE 500000
#define AUDIO_SAMPLE_RATE 22050

#define mult_q31(a, b) ((q31_t)(((int64_t)(a) * (b)) >> 31))

Typedef struct _sdr_radio_obj_t {
    Mp_obj_base_t base;
    Uint32_t tune_freq_hz;

    Q31_t nco_phase;             // Current phase accumulator
    Q31_t nco_phase_increment;   // Phase step per sample

    // --- State for the Iterative NCO (Mixer) ---
    Q31_t nco_i;            // Current I value (cos) of the NCO, Q31 format
    Q31_t nco_q;            // Current Q value (sin) of the NCO, Q31 format
    Q31_t nco_cos_inc;      // Pre-calculated cos(phase_increment)
    Q31_t nco_sin_inc;      // Pre-calculated sin(phase_increment)

    // --- State for the fixed-point RF DC Blocker ---
    Q31_t dc_block_i_x1;
    Q31_t dc_block_i_y1;
    Q31_t dc_block_q_x1;
    Q31_t dc_block_q_y1;

    // --- State for the LPF (Cascaded EMA) ---
    Q31_t ema_i_s1, ema_i_s2, ema_i_s3;
    Q31_t ema_q_s1, ema_q_s2, ema_q_s3;;
    
 Q31_t demod_mag_x1;

    // --- State for the Audio HPF (DC Blocker) ---
    Q31_t audio_hpf_x1;
 Q31_t audio_hpf_y1;

 Q31_t agc_smoothed_peak;

 Q31_t audio_ema_lpf;

 Bool is_am_mode;

    Q31_t bfo_phase;
    Q31_t bfo_phase_increment;

 ///////////////////////////////////////////////////////////////
 ////////////// Transmitter Section ////////////////////////////
 ///////////////////////////////////////////////////////////////
    Uint32_t tx_carrier_freq_hz;
    Q31_t tx_nco_phase;
    Q31_t tx_nco_phase_increment;
    Float32_t tx_modulation_index;

    Uint32_t capture_sample_rate;
    Uint32_t capture_num_samples;
    Uint32_t adc_clkdiv;

} sdr_radio_obj_t;


// The internal C buffers that the DMA will write to.
// The size MUST match the buffer size used in the Python script.
#define MAX_CAPTURE_BUFFER_SIZE 8192

Static int adc_dma_chan_A = -1;
Static int adc_dma_chan_B = -1;

// Internal ping-pong buffers for the DMA
Static uint32_t capture_buf_A[MAX_CAPTURE_BUFFER_SIZE];
Static uint32_t capture_buf_B[MAX_CAPTURE_BUFFER_SIZE];



// Helper function to guarantee a clean state
Static void reset_sdr_state(sdr_radio_obj_t *self) {
    Self->nco_phase = 0;
    Self->dc_block_i_x1 = 0;
    Self->dc_block_i_y1 = 0;
    Self->dc_block_q_x1 = 0;
    Self->dc_block_q_y1 = 0;

 Self->ema_i_s1=0; self->ema_i_s2=0; self->ema_i_s3=0;
 Self->ema_q_s1=0; self->ema_q_s2=0; self->ema_q_s3=0;

    Self->agc_smoothed_peak = 1000;

    // Initialize the Audio HPF state
    Self->demod_mag_x1 = 0;
    Self->audio_hpf_y1 = 0;

 Self->bfo_phase = 0;

 Self->audio_ema_lpf = 0;
}

// Exposed to Python to make tests deterministic
Static mp_obj_t sdr_radio_reset_state(mp_obj_t self_in) {
    Sdr_radio_obj_t *self = MP_OBJ_TO_PTR(self_in);
    Reset_sdr_state(self);
    Return mp_const_none;
}
Static MP_DEFINE_CONST_FUN_OBJ_1(sdr_radio_reset_state_obj, sdr_radio_reset_state);


Static mp_obj_t sdr_radio_set_mode(mp_obj_t self_in, mp_obj_t is_am_obj) {
    Sdr_radio_obj_t *self = MP_OBJ_TO_PTR(self_in);
 Self->is_am_mode = mp_obj_is_true(is_am_obj);
 
    Return mp_const_none;
}
Static MP_DEFINE_CONST_FUN_OBJ_2(sdr_radio_set_mode_obj, sdr_radio_set_mode);



Static mp_obj_t sdr_radio_make_new(const mp_obj_type_t *type, size_t n_args, size_t n_kw, const mp_obj_t *args) {

    Sdr_radio_obj_t *self = mp_obj_malloc(sdr_radio_obj_t, type);

    Reset_sdr_state(self);
 Self->bfo_phase = 0;
    Self->nco_phase_increment = (uint32_t)( ( (uint64_t)self->tune_freq_hz << 32 ) / ADC_SAMPLE_RATE );
    Self->capture_sample_rate = 0;
    Self->capture_num_samples = 0;

    Return MP_OBJ_FROM_PTR(self);
}


Static mp_obj_t sdr_radio_tune(mp_obj_t self_in, mp_obj_t freq_obj) {
    Sdr_radio_obj_t *self = MP_OBJ_TO_PTR(self_in);
    
    // 1. Get the desired station frequency (e.g., 810000) from Python.
    Uint32_t station_freq_hz = mp_obj_get_int(freq_obj);

    // --- Alias Calculation ---
    // This logic calculates the NCO frequency needed to tune to a station
    // by using undersampling (aliasing) to bring it into the first Nyquist zone.
    
    // Find the remainder when the station frequency is divided by the sample rate.
    Uint32_t remainder = station_freq_hz % ADC_SAMPLE_RATE;

    Uint32_t nco_tune_freq_hz;
    
    // Check which half of the Nyquist zone the remainder falls into.
    If (remainder < (ADC_SAMPLE_RATE / 2)) {
        // If it’s in the lower half, the alias appears directly.
        // e.g., for a 190kHz station, remainder is 190k. We tune to 190k.
        Nco_tune_freq_hz = remainder;
    } else {
        // If it’s in the upper half, the alias is mirrored from the top.
        // e.g., for an 810kHz station, remainder is 310k. We tune to 500k-310k = 190k.
        Nco_tune_freq_hz = ADC_SAMPLE_RATE – remainder;
    }

    // Store the calculated NCO frequency in our object.
    Self->tune_freq_hz = nco_tune_freq_hz;
    
    // Recalculate the NCO phase increment with the new frequency.
    Self->nco_phase_increment = (q31_t)(((uint64_t)self->tune_freq_hz << 31) / ADC_SAMPLE_RATE);

    Return mp_const_none;
}


Static MP_DEFINE_CONST_FUN_OBJ_2(sdr_radio_tune_obj, sdr_radio_tune);




Static mp_obj_t fast_sdr_pipeline(mp_obj_t self_in, mp_obj_t args_in) {

    Sdr_radio_obj_t *self = MP_OBJ_TO_PTR(self_in);

    Size_t n_args;
    Mp_obj_t *args;
    Mp_obj_get_array(args_in, &n_args, &args);

    If (n_args < 3) {
        Mp_raise_TypeError(MP_ERROR_TEXT(“Requires at least adc, out, and scratch buffers”));
    }
    Mp_buffer_info_t adc_info;     mp_get_buffer_raise(args[0], &adc_info,     MP_BUFFER_READ);
    Mp_buffer_info_t out_info;     mp_get_buffer_raise(args[1], &out_info,     MP_BUFFER_WRITE);
    Mp_buffer_info_t scratch_info; mp_get_buffer_raise(args[2], &scratch_info, MP_BUFFER_WRITE);

    // --- Buffer Pointers and Sizes ---
    Uint16_t *adc_in_ptr = (uint16_t *)adc_info.buf;
    Uint32_t *pwm_out_ptr = (uint32_t *)out_info.buf;
    Const int num_adc_samples = adc_info.len / sizeof(uint16_t);
    Const int num_audio_samples = out_info.len / sizeof(uint32_t);

    // --- DSP Constants ---
    Const q31_t DC_BLOCK_R = 0x7F800000;
    Const q31_t RF_LPF_ALPHA = 0x20000000; // Alpha=0.25, wide ~20kHz RF LPF
    Const q31_t RF_LPF_ONE_MINUS_ALPHA = 0x7FFFFFFF – RF_LPF_ALPHA;
    Const int DECIMATION_FACTOR = ADC_SAMPLE_RATE / 22050;
    Const q31_t AUDIO_HPF_R = 0x7E000000; // ~112 Hz HPF cutoff

    Q31_t *temp_audio_buf = (q31_t*)scratch_info.buf;
    Int audio_idx = 0;

 Int decimation_counter = 0;
 Q31_t i_filtered = 0;
 Q31_t q_filtered = 0;

    If (self->is_am_mode) {
        // ====================================================================
        //  FAST PATH for AM MODE (No RF DC Blocker)
        // ====================================================================
        For (int i = 0; i < num_adc_samples; i++) {
            Q31_t sample = ((q31_t)adc_in_ptr[i] – 2048) << 19;

            Q31_t nco_s = arm_sin_q31(self->nco_phase);
            Q31_t nco_c = arm_cos_q31(self->nco_phase);

            Self->nco_phase += self->nco_phase_increment;
            Q31_t i_raw = mult_q31(sample, nco_c);
            Q31_t q_raw = mult_q31(sample, nco_s); // Use positive sine for Q

            // 3-Stage Cascaded EMA Low-Pass Filter
            Q31_t i_s1_out = mult_q31(self->ema_i_s1, RF_LPF_ONE_MINUS_ALPHA) + mult_q31(i_raw, RF_LPF_ALPHA);
            Self->ema_i_s1 = i_s1_out;
            Q31_t i_s2_out = mult_q31(self->ema_i_s2, RF_LPF_ONE_MINUS_ALPHA) + mult_q31(i_s1_out, RF_LPF_ALPHA);
            Self->ema_i_s2 = i_s2_out;
            // q31_t i_filtered = mult_q31(self->ema_i_s3, RF_LPF_ONE_MINUS_ALPHA) + mult_q31(i_s2_out, RF_LPF_ALPHA);
            I_filtered = mult_q31(self->ema_i_s3, RF_LPF_ONE_MINUS_ALPHA) + mult_q31(i_s2_out, RF_LPF_ALPHA);
            Self->ema_i_s3 = i_filtered;

            Q31_t q_s1_out = mult_q31(self->ema_q_s1, RF_LPF_ONE_MINUS_ALPHA) + mult_q31(q_raw, RF_LPF_ALPHA);
            Self->ema_q_s1 = q_s1_out;
            Q31_t q_s2_out = mult_q31(self->ema_q_s2, RF_LPF_ONE_MINUS_ALPHA) + mult_q31(q_s1_out, RF_LPF_ALPHA);
            Self->ema_q_s2 = q_s2_out;
            // q31_t q_filtered = mult_q31(self->ema_q_s3, RF_LPF_ONE_MINUS_ALPHA) + mult_q31(q_s2_out, RF_LPF_ALPHA);
            Q_filtered = mult_q31(self->ema_q_s3, RF_LPF_ONE_MINUS_ALPHA) + mult_q31(q_s2_out, RF_LPF_ALPHA);
            Self->ema_q_s3 = q_filtered;
            
            // Decimation and Audio Path
   If (++decimation_counter >= DECIMATION_FACTOR) {
                Decimation_counter = 0;
                If (audio_idx < num_audio_samples) {
     // --- AM Demodulation (Fast Approximation) ---
                    Q31_t abs_i = (i_filtered > 0) ? i_filtered : -i_filtered;
                    Q31_t abs_q = (q_filtered > 0) ? q_filtered : -q_filtered;
     Q31_t max_val, min_val;
     If (abs_i > abs_q) {
      Max_val = abs_i;
      Min_val = abs_q;
     } else {
      Max_val = abs_q;
      Min_val = abs_i;
     }

     // Magnitude ≈ max + 0.25*min
     Q31_t magnitude = __QADD(max_val, min_val >> 2);
     Q31_t demodulated_signal = magnitude;
     
     // Audio HPF
     Q31_t diff = __QSUB(demodulated_signal, self->audio_hpf_x1);
     Q31_t sum = __QADD(self->audio_hpf_y1, diff);
     Q31_t audio_sample = mult_q31(AUDIO_HPF_R, sum);
     Self->audio_hpf_x1 = magnitude;
     Self->audio_hpf_y1 = audio_sample;
     
     Temp_audio_buf[audio_idx++] = audio_sample;
    }
            }
        }
    } else {
        // ====================================================================
        //  FAST PATH for CW/SSB MODE (with BFO)
        // ====================================================================
        For (int i = 0; i < num_adc_samples; i++) {
            // Step 1: ADC Scaling
            Q31_t sample = ((q31_t)adc_in_ptr[i] – 2048) << 19;

            // Step 2: NCO & Mixer
            Q31_t nco_s = arm_sin_q31(self->nco_phase);
            Q31_t nco_c = arm_cos_q31(self->nco_phase);

            Self->nco_phase += self->nco_phase_increment;
            Q3
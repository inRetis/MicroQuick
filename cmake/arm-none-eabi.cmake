# Toolchain file for Cortex-M targets (GNU Arm Embedded toolchain).
#   cmake -S . -B build-arm -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi.cmake \
#         -DMQ_ASSETS_EXECUTABLE=$PWD/build/tools/mqassets/mqassets
# Adjust MQ_CPU_FLAGS for your MCU (default: Cortex-M7 with double precision FPU).
set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR arm)
set(CMAKE_C_COMPILER arm-none-eabi-gcc)
set(CMAKE_CXX_COMPILER arm-none-eabi-g++)
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

set(MQ_CPU_FLAGS "-mcpu=cortex-m7 -mthumb -mfpu=fpv5-d16 -mfloat-abi=hard" CACHE STRING "CPU flags")
set(CMAKE_C_FLAGS_INIT "${MQ_CPU_FLAGS} -ffunction-sections -fdata-sections")
set(CMAKE_CXX_FLAGS_INIT "${MQ_CPU_FLAGS} -ffunction-sections -fdata-sections -fno-threadsafe-statics -fno-use-cxa-atexit")
set(CMAKE_EXE_LINKER_FLAGS_INIT "-Wl,--gc-sections --specs=nano.specs")

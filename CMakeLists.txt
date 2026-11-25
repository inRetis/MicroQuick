cmake_minimum_required(VERSION 3.21)
project(MicroQuick VERSION 0.1 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Host build (simulator, tools, tests) vs. MCU cross build (runtime + app only).
if(CMAKE_CROSSCOMPILING)
    set(MQ_HOST_BUILD OFF)
else()
    set(MQ_HOST_BUILD ON)
endif()
option(MQ_BUILD_SIMULATOR "Build the Qt based desktop simulator" ${MQ_HOST_BUILD})
option(MQ_BUILD_TESTS "Build the tests" ${MQ_HOST_BUILD})
option(MQ_BUILD_EXAMPLES "Build the examples" ON)

find_package(Python3 REQUIRED COMPONENTS Interpreter)

add_subdirectory(runtime)
include(cmake/MicroQuick.cmake)

if(MQ_HOST_BUILD)
    # Qt 6 is only needed on the host: asset compiler + simulator.
    find_package(Qt6 REQUIRED COMPONENTS Core Gui)
    add_subdirectory(tools/mqassets)
    if(MQ_BUILD_SIMULATOR)
        add_subdirectory(platform/simulator)
    endif()
endif()

if(MQ_BUILD_EXAMPLES)
    add_subdirectory(examples/demo)
    add_subdirectory(examples/core2)
endif()

if(MQ_BUILD_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif()

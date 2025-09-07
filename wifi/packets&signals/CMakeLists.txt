cmake_minimum_required(VERSION 3.16)
project(soapywifi_capture LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

find_package(SoapySDR REQUIRED)

add_executable(wifi_capture src/wifi_capture.cpp)
target_link_libraries(wifi_capture PRIVATE SoapySDR)

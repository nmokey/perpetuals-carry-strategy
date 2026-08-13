cmake_minimum_required(VERSION 3.20)
project(perpcarry LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE RelWithDebInfo CACHE STRING "Build type" FORCE)
endif()

# Tests are built for standalone C++ development, but skipped when scikit-build-core
# is driving the build to produce a wheel.
option(PERPCARRY_BUILD_TESTS "Build the C++ unit tests" ON)
option(PERPCARRY_BUILD_PYTHON "Build the pybind11 extension module" ON)
if(SKBUILD)
  set(PERPCARRY_BUILD_TESTS OFF)
endif()

if(PERPCARRY_BUILD_TESTS)
  enable_testing()
endif()

add_subdirectory(cpp)

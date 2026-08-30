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
# Local developer tools (the M2-T2 replay validator). Like the tests, these are for
# standalone C++ work and have no place in a wheel.
option(PERPCARRY_BUILD_TOOLS "Build the local developer tools" ON)
if(SKBUILD)
  set(PERPCARRY_BUILD_TESTS OFF)
  set(PERPCARRY_BUILD_TOOLS OFF)
endif()

# Sanitizer builds (M3-T2). ThreadSanitizer is the one the SPSC queue's acceptance
# criterion names, and until this existed that criterion could not be executed at all --
# blockers.md carried it as an unassigned gap. A criterion that cannot be run is not a
# criterion, which is the same reasoning that forced D-019.
#
# Applied globally rather than per-target: TSan must instrument everything in the process,
# including the parts a race is observed *from*, or it reports nothing and looks clean.
set(PERPCARRY_SANITIZER "" CACHE STRING
    "Sanitizer to build with: thread, address, undefined, or empty for none")
if(PERPCARRY_SANITIZER)
  message(STATUS "perpcarry: building with -fsanitize=${PERPCARRY_SANITIZER}")
  add_compile_options(-fsanitize=${PERPCARRY_SANITIZER} -fno-omit-frame-pointer -g)
  add_link_options(-fsanitize=${PERPCARRY_SANITIZER})
endif()

if(PERPCARRY_BUILD_TESTS)
  enable_testing()
endif()

add_subdirectory(cpp)

# Deterministic, single-threaded core. Everything correctness-critical lives here
# (order book reconstruction, impact simulation) so it stays unit-testable.
add_library(perpcarry_core STATIC
  src/version.cpp
)
target_include_directories(perpcarry_core PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
)
target_compile_features(perpcarry_core PUBLIC cxx_std_20)
set_target_properties(perpcarry_core PROPERTIES POSITION_INDEPENDENT_CODE ON)

if(PERPCARRY_BUILD_PYTHON)
  if(SKBUILD)
    find_package(Python 3.11 REQUIRED COMPONENTS Interpreter Development.Module)
    find_package(pybind11 CONFIG REQUIRED)
  else()
    # Standalone builds: locate pybind11 inside whatever interpreter is active
    # (the uv-managed .venv), since it is only a dev dependency there.
    find_package(Python 3.11 QUIET COMPONENTS Interpreter Development.Module)
    if(Python_FOUND AND NOT pybind11_DIR)
      execute_process(
        COMMAND "${Python_EXECUTABLE}" -m pybind11 --cmakedir
        OUTPUT_VARIABLE _pybind11_cmakedir
        OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_QUIET
      )
      if(_pybind11_cmakedir)
        set(pybind11_DIR "${_pybind11_cmakedir}")
      endif()
    endif()
    find_package(pybind11 CONFIG QUIET)
  endif()

  if(pybind11_FOUND)
    pybind11_add_module(perpcarry_cpp bindings/pybind_module.cpp)
    target_link_libraries(perpcarry_cpp PRIVATE perpcarry_core)
    install(TARGETS perpcarry_cpp LIBRARY DESTINATION .)
  else()
    message(STATUS "pybind11 not found; skipping the perpcarry_cpp extension module")
  endif()
endif()

if(PERPCARRY_BUILD_TESTS)
  add_subdirectory(tests)
endif()

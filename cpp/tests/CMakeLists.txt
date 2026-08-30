include(FetchContent)

FetchContent_Declare(
  Catch2
  GIT_REPOSITORY https://github.com/catchorg/Catch2.git
  GIT_TAG v3.7.1
  GIT_SHALLOW TRUE
  SYSTEM
)
FetchContent_MakeAvailable(Catch2)

add_executable(perpcarry_tests
  test_book_dump.cpp
  test_book_replayer.cpp
  test_spsc_queue.cpp
  test_order_book.cpp
  test_version.cpp
)
target_link_libraries(perpcarry_tests PRIVATE perpcarry_core Catch2::Catch2WithMain)

# The harness lives in cpp/tools/, and its tests are the only thing that exercises the
# M2-T2 validation mechanism -- the real vendor data never can, since the licence keeps it
# out of CI (D-018).
#
# Skipping them when the tools are off would drop seven cases while ctest still printed
# "100% tests passed": verified 2026-08-29, 29 passing where 36 were expected, with no
# outward difference. A check that passes by not running is the failure mode C15 exists
# for, so this combination is a hard error rather than a quiet subset.
#
# A wheel build reaches neither branch: SKBUILD forces tests and tools off together.
if(NOT TARGET perpcarry_replay_validate)
  message(FATAL_ERROR
    "PERPCARRY_BUILD_TESTS=ON requires PERPCARRY_BUILD_TOOLS=ON: the replay-validator "
    "tests link against cpp/tools/. Turning the tools off would silently shrink the suite.")
endif()
target_sources(perpcarry_tests PRIVATE test_replay_validate.cpp)
target_link_libraries(perpcarry_tests PRIVATE perpcarry_replay_validate)

# perpcarry_core is linked directly (test_order_book.cpp and friends use it) and arrives
# again transitively through perpcarry_replay_validate, which PUBLIC-links it because its
# own header exposes core types. Declaring direct dependencies directly is right, so the
# duplicate is CMake flattening a correct graph rather than a mistake to restructure.
#
# Apple's linker warns about it anyway. Silence that one warning rather than dropping the
# explicit dependency: relying on the transitive path would make the tests' link depend on
# the tools being enabled, which is true today only because of the hard error above.
if(APPLE)
  include(CheckLinkerFlag)
  check_linker_flag(CXX "-Wl,-no_warn_duplicate_libraries" PERPCARRY_HAS_NO_WARN_DUPLICATE_LIBS)
  if(PERPCARRY_HAS_NO_WARN_DUPLICATE_LIBS)
    target_link_options(perpcarry_tests PRIVATE "-Wl,-no_warn_duplicate_libraries")
  endif()
endif()

list(APPEND CMAKE_MODULE_PATH ${catch2_SOURCE_DIR}/extras)
include(Catch)
catch_discover_tests(perpcarry_tests)

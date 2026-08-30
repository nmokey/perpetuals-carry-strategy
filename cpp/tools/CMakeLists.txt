# The validation harness (D-018). Deliberately outside perpcarry_core: it does file I/O,
# and the core does none (D-012). Built as a library plus a thin main so the harness itself
# is testable in CI against synthetic input -- the real vendor data never can be.
add_library(perpcarry_replay_validate STATIC
  replay_validate.cpp
)
target_include_directories(perpcarry_replay_validate PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
)
target_link_libraries(perpcarry_replay_validate PUBLIC perpcarry_core)

add_executable(perpcarry_replay_validate_cli
  replay_validate_main.cpp
)
set_target_properties(perpcarry_replay_validate_cli PROPERTIES OUTPUT_NAME perpcarry_replay_validate)
target_link_libraries(perpcarry_replay_validate_cli PRIVATE perpcarry_replay_validate)

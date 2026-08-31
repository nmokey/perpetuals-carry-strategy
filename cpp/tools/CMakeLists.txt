# The validation harness (D-018). Deliberately outside perpcarry_core: it does file I/O,
# and the core does none (D-012). Built as a library plus a thin main so the harness itself
# is testable in CI against synthetic input -- the real vendor data never can be.
add_library(perpcarry_replay_validate STATIC
  event_csv.cpp
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

# M3-T2's throughput measurement. A wall-clock number has no place in the pass/fail unit
# suite -- it would be flaky on a loaded machine and uninformative when it failed -- so it
# is a tool that writes its result, and docs/validation/ holds the recorded run.
add_executable(perpcarry_queue_bench queue_bench.cpp)
target_link_libraries(perpcarry_queue_bench PRIVATE perpcarry_core)
target_compile_definitions(perpcarry_queue_bench
  PRIVATE PERPCARRY_BUILD_TYPE="${CMAKE_BUILD_TYPE}")

# M4's real-data harness. Like the replay validator, it reads licensed vendor book data and emits
# only aggregates -- rates and means over a day, which expose no rows.
add_executable(perpcarry_impact_probe impact_probe.cpp)
target_link_libraries(perpcarry_impact_probe PRIVATE perpcarry_replay_validate)

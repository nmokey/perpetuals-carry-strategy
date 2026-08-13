#include <catch2/catch_test_macros.hpp>

#include "perpcarry/version.hpp"

TEST_CASE("core reports a version", "[smoke]") {
  REQUIRE_FALSE(perpcarry::version().empty());
}

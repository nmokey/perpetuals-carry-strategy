#pragma once

#include <string_view>

namespace perpcarry {

// Version of the C++ core, kept in sync with the project version in pyproject.toml.
std::string_view version() noexcept;

}  // namespace perpcarry

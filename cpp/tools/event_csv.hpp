// Shared CSV reading for the local dev tools: the events export produced by
// perpcarry.tools.export_book (D-018).
//
// Extracted from replay_validate.cpp when a second tool needed it (M4's impact probe). A
// second copy of the exporter's column contract would be a second source of truth that can
// only ever agree by luck, and it would fail in the direction that looks like success --
// a file parsed into the wrong fields is still a plausible book (C15).
//
// Lives in cpp/tools/, not perpcarry_core: the core does no file I/O (D-012).
#ifndef PERPCARRY_TOOLS_EVENT_CSV_HPP
#define PERPCARRY_TOOLS_EVENT_CSV_HPP

#include <cstdint>
#include <iosfwd>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

#include "perpcarry/book_replayer.hpp"

namespace perpcarry::tools {

class ValidationError : public std::runtime_error {
 public:
  explicit ValidationError(const std::string& what) : std::runtime_error(what) {}
};

extern const std::vector<std::string> kEventColumns;
extern const std::vector<std::string> kReferenceColumns;

std::string_view unquote(std::string_view field);
void split(std::string_view line, std::vector<std::string_view>& out);
std::int64_t parse_int(std::string_view field, const char* what);
double parse_double(std::string_view field, const char* what);
Side parse_side(std::string_view field);
bool parse_bool(std::string_view field);

// Header-checked line reader. The header is verified rather than skipped: a column reordered
// upstream would otherwise be read as a different field and produce a wrong book with no error
// anywhere (C14).
class CsvReader {
 public:
  CsvReader(std::istream& in, const std::vector<std::string>& expected, const char* what);

  // Fields remain valid until the next call.
  const std::vector<std::string_view>* next();

 private:
  std::istream& in_;
  std::string line_;
  std::vector<std::string_view> fields_;
};

// One-row lookahead over the event stream, so a group of events sharing a millisecond can be
// counted only once its end is known.
class EventStream {
 public:
  explicit EventStream(std::istream& in);

  bool has() const { return has_; }
  const BookUpdate& peek() const { return pending_; }
  void advance();

 private:
  CsvReader csv_;
  BookUpdate pending_;
  bool has_ = false;
};

}  // namespace perpcarry::tools

#endif  // PERPCARRY_TOOLS_EVENT_CSV_HPP

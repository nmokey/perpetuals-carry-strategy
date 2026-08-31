#include "event_csv.hpp"

#include <charconv>
#include <istream>

namespace perpcarry::tools {

// Must match perpcarry.tools.export_book.EVENT_COLUMNS / REFERENCE_COLUMNS.
const std::vector<std::string> kEventColumns = {"timestamp", "local_timestamp", "is_snapshot",
                                                "side",      "price",           "quantity"};
const std::vector<std::string> kReferenceColumns = {"timestamp", "side", "level", "price",
                                                    "quantity"};

std::string_view unquote(std::string_view field) {
  if (field.size() >= 2 && field.front() == '"' && field.back() == '"') {
    return field.substr(1, field.size() - 2);
  }
  return field;
}

void split(std::string_view line, std::vector<std::string_view>& out) {
  out.clear();
  std::size_t start = 0;
  while (true) {
    const std::size_t comma = line.find(',', start);
    if (comma == std::string_view::npos) {
      out.push_back(unquote(line.substr(start)));
      return;
    }
    out.push_back(unquote(line.substr(start, comma - start)));
    start = comma + 1;
  }
}

std::int64_t parse_int(std::string_view field, const char* what) {
  std::int64_t value = 0;
  const auto result = std::from_chars(field.data(), field.data() + field.size(), value);
  if (result.ec != std::errc() || result.ptr != field.data() + field.size()) {
    throw ValidationError(std::string("could not parse ") + what + " as an integer: '" +
                          std::string(field) + "'");
  }
  return value;
}

double parse_double(std::string_view field, const char* what) {
  // std::from_chars, not strtod: it is locale-independent by construction, and a decimal
  // separator that follows the environment is exactly the kind of thing that silently
  // truncates every price on someone else's machine.
  double value = 0.0;
  const auto result = std::from_chars(field.data(), field.data() + field.size(), value);
  if (result.ec != std::errc() || result.ptr != field.data() + field.size()) {
    throw ValidationError(std::string("could not parse ") + what + " as a number: '" +
                          std::string(field) + "'");
  }
  return value;
}

Side parse_side(std::string_view field) {
  if (field == "bid") return Side::Bid;
  if (field == "ask") return Side::Ask;
  throw ValidationError("unknown side '" + std::string(field) + "', expected bid or ask");
}

bool parse_bool(std::string_view field) {
  if (field == "true" || field == "1") return true;
  if (field == "false" || field == "0") return false;
  throw ValidationError("unknown boolean '" + std::string(field) + "'");
}

CsvReader::CsvReader(std::istream& in, const std::vector<std::string>& expected, const char* what)
    : in_(in) {
  if (!std::getline(in_, line_)) {
    throw ValidationError(std::string(what) + " csv is empty: expected a header row");
  }
  if (!line_.empty() && line_.back() == '\r') line_.pop_back();
  split(line_, fields_);
  if (fields_.size() != expected.size()) {
    throw ValidationError(std::string(what) + " csv has " + std::to_string(fields_.size()) +
                          " columns, expected " + std::to_string(expected.size()));
  }
  for (std::size_t i = 0; i < expected.size(); ++i) {
    if (fields_[i] != expected[i]) {
      throw ValidationError(std::string(what) + " csv column " + std::to_string(i) + " is '" +
                            std::string(fields_[i]) + "', expected '" + expected[i] + "'");
    }
  }
}

const std::vector<std::string_view>* CsvReader::next() {
  if (!std::getline(in_, line_)) return nullptr;
  if (!line_.empty() && line_.back() == '\r') line_.pop_back();
  if (line_.empty()) return next();
  split(line_, fields_);
  return &fields_;
}

EventStream::EventStream(std::istream& in) : csv_(in, kEventColumns, "events") { advance(); }

void EventStream::advance() {
  const std::vector<std::string_view>* fields = csv_.next();
  if (fields == nullptr) {
    has_ = false;
    return;
  }
  pending_.timestamp = parse_int((*fields)[0], "event timestamp");
  pending_.local_timestamp = parse_int((*fields)[1], "event local_timestamp");
  pending_.is_snapshot = parse_bool((*fields)[2]);
  pending_.side = parse_side((*fields)[3]);
  pending_.price = parse_double((*fields)[4], "event price");
  pending_.quantity = parse_double((*fields)[5], "event quantity");
  has_ = true;
}

}  // namespace perpcarry::tools

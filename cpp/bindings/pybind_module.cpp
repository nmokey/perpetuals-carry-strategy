// Python bindings for the C++ core. See docs/specs/M3/M3-T1-pybind11-bindings.md.
//
// The C++/Python boundary deliberately sits at the pipeline level (post-SPSC-queue),
// never per-tick -- see design-doc Risk R4. Concretely: BookReplayer, which *is* the
// replay pipeline, exposes only apply_batch(). It has no single-row entry point on this
// side and must not grow one; that is the R4 mistake in its most tempting form.
//
// OrderBook::apply is exposed, and the distinction is deliberate rather than an
// inconsistency: OrderBook is a data structure a caller may want to build by hand to test
// or to reason about, while BookReplayer is the thing a feed flows through. Replaying a
// feed by looping OrderBook.apply from Python would be per-tick interop, and nothing here
// makes that convenient.
//
// What deliberately does NOT cross:
//   - format_ladder, format_diff, format_price. Human-readable renderings are for the C++
//     harness's failure output; nothing on the Python side reads them.
//   - compare_top_n / BookDiff. Comparison against vendor images is the harness's job
//     (D-018), on the other side of a licence boundary Python code is not invited across.
//
// dump_csv DOES cross, reversing M2-T3's "and probably never". That call reasoned that
// Python can read the corpus directly, which is true and beside the point: M3-T3's
// checkpoint is a digest of the *replayed* book, a thing only C++ holds. Re-deriving the
// canonical rendering in Python would be a second source of truth that agrees by luck --
// Python's repr() and std::to_chars happen to produce the same text today, which is
// exactly the kind of coincidence C15 warns is invisible until it breaks.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <optional>
#include <span>
#include <string>
#include <vector>

#include <sstream>

#include "perpcarry/book_debug.hpp"
#include "perpcarry/book_replayer.hpp"
#include "perpcarry/order_book.hpp"
#include "perpcarry/pipeline.hpp"
#include "perpcarry/version.hpp"

namespace py = pybind11;

using perpcarry::BookReplayer;
using perpcarry::BookReplayError;
using perpcarry::BookUpdate;
using perpcarry::Level;
using perpcarry::OrderBook;
using perpcarry::Pipeline;
using perpcarry::PipelineResult;
using perpcarry::Side;

namespace {

// Levels cross as plain (price, quantity) tuples, and they are *copied* out.
//
// This is the task's one real hazard. OrderBook::levels() returns a std::span whose header
// states it is invalidated by the next apply() or clear(); that is correct and deliberate
// on the C++ side, since it lets M4 walk the book with no copy and no allocation. Handed to
// Python as a view, the same span becomes an object that stays alive, keeps returning
// numbers, and returns garbage after the next update -- surfacing as a plausible fill price
// rather than as a crash, which is the worst available failure mode for this project.
//
// Building a new list here makes that structurally impossible. The zero-copy path remains
// available to C++ callers, who are the ones that need it.
py::list levels_to_list(std::span<const Level> levels) {
  py::list out(levels.size());
  for (std::size_t i = 0; i < levels.size(); ++i) {
    out[i] = py::make_tuple(levels[i].price, levels[i].quantity);
  }
  return out;
}

py::object level_to_object(const std::optional<Level>& level) {
  if (!level.has_value()) return py::none();
  return py::make_tuple(level->price, level->quantity);
}

}  // namespace

PYBIND11_MODULE(perpcarry_cpp, m) {
  m.doc() = "C++ core for PerpCarry: order book reconstruction and impact simulation";
  m.attr("__version__") = std::string(perpcarry::version());
  m.def("version", []() { return std::string(perpcarry::version()); },
        "Version string of the compiled C++ core.");

  // Catchable on the Python side rather than arriving as a bare RuntimeError: a replay that
  // rejects its input is a different situation from a bug, and M3-T3 needs to tell them
  // apart. Invalid prices and quantities keep std::invalid_argument's default translation
  // to ValueError.
  py::register_exception<BookReplayError>(m, "BookReplayError");

  py::enum_<Side>(m, "Side")
      .value("Bid", Side::Bid)
      .value("Ask", Side::Ask);

  py::class_<BookUpdate>(m, "BookUpdate")
      .def(py::init([](std::int64_t timestamp, std::int64_t local_timestamp, bool is_snapshot,
                       Side side, double price, double quantity) {
             return BookUpdate{timestamp, local_timestamp, is_snapshot, side, price, quantity};
           }),
           py::arg("timestamp"), py::arg("local_timestamp") = 0,
           py::arg("is_snapshot") = false, py::arg("side") = Side::Bid, py::arg("price") = 0.0,
           py::arg("quantity") = 0.0)
      .def_readonly("timestamp", &BookUpdate::timestamp)
      .def_readonly("local_timestamp", &BookUpdate::local_timestamp)
      .def_readonly("is_snapshot", &BookUpdate::is_snapshot)
      .def_readonly("side", &BookUpdate::side)
      .def_readonly("price", &BookUpdate::price)
      .def_readonly("quantity", &BookUpdate::quantity);

  py::class_<BookReplayer::Stats>(m, "ReplayStats")
      .def_readonly("applied", &BookReplayer::Stats::applied)
      .def_readonly("resyncs", &BookReplayer::Stats::resyncs)
      .def_readonly("snapshot_rows", &BookReplayer::Stats::snapshot_rows)
      .def_readonly("removals", &BookReplayer::Stats::removals)
      .def_readonly("crossed", &BookReplayer::Stats::crossed)
      .def_readonly("last_timestamp", &BookReplayer::Stats::last_timestamp);

  py::class_<OrderBook>(m, "OrderBook")
      .def(py::init<>())
      .def("apply", &OrderBook::apply, py::arg("side"), py::arg("price"), py::arg("quantity"),
           "Apply one update. quantity == 0 removes the level.")
      .def("clear", &OrderBook::clear)
      .def("best", [](const OrderBook& b, Side s) { return level_to_object(b.best(s)); },
           py::arg("side"))
      .def("best_bid", [](const OrderBook& b) { return level_to_object(b.best_bid()); })
      .def("best_ask", [](const OrderBook& b) { return level_to_object(b.best_ask()); })
      .def("is_crossed", &OrderBook::is_crossed)
      .def("level_count", &OrderBook::level_count, py::arg("side"))
      .def("levels", [](const OrderBook& b, Side s) { return levels_to_list(b.levels(s)); },
           py::arg("side"),
           "Levels on one side, best to worst, as (price, quantity) tuples. A copy: the "
           "result is unaffected by later updates to the book.");

  m.def(
      "dump_csv",
      [](const OrderBook& book, std::size_t depth) {
        std::ostringstream out;
        perpcarry::dump_csv(book, out, depth);
        return out.str();
      },
      py::arg("book"), py::arg("depth") = 25,
      "side,level,price,quantity for the top `depth` levels per side, bids then asks. A "
      "pure, deterministic, locale-independent function of book state -- which is what "
      "makes a digest of it a stable checkpoint (M3-T3).");

  py::class_<PipelineResult>(m, "PipelineResult")
      .def_readonly("replay", &PipelineResult::replay)
      .def_readonly("consumed", &PipelineResult::consumed)
      .def_readonly("queue_capacity", &PipelineResult::queue_capacity)
      .def_readonly("peak_queue_occupancy", &PipelineResult::peak_queue_occupancy)
      .def_readonly("producer_stalls", &PipelineResult::producer_stalls)
      .def_readonly("consumer_stalls", &PipelineResult::consumer_stalls);

  py::class_<Pipeline>(m, "Pipeline")
      .def(py::init<std::size_t>(), py::arg("queue_capacity") = Pipeline::kDefaultQueueCapacity)
      // The GIL is released for the duration: run() spawns two C++ threads and touches no
      // Python object, and holding the GIL across it would serialise the producer against
      // the interpreter for no reason.
      .def(
          "run",
          [](Pipeline& pipeline, const std::vector<BookUpdate>& batch) {
            py::gil_scoped_release release;
            return pipeline.run(std::span<const BookUpdate>(batch));
          },
          py::arg("batch"),
          "Replay a batch across the ingest/replay thread boundary. One crossing per "
          "batch, never per event (Risk R4).")
      .def("book", &Pipeline::book, py::return_value_policy::reference_internal)
      .def("stats", &Pipeline::stats, py::return_value_policy::reference_internal);

  py::class_<BookReplayer>(m, "BookReplayer")
      .def(py::init<>())
      .def(
          "apply_batch",
          [](BookReplayer& replayer, const std::vector<BookUpdate>& batch) {
            return replayer.apply_batch(std::span<const BookUpdate>(batch));
          },
          py::arg("batch"),
          "Apply a batch of updates in order, returning the number applied. The batch is "
          "the unit of interop by design (Risk R4); there is no single-row entry point.")
      // reference_internal ties the returned book's lifetime to this replayer, so a book
      // held in Python keeps its owner alive. Without it, `book = replayer.book(); del
      // replayer` would leave Python reading freed memory.
      .def("book", &BookReplayer::book, py::return_value_policy::reference_internal)
      .def("stats", &BookReplayer::stats, py::return_value_policy::reference_internal);
}

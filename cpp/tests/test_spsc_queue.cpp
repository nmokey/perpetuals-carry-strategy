// M3-T2 -- the lock-free SPSC queue.
// Spec: docs/specs/M3/M3-T2-spsc-queue.md, decision D-020 (OD-6).
//
// This is the one M2/M3 component whose tests carry no licence surface at all: no corpus,
// no vendor data, nothing that cannot run in CI. So everything here runs on every push,
// including -- via the sanitizer job -- the data-race check.

#include <catch2/catch_test_macros.hpp>

#include <atomic>
#include <cstdint>
#include <numeric>
#include <thread>
#include <vector>

#include "perpcarry/spsc_queue.hpp"

using perpcarry::SPSCQueue;

namespace {

// Counts every construction and destruction so the queue's raw-storage bookkeeping can be
// audited. A buffer of default-constructed objects assigned over would not be able to make
// the claim this type checks.
struct Counted {
  static inline int constructions = 0;
  static inline int destructions = 0;

  int value = 0;

  Counted() { ++constructions; }
  explicit Counted(int v) : value(v) { ++constructions; }
  Counted(const Counted& other) : value(other.value) { ++constructions; }
  Counted(Counted&& other) noexcept : value(other.value) { ++constructions; }
  Counted& operator=(const Counted&) = default;
  Counted& operator=(Counted&&) noexcept = default;
  ~Counted() { ++destructions; }

  static void reset() {
    constructions = 0;
    destructions = 0;
  }
};

// Drives one full producer/consumer run and returns everything the consumer saw, in the
// order it saw it. `yield_every` perturbs the interleaving without changing the input.
std::vector<int> run_pipeline(int items, int yield_every) {
  SPSCQueue<int> queue(1024);
  std::vector<int> consumed;
  consumed.reserve(static_cast<std::size_t>(items));

  std::thread producer([&queue, items, yield_every] {
    for (int i = 0; i < items; ++i) {
      if (yield_every > 0 && i % yield_every == 0) std::this_thread::yield();
      while (!queue.try_push(i)) std::this_thread::yield();
    }
  });

  int value = 0;
  for (int i = 0; i < items; ++i) {
    while (!queue.try_pop(value)) std::this_thread::yield();
    consumed.push_back(value);
  }
  producer.join();
  return consumed;
}

}  // namespace

TEST_CASE("a filled queue gives everything back in order", "[spsc]") {
  SPSCQueue<int> queue(8);
  REQUIRE(queue.capacity() == 8);
  REQUIRE(queue.empty());

  for (int i = 0; i < 8; ++i) {
    REQUIRE(queue.try_push(i));
  }

  int value = 0;
  for (int i = 0; i < 8; ++i) {
    REQUIRE(queue.try_pop(value));
    REQUIRE(value == i);
  }
  REQUIRE(queue.empty());
}

TEST_CASE("capacity is rounded up to a power of two, and zero is rejected", "[spsc]") {
  REQUIRE(SPSCQueue<int>(1).capacity() == 1);
  REQUIRE(SPSCQueue<int>(5).capacity() == 8);
  REQUIRE(SPSCQueue<int>(1024).capacity() == 1024);
  REQUIRE_THROWS_AS(SPSCQueue<int>(0), std::invalid_argument);
}

TEST_CASE("a full queue refuses the push rather than blocking or overwriting", "[spsc]") {
  SPSCQueue<int> queue(4);
  for (int i = 0; i < 4; ++i) {
    REQUIRE(queue.try_push(i));
  }

  // Refused, and -- the part that matters -- the refusal did not cost the oldest item.
  REQUIRE_FALSE(queue.try_push(99));
  REQUIRE(queue.size_approx() == 4);

  int value = 0;
  REQUIRE(queue.try_pop(value));
  REQUIRE(value == 0);

  // One slot freed, so exactly one more push fits.
  REQUIRE(queue.try_push(99));
  REQUIRE_FALSE(queue.try_push(100));
}

TEST_CASE("an empty queue reports empty rather than yielding a stale value", "[spsc]") {
  SPSCQueue<int> queue(4);
  int value = -1;

  REQUIRE_FALSE(queue.try_pop(value));
  REQUIRE(value == -1);  // untouched

  REQUIRE(queue.try_push(7));
  REQUIRE(queue.try_pop(value));
  REQUIRE(value == 7);

  // Popping the same slot again must not hand back the item that was there.
  value = -1;
  REQUIRE_FALSE(queue.try_pop(value));
  REQUIRE(value == -1);
}

TEST_CASE("the ring wraps many times without losing or reordering", "[spsc]") {
  // Capacity 8, ten full laps, one item in flight at a time -- so every push and pop
  // straddles the wrap at a different offset. Index arithmetic is where off-by-ones live.
  SPSCQueue<int> queue(8);
  int value = 0;
  for (int i = 0; i < 80; ++i) {
    REQUIRE(queue.try_push(i));
    REQUIRE(queue.try_pop(value));
    REQUIRE(value == i);
  }
  REQUIRE(queue.empty());
}

TEST_CASE("a non-trivial element is constructed and destroyed exactly once", "[spsc]") {
  SECTION("drained normally") {
    Counted::reset();
    {
      SPSCQueue<Counted> queue(16);
      for (int i = 0; i < 100; ++i) {
        while (!queue.try_push(Counted(i))) {
          Counted out;
          REQUIRE(queue.try_pop(out));
        }
      }
      Counted out;
      while (queue.try_pop(out)) {
      }
    }
    // Balanced: nothing leaked, and nothing was destroyed twice (which would push
    // destructions above constructions).
    REQUIRE(Counted::constructions == Counted::destructions);
    REQUIRE(Counted::constructions > 0);
  }

  SECTION("destroyed with items still queued") {
    Counted::reset();
    {
      SPSCQueue<Counted> queue(16);
      for (int i = 0; i < 10; ++i) {
        REQUIRE(queue.try_push(Counted(i)));
      }
      // Left deliberately full: the queue's destructor owns those ten objects, and raw
      // storage means nothing else will ever destroy them.
    }
    REQUIRE(Counted::constructions == Counted::destructions);
  }

  SECTION("wrapped, so slots are reused") {
    Counted::reset();
    {
      SPSCQueue<Counted> queue(4);
      Counted out;
      for (int i = 0; i < 50; ++i) {
        REQUIRE(queue.try_push(Counted(i)));
        REQUIRE(queue.try_pop(out));
        REQUIRE(out.value == i);
      }
    }
    REQUIRE(Counted::constructions == Counted::destructions);
  }
}

TEST_CASE("ten million items cross two threads exactly once and in order", "[spsc][stress]") {
  // The criterion's stress run. Verified against a counter rather than a collected vector,
  // so the check is O(1) in memory and the test measures the queue rather than the
  // allocator.
  //
  // A single-threaded test cannot stand in for this: with no second thread there is nothing
  // to observe a missing release/acquire pair from, so the ordering could be wrong and
  // every other test here would still pass.
  constexpr int kItems = 10'000'000;
  SPSCQueue<std::int64_t> queue(65536);
  std::atomic<bool> producer_ok{true};

  std::thread producer([&queue, &producer_ok] {
    for (std::int64_t i = 0; i < kItems; ++i) {
      while (!queue.try_push(i)) std::this_thread::yield();
    }
    producer_ok.store(true, std::memory_order_release);
  });

  std::int64_t expected = 0;
  std::int64_t value = 0;
  bool ordered = true;
  // A cheap invariant, checked on every iteration rather than at the end: an occupancy
  // above capacity is impossible, so seeing one means the unsigned subtraction inside
  // size_approx() underflowed -- which is what happens if its two loads are read in the
  // wrong order. Not the defect this test was written for, which is rather the point (C14).
  bool occupancy_sane = true;
  while (expected < kItems) {
    if (!queue.try_pop(value)) {
      std::this_thread::yield();
      continue;
    }
    if (queue.size_approx() > queue.capacity()) occupancy_sane = false;
    if (value != expected) ordered = false;
    ++expected;
  }
  producer.join();

  REQUIRE(ordered);                 // none lost, none duplicated, none reordered
  REQUIRE(occupancy_sane);
  REQUIRE(expected == kItems);
  REQUIRE(queue.empty());
  REQUIRE(producer_ok.load(std::memory_order_acquire));
}

TEST_CASE("size_approx never underflows, even read from a third thread", "[spsc]") {
  // size_approx() subtracts two independently-loaded atomics. C++ does not order the
  // operands of `-`, so a version that reads tail first can sample tail, have head advance
  // past it, and return an astronomically large size_t instead of a small one.
  //
  // The consumer cannot expose this -- it owns head_, which is why the queue's other tests
  // cannot see the difference. An independent observer can, so this is that observer.
  //
  // The bound is deliberately *not* `<= capacity`: an observer that samples head early and
  // tail late may legitimately see more than a queue-full, because both indices moved
  // between the two loads. Only an underflow lands anywhere near SIZE_MAX.
  constexpr std::int64_t kItems = 2'000'000;
  constexpr std::size_t kUnderflowBound = static_cast<std::size_t>(-1) / 2;

  SPSCQueue<std::int64_t> queue(64);
  std::atomic<bool> running{true};
  std::atomic<bool> underflowed{false};
  std::atomic<std::int64_t> observations{0};

  std::thread observer([&] {
    while (running.load(std::memory_order_acquire)) {
      if (queue.size_approx() > kUnderflowBound) underflowed.store(true, std::memory_order_release);
      observations.fetch_add(1, std::memory_order_relaxed);
    }
  });

  std::thread producer([&] {
    for (std::int64_t i = 0; i < kItems; ++i) {
      while (!queue.try_push(i)) std::this_thread::yield();
    }
  });

  std::int64_t value = 0;
  for (std::int64_t i = 0; i < kItems; ++i) {
    while (!queue.try_pop(value)) std::this_thread::yield();
  }
  producer.join();
  running.store(false, std::memory_order_release);
  observer.join();

  REQUIRE(observations.load(std::memory_order_relaxed) > 0);  // the observer really ran
  REQUIRE_FALSE(underflowed.load(std::memory_order_acquire));
}

TEST_CASE("the consumer's output does not depend on how the producer was paced", "[spsc]") {
  // D-020's constraint, as a test rather than a comment. The queue may change *when* an
  // item is consumed; it must never change which item or in what order. Reproducibility
  // given a fixed seed is a north-star invariant, and a queue between replay and simulation
  // is exactly the kind of change that takes it away quietly.
  constexpr int kItems = 20'000;

  const std::vector<int> paced_every_item = run_pipeline(kItems, 1);
  const std::vector<int> paced_occasionally = run_pipeline(kItems, 7);
  const std::vector<int> unpaced = run_pipeline(kItems, 0);

  std::vector<int> expected(kItems);
  std::iota(expected.begin(), expected.end(), 0);

  REQUIRE(paced_every_item == expected);
  REQUIRE(paced_occasionally == expected);
  REQUIRE(unpaced == expected);
}

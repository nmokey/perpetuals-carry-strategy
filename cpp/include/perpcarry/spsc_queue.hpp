// Bounded lock-free single-producer/single-consumer queue.
// See docs/specs/M3/M3-T2-spsc-queue.md and OD-6 / D-020.
//
// This is the project's only real concurrency, and OD-6 chose it because the
// feed-handler -> strategy-engine split is a structure that exists in real systems -- not
// because it makes a backtest faster. In a backtest the producer is reading a file, so this
// queue is not on a latency-critical path in any live sense. The defensible claim is that
// the structure mirrors a real boundary and that its throughput is measured.
//
// The determinism constraint from D-020 lives on the *consumer*, not here: this queue is
// FIFO, so it can change when an item is consumed but never which item or in what order.
// A consumer whose behaviour depended on occupancy or on producer timing would make results
// differ run to run on identical input, and reproducibility is a north-star invariant.
//
// Exactly one producer thread and exactly one consumer thread. Two producers is not a
// degraded mode, it is undefined behaviour.
#ifndef PERPCARRY_SPSC_QUEUE_HPP
#define PERPCARRY_SPSC_QUEUE_HPP

#include <atomic>
#include <cstddef>
#include <memory>
#include <new>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <utility>

namespace perpcarry {
namespace detail {

// Padding width for the two indices. Measured 2026-08-29: this is 256 on Apple Silicon and
// 64 on x86-64, so the 64 that every SPSC tutorial hard-codes would under-pad by 4x here --
// silently reintroducing the false sharing the padding exists to prevent, and only on one
// architecture.
//
// GCC warns (-Winterference-size) when the constant is used in a header, because its value
// can differ between translation units and is therefore an ABI hazard. That is a real
// concern for a library boundary; it is not one here, since this queue is only ever used
// inside this project, built as one unit, and never crosses a shared-library edge.
#if defined(__GNUC__) && !defined(__clang__)
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Winterference-size"
#endif
#if defined(__cpp_lib_hardware_interference_size)
inline constexpr std::size_t kCacheLine = std::hardware_destructive_interference_size;
#else
inline constexpr std::size_t kCacheLine = 64;
#endif
#if defined(__GNUC__) && !defined(__clang__)
#pragma GCC diagnostic pop
#endif

}  // namespace detail

template <typename T>
class SPSCQueue {
 public:
  // `capacity` is rounded up to a power of two so the wrap is a mask rather than a divide.
  // Ask capacity() for what you actually got.
  explicit SPSCQueue(std::size_t capacity)
      : capacity_(round_up_to_power_of_two(capacity)),
        mask_(capacity_ - 1),
        slots_(std::make_unique<Slot[]>(capacity_)) {}

  ~SPSCQueue() {
    // Slots hold raw storage, so anything still queued at destruction has been constructed
    // and must be destroyed here. Only the objects between head and tail are live.
    const std::size_t head = head_.load(std::memory_order_relaxed);
    const std::size_t tail = tail_.load(std::memory_order_relaxed);
    for (std::size_t i = head; i != tail; ++i) {
      slots_[i & mask_].value.~T();
    }
  }

  SPSCQueue(const SPSCQueue&) = delete;
  SPSCQueue& operator=(const SPSCQueue&) = delete;

  // Producer thread only. Returns false when full -- it never blocks and never overwrites.
  //
  // What to do when full is deliberately the caller's policy. A spin loop buried in here
  // would make the throughput benchmark a measurement of the spin rather than of the queue.
  template <typename U>
  bool try_push(U&& value) {
    // The producer owns tail_, so it can read its own index without synchronising; only the
    // consumer's index has to be acquired.
    const std::size_t tail = tail_.load(std::memory_order_relaxed);
    if (tail - head_.load(std::memory_order_acquire) == capacity_) {
      return false;
    }
    new (&slots_[tail & mask_].value) T(std::forward<U>(value));
    // Release pairs with the consumer's acquire on tail_: it publishes the constructed
    // object, not merely the index.
    tail_.store(tail + 1, std::memory_order_release);
    return true;
  }

  // Consumer thread only. Returns false when empty.
  bool try_pop(T& out) {
    const std::size_t head = head_.load(std::memory_order_relaxed);
    if (head == tail_.load(std::memory_order_acquire)) {
      return false;
    }
    T* slot = &slots_[head & mask_].value;
    out = std::move(*slot);
    slot->~T();
    head_.store(head + 1, std::memory_order_release);
    return true;
  }

  std::size_t capacity() const { return capacity_; }

  // Approximate by nature: either index may move under a concurrent peer. Safe for
  // reporting and for M3-T3's "the queue actually filled" check; never for a decision the
  // simulation's output depends on, which is exactly what D-020 forbids.
  std::size_t size_approx() const {
    // head_ is loaded *first*, in its own statement, and that is load-bearing rather than
    // stylistic. C++ does not order the operands of `-`, so `tail_.load() - head_.load()`
    // may read tail first; if head then advances past that sampled tail before its own
    // load, the unsigned subtraction underflows to an astronomically large size_t rather
    // than to something obviously wrong. Sampling head first is safe unconditionally:
    // head <= tail holds at every instant, so any later tail is >= the head already read.
    const std::size_t head = head_.load(std::memory_order_acquire);
    const std::size_t tail = tail_.load(std::memory_order_acquire);
    return tail - head;
  }

  bool empty() const { return size_approx() == 0; }

 private:
  // An anonymous union member gives correctly aligned, uninitialised storage for one T:
  // the union's constructor and destructor do nothing, so no T exists until try_push
  // placement-news one and none survives try_pop's explicit destroy. That is what makes
  // "constructed and destroyed exactly once per item" true for a non-trivial T, which a
  // buffer of default-constructed objects assigned over could not claim.
  union Slot {
    Slot() {}
    ~Slot() {}
    T value;
  };

  static std::size_t round_up_to_power_of_two(std::size_t capacity) {
    if (capacity == 0) {
      throw std::invalid_argument("SPSCQueue capacity must be at least 1");
    }
    std::size_t rounded = 1;
    while (rounded < capacity) {
      if (rounded > (static_cast<std::size_t>(-1) >> 1)) {
        throw std::invalid_argument("SPSCQueue capacity too large: " +
                                    std::to_string(capacity));
      }
      rounded <<= 1;
    }
    return rounded;
  }

  const std::size_t capacity_;
  const std::size_t mask_;
  std::unique_ptr<Slot[]> slots_;

  // Separate cache lines. Without the padding the two indices share one, every push
  // invalidates the consumer's line and vice versa, and the "lock-free" queue spends its
  // time on coherence traffic -- the classic way this structure gets written and then
  // benchmarks badly.
  alignas(detail::kCacheLine) std::atomic<std::size_t> head_{0};
  alignas(detail::kCacheLine) std::atomic<std::size_t> tail_{0};
};

}  // namespace perpcarry

#endif  // PERPCARRY_SPSC_QUEUE_HPP

#include <pybind11/pybind11.h>

#include <string>

#include "perpcarry/version.hpp"

namespace py = pybind11;

// The C++/Python boundary deliberately sits at the pipeline level (post-SPSC-queue),
// never per-tick -- see design-doc Risk R4. Bindings added here should expose batch
// entry points (replay a window, simulate a set of orders), not per-event calls.
PYBIND11_MODULE(perpcarry_cpp, m) {
  m.doc() = "C++ core for PerpCarry: order book reconstruction and impact simulation";
  m.attr("__version__") = std::string(perpcarry::version());
  m.def("version", []() { return std::string(perpcarry::version()); },
        "Version string of the compiled C++ core.");
}

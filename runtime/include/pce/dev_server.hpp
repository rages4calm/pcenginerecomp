#pragma once
#include "pce/video.hpp"
#include "pce/dev_instruction.hpp"
#include <array>
#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace pce {
struct DevSnapshot {
  std::uint64_t frame = 0, ticks = 0, frame_ticks = 0;
  bool local_paused = false;
  // Trusted host-produced JSON object, never guest or client text.
  std::function<std::string()> status;
  std::function<void()> apply_input;
  // Host-owned opt-in policy selection, only from a quiescent remote pause.
  // The callback validates the first-dispatch boundary; later calls retain it.
  std::function<void()> reference_frames;
  bool reference_selected = false;
  std::function<DevLocation()> location;
  // Exact compare-and-set of PC,A,X,Y,SP,P,MPR[8] (15 bytes). Host opt-in
  // required; clocks, retired work and hidden CPU/device state are not edited.
  std::function<void(const std::vector<std::uint8_t>&,
                     const std::vector<std::uint8_t>&)> write_cpu;
  std::function<std::string(const std::string&)> save_checkpoint, load_checkpoint;
  // Paused, stored retired-source observations only; no source bytes or peeks.
  std::function<std::string()> capture_summary;
  // Stored bus observer counters only; never peeks or steps guest state.
  std::function<std::string()> bus_trace_summary;
  std::function<std::string(std::uint32_t, unsigned)> disc_origin;
  std::function<std::string(std::uint64_t, std::uint32_t, std::uint32_t)>
      capture_sources;
  // false: last completed guest image; true: composed desktop target.
  std::function<VideoFrame(bool)> capture;
  // Optional desktop-only resize. Arguments are window units, not pixels.
  std::function<void(unsigned, unsigned)> resize_window;
  // Optional host-defined, non-MMIO debug access at a quiescent pause.
  // Writes must preflight the whole expected range before changing any byte.
  std::function<std::vector<std::uint8_t>(std::uint32_t, std::uint32_t)>
      read_memory;
  std::function<void(std::uint32_t, const std::vector<std::uint8_t> &,
                     const std::vector<std::uint8_t> &)>
      write_memory;
};

// Optional main-thread development control. IPv4 loopback only, one client,
// bounded nonblocking I/O. No network thread can mutate guest state.
class DevServer {
public:
  explicit DevServer(std::uint16_t port, bool start_paused = false);
  ~DevServer();
  DevServer(const DevServer &) = delete;
  DevServer &operator=(const DevServer &) = delete;
  std::uint16_t port() const;
  void poll(const DevSnapshot &);
  bool paused(std::uint64_t current_frame) const;
  const std::array<std::uint16_t, 5> &input_masks() const;
  void restore_input_masks(const std::array<std::uint16_t,5>&);
  bool quit_requested() const;
  bool instruction_control() const;
  void instruction_boundary(const DevLocation&,std::uint64_t ticks);

private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};
} // namespace pce

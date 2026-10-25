#pragma once
#include "pce/video.hpp"
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
  // Paused, stored retired-source observations only; no source bytes or peeks.
  std::function<std::string()> capture_summary;
  std::function<std::string(std::uint64_t, std::uint32_t, std::uint32_t)>
      capture_sources;
  // false: last completed guest image; true: composed desktop target.
  std::function<VideoFrame(bool)> capture;
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
  bool quit_requested() const;

private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};
} // namespace pce

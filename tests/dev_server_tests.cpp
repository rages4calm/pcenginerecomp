#include "pce/dev_server.hpp"
#include <chrono>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <thread>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
using Socket = SOCKET;
static constexpr Socket bad = INVALID_SOCKET;
static void close_socket(Socket s) { closesocket(s); }
#else
#include <arpa/inet.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <unistd.h>
using Socket = int;
static constexpr Socket bad = -1;
static void close_socket(Socket s) { ::close(s); }
#endif

static void require(bool condition, const char *message) {
  if (!condition)
    throw std::runtime_error(message);
}
struct Peer {
  Socket s = bad;
  std::string received;
  explicit Peer(std::uint16_t port) {
    s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    require(s != bad, "client creation failed");
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_port = htons(port);
    a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (connect(s, reinterpret_cast<sockaddr *>(&a), sizeof(a))) {
      close_socket(s);
      throw std::runtime_error("client connection failed");
    }
#ifdef _WIN32
    u_long one = 1;
    require(ioctlsocket(s, FIONBIO, &one) == 0, "client nonblocking failed");
#else
    require(fcntl(s, F_SETFL, fcntl(s, F_GETFL, 0) | O_NONBLOCK) == 0,
            "client nonblocking failed");
#endif
  }
  ~Peer() {
    if (s != bad)
      close_socket(s);
  }
  void close() {
    close_socket(s);
    s = bad;
  }
  void send(const std::string &text) {
    std::size_t n = 0;
    const auto deadline =
        std::chrono::steady_clock::now() + std::chrono::seconds(2);
    while (n < text.size()) {
      const auto count =
          ::send(s, text.data() + n, static_cast<int>(text.size() - n), 0);
      if (count > 0)
        n += static_cast<std::size_t>(count);
      else
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
      require(std::chrono::steady_clock::now() < deadline,
              "client send timed out");
    }
  }
  std::string response(pce::DevServer &server,
                       const pce::DevSnapshot &snapshot) {
    const auto deadline =
        std::chrono::steady_clock::now() + std::chrono::seconds(3);
    for (;;) {
      server.poll(snapshot);
      char buffer[4096];
      const auto count = recv(s, buffer, sizeof(buffer), 0);
      if (count > 0)
        received.append(buffer, static_cast<std::size_t>(count));
      const auto newline = received.find('\n');
      if (newline != std::string::npos) {
        auto line = received.substr(0, newline);
        received.erase(0, newline + 1);
        return line;
      }
      require(std::chrono::steady_clock::now() < deadline,
              "response timed out");
      std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
  }
  std::string call(pce::DevServer &server, const pce::DevSnapshot &snapshot,
                   const std::string &request) {
    send(request + "\n");
    return response(server, snapshot);
  }
};
static bool has(const std::string &text, const std::string &part) {
  return text.find(part) != std::string::npos;
}

int main() {
  try {
    unsigned checks = 0, captures = 0, status_calls = 0;
    pce::DevServer server(0, true);
    require(server.port() != 0 && server.paused(0),
            "automatic port or initial pause failed");
    ++checks;
    bool exclusive = false;
    try {
      pce::DevServer duplicate(server.port());
    } catch (const std::exception &) {
      exclusive = true;
    }
    require(exclusive, "listener allowed duplicate bind");
    ++checks;
    pce::DevSnapshot state;
    state.frame = 12;
    state.ticks = 345;
    state.frame_ticks = 340;
    state.status = [&] {
      ++status_calls;
      return "{\"native_steps\":7}";
    };
    state.capture = [&](bool present) {
      ++captures;
      return pce::VideoFrame{
          present ? 1U : 2U, present ? 2U : 1U, {0, 1, 2, 253, 254, 255}};
    };
    {
      Peer peer(server.port());
      peer.send("{\"id\":1,\"cmd\":\"set_in");
      for (unsigned n = 0; n < 3; ++n)
        server.poll(state);
      require(server.input_masks()[0] == 0,
              "fragment changed state before complete request");
      ++checks;
      peer.send("put\",\"mask\":4095}\n");
      require(has(peer.response(server, state), "\"ok\":true") &&
                  server.input_masks()[0] == 4095,
              "fragmented request failed");
      ++checks;
      peer.send("{\"id\":2,\"cmd\":\"ping\"}\n{\"id\":3,\"cmd\":\"status\"}\n");
      require(has(peer.response(server, state), "\"protocol\":\"pce-dev-1\""),
              "pipelined ping failed");
      const auto status = peer.response(server, state);
      require(has(status, "\"id\":3") && has(status, "\"frame\":12") &&
                  has(status, "\"ticks\":345") &&
                  has(status, "\"paused\":true") &&
                  has(status, "\"native_steps\":7") && status_calls == 1 &&
                  captures == 0,
              "lazy status failed");
      checks += 2;
      for (unsigned port = 0; port < 5; ++port) {
        const auto response =
            peer.call(server, state,
                      "{\"id\":4,\"cmd\":\"set_input\",\"mask\":" +
                          std::to_string(1U << port) +
                          ",\"port\":" + std::to_string(port) + "}");
        require(has(response, "\"ok\":true") &&
                    server.input_masks()[port] == (1U << port),
                "input port failed");
        ++checks;
      }
      require(has(peer.call(server, state,
                            "{\"id\":5,\"cmd\":\"clear_input\",\"port\":2}"),
                  "\"ok\":true") &&
                  server.input_masks()[2] == 0 && server.input_masks()[1] == 2,
              "selective input clear failed");
      ++checks;
      require(
          has(peer.call(server, state, "{\"id\":6,\"cmd\":\"clear_input\"}"),
              "\"ok\":true") &&
              server.input_masks() == std::array<std::uint16_t, 5>{},
          "all input clear failed");
      ++checks;
      require(has(peer.call(server, state,
                            "{\"id\":7,\"cmd\":\"step_frames\",\"frames\":3}"),
                  "\"target_frame\":15") &&
                  !server.paused(12) && !server.paused(14) && server.paused(15),
              "frame stepping boundary failed");
      ++checks;
      peer.call(server, state, "{\"id\":8,\"cmd\":\"resume\"}");
      require(!server.paused(0) && !server.paused(100), "resume failed");
      ++checks;
      auto locally_paused = state;
      locally_paused.local_paused = true;
      auto local_status =
          peer.call(server, locally_paused, "{\"id\":8,\"cmd\":\"status\"}");
      require(has(local_status, "\"paused\":true") &&
                  has(local_status, "\"local_paused\":true"),
              "local pause absent from aggregate status");
      ++checks;
      require(has(peer.call(server, locally_paused,
                            "{\"id\":8,\"cmd\":\"step_frames\",\"frames\":1}"),
                  "release the local desktop pause") &&
                  !server.paused(100),
              "local pause frame-step refusal mutated network state");
      ++checks;
      peer.call(server, locally_paused, "{\"id\":8,\"cmd\":\"resume\"}");
      require(has(peer.call(server, locally_paused,
                            "{\"id\":8,\"cmd\":\"status\"}"),
                  "\"paused\":true") &&
                  !server.paused(12),
              "network resume overrode local pause");
      ++checks;
      peer.call(server, state, "{\"id\":9,\"cmd\":\"pause\"}");
      require(server.paused(12), "pause failed");
      ++checks;
      const auto guest =
          peer.call(server, state, "{\"id\":10,\"cmd\":\"screenshot\"}");
      require(has(guest, "\"source\":\"guest\"") &&
                  has(guest, "\"width\":2,\"height\":1") &&
                  has(guest, "\"encoding\":\"rgb24-base64\"") &&
                  has(guest, "\"data\":\"AAEC/f7/\"") &&
                  has(guest, "\"frame_ticks\":340") && captures == 1,
              "guest RGB response failed");
      ++checks;
      require(
          has(peer.call(server, state, "{\"id\":11,\"cmd\":\"present_shot\"}"),
              "\"source\":\"present\"") &&
              captures == 2,
          "present capture alias failed");
      ++checks;
      require(
          has(peer.call(
                  server, state,
                  "{\"id\":12,\"cmd\":\"screenshot\",\"source\":\"present\"}"),
              "\"height\":2") &&
              captures == 3,
          "explicit present capture failed");
      ++checks;
      require(has(peer.call(
                      server, state,
                      "{\"id\":9007199254740991,\"c\\u006dd\":\"pi\\u006eg\"}"),
                  "\"id\":9007199254740991,\"ok\":true"),
              "ASCII JSON escapes or exact max id failed");
      ++checks;
      std::string exact = "{\"id\":14,\"cmd\":\"ping\"}";
      exact.append(8191 - exact.size(), ' ');
      require(has(peer.call(server, state, exact), "\"id\":14,\"ok\":true"),
              "maximum request including newline rejected");
      ++checks;
      for (const std::string &invalid :
           {"{}",
            "{\"cmd\":\"ping\"}",
            "{\"id\":1}",
            "{\"id\":1,\"id\":2,\"cmd\":\"ping\"}",
            "{\"id\":1,\"cmd\":\"ping\",\"cmd\":\"quit\"}",
            "{\"id\":1,\"cmd\":\"quit\",\"extra\":0}",
            "{\"id\":-1,\"cmd\":\"ping\"}",
            "{\"id\":1.5,\"cmd\":\"ping\"}",
            "{\"id\":1e0,\"cmd\":\"ping\"}",
            "{\"id\":01,\"cmd\":\"ping\"}",
            "{\"id\":9007199254740992,\"cmd\":\"ping\"}",
            "{\"id\":18446744073709551616,\"cmd\":\"ping\"}",
            "{\"id\":1,\"cmd\":[]}",
            "{\"id\":1,\"cmd\":{}}",
            "{\"id\":1,\"cmd\":true}",
            "{\"id\":1,\"cmd\":null}",
            "{\"id\":\"1\",\"cmd\":\"ping\"}",
            "{\"id\":1,\"cmd\":\"ping\",}",
            "{\"id\":1,\"cmd\":\"ping\"}junk",
            "{\"id\":1,\"cmd\":\"pi\\qng\"}",
            "{\"id\":1,\"cmd\":\"pi\\u0080ng\"}",
            "{\"id\":1,\"cmd\":\"pi\\uD800ng\"}",
            "{\"id\":1,\"cmd\":\"unknown\"}",
            "{\"id\":1,\"cmd\":\"set_input\",\"mask\":4096}",
            "{\"id\":1,\"cmd\":\"set_input\",\"mask\":1,\"port\":5}",
            "{\"id\":1,\"cmd\":\"set_input\"}",
            "{\"id\":1,\"cmd\":\"set_input\",\"mask\":\"1\"}",
            "{\"id\":1,\"cmd\":\"clear_input\",\"port\":5}",
            "{\"id\":1,\"cmd\":\"step_frames\",\"frames\":0}",
            "{\"id\":1,\"cmd\":\"step_frames\",\"frames\":601}",
            "{\"id\":1,\"cmd\":\"screenshot\",\"path\":\"out.png\"}",
            "{\"id\":1,\"cmd\":\"screenshot\",\"source\":\"bad\"}",
            "{\"id\":1,\"cmd\":\"present_shot\",\"source\":\"guest\"}"}) {
        require(has(peer.call(server, state, invalid), "\"ok\":false") &&
                    !server.quit_requested() &&
                    server.input_masks() == std::array<std::uint16_t, 5>{},
                "invalid request accepted or mutated state");
        ++checks;
      }
      auto missing = state;
      missing.capture = {};
      require(
          has(peer.call(server, missing, "{\"id\":1,\"cmd\":\"screenshot\"}"),
              "capture unavailable"),
          "unavailable capture accepted");
      ++checks;
      auto invalid = state;
      invalid.capture = [](bool) {
        return pce::VideoFrame{1025, 1, std::vector<std::uint8_t>(3075)};
      };
      require(
          has(peer.call(server, invalid, "{\"id\":1,\"cmd\":\"screenshot\"}"),
              "\"ok\":false"),
          "oversize guest image accepted");
      ++checks;
      invalid.capture = [](bool) { return pce::VideoFrame{2, 1, {1}}; };
      require(
          has(peer.call(server, invalid, "{\"id\":1,\"cmd\":\"screenshot\"}"),
              "\"ok\":false"),
          "malformed RGB accepted");
      ++checks;
      invalid.capture = [](bool) -> pce::VideoFrame {
        throw std::runtime_error("authored capture refusal");
      };
      require(
          has(peer.call(server, invalid, "{\"id\":1,\"cmd\":\"screenshot\"}"),
              "authored capture refusal"),
          "capture exception escaped server");
      ++checks;
      invalid = state;
      invalid.frame = std::numeric_limits<std::uint64_t>::max();
      require(has(peer.call(server, invalid,
                            "{\"id\":1,\"cmd\":\"step_frames\",\"frames\":1}"),
                  "\"ok\":false"),
              "frame target overflow accepted");
      ++checks;
      peer.call(server, state, "{\"id\":1,\"cmd\":\"set_input\",\"mask\":8}");
      peer.close();
      for (unsigned n = 0; n < 10; ++n)
        server.poll(state);
      require(server.input_masks()[0] == 0 && server.paused(12),
              "disconnect did not release input or lost pause");
      ++checks;
    }
    {
      Peer peer(server.port());
      require(has(peer.call(server, state, "{\"id\":99,\"cmd\":\"ping\"}"),
                  "\"id\":99,\"ok\":true"),
              "reconnection failed");
      ++checks;
      peer.send(std::string(8192, 'x'));
      require(has(peer.response(server, state), "request exceeds 8192 bytes"),
              "oversize request not bounded");
      ++checks;
    }
    for (unsigned n = 0; n < 10; ++n)
      server.poll(state);
    {
      Peer peer(server.port());
      peer.send("{");
      server.poll(state);
      std::this_thread::sleep_for(std::chrono::milliseconds(5100));
      server.poll(state);
      ++checks;
    }
    {
      Peer peer(server.port());
      auto large = state;
      large.capture = [](bool) {
        return pce::VideoFrame{2000, 2000,
                               std::vector<std::uint8_t>(12000000, 0x55)};
      };
      peer.send("{\"id\":101,\"cmd\":\"present_shot\"}\n");
      const auto begin = std::chrono::steady_clock::now();
      server.poll(large);
      require(std::chrono::steady_clock::now() - begin <
                  std::chrono::seconds(2),
              "large response blocked poll waiting for reader");
      ++checks;
      // Intentionally never drain this response. The absolute send deadline
      // must release it and permit another connection, without host changes.
      std::this_thread::sleep_for(std::chrono::milliseconds(5100));
      server.poll(state);
      require(server.paused(12) &&
                  server.input_masks() == std::array<std::uint16_t, 5>{},
              "stalled capture changed host controls");
      ++checks;
    }
    {
      Peer peer(server.port());
      require(has(peer.call(server, state, "{\"id\":100,\"cmd\":\"quit\"}"),
                  "\"ok\":true") &&
                  server.quit_requested(),
              "quit failed after stalled-client timeout");
      ++checks;
    }
    std::cout
        << checks
        << " development-server TCP/parser/control/capture checks passed\n";
    return 0;
  } catch (const std::exception &e) {
    std::cerr << e.what() << '\n';
    return 1;
  }
}

#pragma once
#include "pce/runtime.hpp"
#include <unordered_map>

namespace pce {
// Host diagnostics. Tags are learned only after attachment and never enter
// checkpoints or participate in native dispatch admission.
class DiscOrigin {
public:
    DiscOrigin()=default;
    DiscOrigin(const DiscOrigin&)=delete;
    DiscOrigin& operator=(const DiscOrigin&)=delete;
    ~DiscOrigin();
    void attach(Bus&,Cpu&);
    void detach() noexcept;
    void reset();
    void invalidate(std::uint32_t address,std::size_t length);
    std::string json(std::uint32_t address,unsigned length) const;
    void begin();
    void finish(Exit);
    void read(std::uint32_t,std::uint8_t,std::optional<std::uint64_t>);
    void write(std::uint32_t,std::uint8_t);
    bool matches(const Bus&,const Cpu&) const;
    unsigned fetch_depth=0;
private:
    friend void invalidate_disc_origin(Bus&,std::uint32_t,std::size_t);
    struct Tag {std::uint64_t offset=0;std::uint8_t value=0;};
    std::optional<Tag> tag(std::uint32_t) const;
    Bus* bus_=nullptr;
    Cpu* cpu_=nullptr;
    std::unordered_map<std::uint32_t,Tag> ram_;
    std::array<std::optional<Tag>,3> registers_{},saved_{};
    std::optional<Tag> last_read_;
    unsigned opcode_=256;
    std::uint16_t entry_pc_=0;
    std::uint64_t entry_irqs_=0;
    std::uint64_t last_native_=0,last_interpreted_=0;
    bool active_=false;
    std::uint64_t epoch_=0,reads_=0,writes_=0;
};
DiscOrigin* disc_origin(Bus&,Cpu&) noexcept;
void invalidate_disc_origin(Bus&,std::uint32_t,std::size_t);
namespace detail {
struct DiscOriginScope {
    DiscOrigin* observer;
    DiscOriginScope(Bus&,Cpu&);
    ~DiscOriginScope();
    void finish(Exit);
};
struct DiscOriginFetch {
    DiscOrigin* observer;
    DiscOriginFetch(Bus&,Cpu&);
    ~DiscOriginFetch();
};
}
}

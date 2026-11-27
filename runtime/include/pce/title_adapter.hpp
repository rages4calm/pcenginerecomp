#pragma once
// Deterministic, consumer-authored gameplay extensions. This is a trusted C++
// extension contract, not a sandbox. Persistent data belongs in state(), never
// mutable globals. Guest time and original retirement counters remain untouched.
#include "pce/runtime.hpp"
#include <string_view>
#include <vector>

namespace pce {
class TitleAdapterContext;
struct TitleSettingSpec {
    std::string name;
    std::int64_t min=0,max=0,default_value=0;
};
struct TitleEventSpec {
    std::string name;
    std::uint16_t pc=0;
    std::array<std::uint8_t,8> mpr{};
    std::uint8_t selector=0;
    std::vector<std::uint8_t> data;
};
struct TitleAdapterSpec {
    std::string id,manifest_sha256;
    std::uint32_t state_bytes=0;
    std::vector<TitleSettingSpec> settings;
    std::vector<TitleEventSpec> events;
    void (*after)(TitleAdapterContext&)=nullptr;
};
// Supplied by the generated consumer binding. Plain hosts need no definition.
const TitleAdapterSpec* consumer_title_adapter();

struct TitleRegisters {
    std::uint8_t a=0,x=0,y=0,p=0,sp=0;
    std::uint16_t pc=0;
    std::array<std::uint8_t,8> mpr{};
    std::uint64_t ticks=0,cycles=0;
};
struct TitleSource {
    std::uint16_t pc=0;
    std::array<std::uint8_t,8> mpr{};
    std::uint8_t selector=0,length=0;
    std::array<std::uint32_t,7> physical{};
    std::array<std::uint8_t,7> data{};
};
struct TitleAdapterStats {
    std::uint64_t matched_events=0,transactions=0,ram_bytes_changed=0,register_writes=0;
};

class TitleAdapterContext {
public:
    const TitleEventSpec& event() const noexcept;
    const TitleSource& source() const noexcept;
    const TitleRegisters& before() const noexcept;
    const TitleRegisters& after() const noexcept;
    std::uint64_t ticks() const noexcept;
    std::uint64_t frame() const noexcept;
    std::int64_t setting(std::string_view name) const;
    // A scratch copy: callback throws or any bad edit leaves live state intact.
    std::span<std::uint8_t> state() noexcept;
    std::uint8_t read_ram(std::uint32_t physical) const;
    std::uint16_t read_ram_u16(std::uint32_t physical) const;
    void write_ram(std::uint32_t physical,std::span<const std::uint8_t> expected,
                   std::span<const std::uint8_t> replacement);
    void write_ram_u8(std::uint32_t physical,std::uint8_t expected,std::uint8_t replacement);
    void write_ram_u16(std::uint32_t physical,std::uint16_t expected,std::uint16_t replacement);
    void set_a(std::uint8_t expected,std::uint8_t replacement);
    void set_x(std::uint8_t expected,std::uint8_t replacement);
    void set_y(std::uint8_t expected,std::uint8_t replacement);
    void set_p(std::uint8_t expected,std::uint8_t replacement);
private:
    struct Impl;
    Impl* impl_;
    explicit TitleAdapterContext(Impl& value):impl_(&value){}
    friend class TitleAdapterRuntime;
};

class TitleAdapterRuntime {
public:
    struct Pending {
        std::size_t event_index=static_cast<std::size_t>(-1);
        TitleSource source;
        TitleRegisters registers;
        std::uint64_t native_before=0,interpreted_before=0;
    };
    static constexpr std::size_t maximum_state_bytes=4096,maximum_checkpoint_bytes=4160;
    explicit TitleAdapterRuntime(const TitleAdapterSpec* spec=nullptr,
                                 std::string_view mode="pristine",std::string_view settings="");
    bool compiled() const noexcept;
    bool enabled() const noexcept;
    const std::string& canonical_settings() const noexcept;
    const std::string& binding_digest() const noexcept;
    const TitleAdapterStats& stats() const noexcept;
    std::span<const std::uint8_t> state() const noexcept;
    Pending before(const Bus&,const Cpu&) const;
    // No callback for zero retirements; reject counter regression/multi-retire.
    // The host must never call this from its exceptional dispatch path.
    void after(const Pending&,Bus&,Cpu&);
    std::vector<std::uint8_t> checkpoint_state() const;
    void validate_restore(std::span<const std::uint8_t>) const;
    void validate_restore(std::span<const std::uint8_t>,std::uint64_t native_steps,std::uint64_t interpreter_steps) const;
    // Only after validate_restore(), at the enclosing nonthrowing guest commit.
    void commit_restore(std::span<const std::uint8_t>) noexcept;
    std::string status_json() const;
    const std::string& last_audit_json() const noexcept;
private:
    TitleAdapterSpec spec_;
    bool compiled_=false,enabled_=false;
    std::string canonical_,binding_,last_audit_;
    std::vector<std::int64_t> settings_;
    std::vector<std::uint8_t> state_;
    std::vector<std::size_t> event_order_;
    TitleAdapterStats stats_;
    std::uint64_t last_matched_total_=0;
};
} // namespace pce

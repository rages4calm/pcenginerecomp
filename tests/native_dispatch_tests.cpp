#include "pce/runtime.hpp"
#include <iostream>
#include <limits>
#include <tuple>

static void require(bool condition, const char* message) {
    if(!condition) throw std::runtime_error(message);
}

int main() {
    try {
        pce::Bus bus;
        unsigned checks=0;
        // Fill bytes with an authored, nonzero pattern. The expected readable
        // domains are specified independently of peek's implementation.
        for(unsigned bank=0;bank<256;++bank) {
            for(const auto kind: {pce::BankKind::unmapped,pce::BankKind::ram,
                                 pce::BankKind::rom,pce::BankKind::io,pce::BankKind::bram}) {
                bus.kind[bank]=kind;
                const bool readable=kind==pce::BankKind::ram || kind==pce::BankKind::rom;
                for(unsigned offset: {0U,1U,4095U,8190U,8191U}) {
                    const auto address=bank*8192+offset;
                    const auto value=static_cast<std::uint8_t>(bank+offset+0x39);
                    (*bus.bytes)[address]=value;
                    const auto result=bus.peek(address);
                    require(result.has_value()==readable,"source domain mismatch");
                    if(readable) require(*result==value,"source byte mismatch");
                    ++checks;
                }
            }
        }
        for(unsigned address: {0x200000U,0x200001U,0x7fffffffU,
                               std::numeric_limits<std::uint32_t>::max()}) {
            require(!bus.peek(address),"out-of-range source read accepted"); ++checks;
        }

        // Exact bytes remain authoritative even if no writer updated a bank's
        // generation. Include FF, which is a valid source byte, not a miss.
        bus.kind[0x80]=pce::BankKind::ram;
        bus.generation[0x80]=19;
        constexpr unsigned address=0x100123;
        for(unsigned value=0;value<256;++value) {
            (*bus.bytes)[address]=static_cast<std::uint8_t>(value);
            require(bus.peek(address)==std::optional<std::uint8_t>{static_cast<std::uint8_t>(value)},
                    "raw changed source byte was not observed");
            require(bus.generation[0x80]==19,"source read advanced generation");
            ++checks;
        }

        // Reclassifying the very same bytes must immediately revoke source
        // access, without requiring an epoch change or servicing a device.
        bus.enable_cd_control(); bus.enable_psg(); bus.enable_joypad();
        bus.cd.bram_unlocked=true; bus.io_latch=0x5a;
        bus.cd.interrupt_active=0x41;
        bus.kind[0xf7]=pce::BankKind::bram;
        bus.kind[0xff]=pce::BankKind::io;
        const auto before=std::tuple{bus.io_latch,bus.cd.bram_unlocked,
            bus.cd.interrupt_active,bus.cd.reads,bus.psg.writes,bus.joypad.reads,
            bus.generation};
        for(unsigned offset: {0U,0x1000U,0x1803U,0x1807U,0x1fffU}) {
            require(!bus.peek(0x1fe000+offset),"MMIO became source-readable");
            require(!bus.peek(0x1ee000+offset),"BRAM became source-readable");
            ++checks;
        }
        const auto after=std::tuple{bus.io_latch,bus.cd.bram_unlocked,
            bus.cd.interrupt_active,bus.cd.reads,bus.psg.writes,bus.joypad.reads,
            bus.generation};
        require(before==after,"source inspection serviced device or mutated state");
        bus.kind[0x80]=pce::BankKind::rom;
        require(bus.peek(address)==std::optional<std::uint8_t>{0xff},"ROM source byte missing");
        bus.kind[0x80]=pce::BankKind::unmapped;
        require(!bus.peek(address),"reclassified source remained readable");
        std::cout<<"Native source guards: "<<checks+3<<" expectation groups passed\n";
    } catch(const std::exception& error) {
        std::cerr<<error.what()<<'\n'; return 1;
    }
}

// Authored gameplay example. All durable data lives in the SDK-owned state span.
#include "pce/title_adapter.hpp"
#include <limits>

namespace pce::consumer {
namespace {
std::uint64_t word(std::span<std::uint8_t> bytes,unsigned offset) {
    std::uint64_t value=0;
    for(unsigned i=0;i<8;++i)value|=std::uint64_t(bytes[offset+i])<<(8*i);
    return value;
}
void put(std::span<std::uint8_t> bytes,unsigned offset,std::uint64_t value) {
    for(unsigned i=0;i<8;++i)bytes[offset+i]=std::uint8_t(value>>(8*i));
}
void increment(std::span<std::uint8_t> bytes,unsigned offset) {
    const auto value=word(bytes,offset);
    if(value==std::numeric_limits<std::uint64_t>::max())throw Fault("Authored adapter event counter overflow");
    put(bytes,offset,value+1);
}
}

void title_adapter_after(TitleAdapterContext& context) {
    const auto state=context.state();
    if(state.size()!=48)throw Fault("Authored adapter requires its declared 48-byte state");
    const auto& name=context.event().name;
    if(name=="earned_exp" || name=="earned_gold") {
        // These events are the original LDA #earned instructions, before the
        // guest adds the earned value to its balance. Spending is not hooked.
        const auto expected=std::uint8_t(name=="earned_exp"?3:5);
        if(context.after().a!=expected)throw Fault("Authored reward input changed");
        const auto factor=context.setting(name=="earned_exp"?"exp":"gold");
        context.set_a(expected,std::uint8_t(expected*factor));
        increment(state,name=="earned_exp"?0:8);
    } else if(name=="hit") {
        // This is a synthetic duration, not a claim about any retail title.
        const auto duration=std::uint8_t(context.setting("protection")?4:2);
        context.set_a(2,duration);
        if(context.frame()>std::numeric_limits<std::uint64_t>::max()-duration-1)
            throw Fault("Authored guest-frame expiry overflow");
        // The current hit already consumed this frame's attack. The guest
        // skips the following duration VBlanks before accepting another hit.
        put(state,24,context.frame()+duration+1);
        increment(state,16);
        if(context.setting("protection"))
            context.write_ram_u8(0x1F0007,context.read_ram(0x1F0007),1);
    } else if(name=="vblank") {
        // The original guest acknowledges VBlank and increments its own frame
        // counter. No wall-clock sleep, host poll count or balance delta is used.
        put(state,32,context.frame());
        increment(state,40);
        if(context.setting("protection"))
            context.write_ram_u8(0x1F0007,context.read_ram(0x1F0007),
                                 context.frame()<word(state,24)?1:0);
    } else throw Fault("Unexpected authored source event");
}
} // namespace pce::consumer

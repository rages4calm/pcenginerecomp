#include "pce/runtime.hpp"

namespace pce {
void Bus::enable_joypad(bool japanese,bool cd) {
    joypad=Joypad{};
    joypad.enabled=true; joypad.japanese=japanese; joypad.cd=cd;
    joypad.reset(); kind[0xFF]=BankKind::io;
}
void Joypad::reset() {
    sel=true; clr=true; extra=false; selected=0;
    for(auto& pad:pads) pad.pressed=0;
    write(255); reads=0; writes=0;
}
void Joypad::set_pressed(unsigned slot,unsigned mask) {
    if(slot>=pads.size() || mask>0xFFF) throw Fault("invalid controller slot or 12-bit button snapshot");
    pads[slot].pressed=static_cast<std::uint16_t>(mask);
}
void Joypad::set_type(unsigned slot,unsigned buttons) {
    if(slot>=pads.size() || (buttons!=2 && buttons!=6)) throw Fault("only two/six-button controllers in slots 0..4 are supported");
    pads[slot].buttons=buttons;
}
std::uint8_t Joypad::read() { ++reads; return latched; }
void Joypad::write(std::uint8_t value) {
    ++writes;
    const bool previous_sel=sel, previous_clr=clr;
    sel=(value&1)!=0; clr=(value&2)!=0;
    latched=static_cast<std::uint8_t>(0x30|(japanese ? 0x40:0)|(cd ? 0:0x80));
    if(multitap) {
        if(!clr && !previous_sel && sel && selected<5) ++selected;
        if(sel && !previous_clr && clr) selected=0;
        // Beyond the fifth port, the reference returns pull-ups before
        // handling the shared six-button bank edge, even with CLR asserted.
        if(selected>=5) { latched|=15; return; }
    } else selected=0;
    if(previous_clr && !clr) extra=!extra;
    if(clr) return;
    const auto& pad=pads[selected];
    const auto released=static_cast<unsigned>(~pad.pressed);
    if(pad.buttons==6 && extra) {
        if(!sel) latched|=(released>>8)&15;
    } else latched|=(released>>(sel ? 4:0))&15;
}
} // namespace pce

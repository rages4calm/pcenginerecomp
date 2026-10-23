#include "pce/runtime.hpp"
#include <limits>
#include <sstream>
#include <iomanip>

namespace pce {
namespace {
constexpr unsigned bsy=0x80, req=0x40, msg=0x20, cd=0x10, io=8, ack_bit=2, rst=0x100;
constexpr unsigned free_phase=0, command_phase=3, data_phase=4, message_phase=6, status_phase=7;
unsigned command_length(unsigned op) {
    switch(op) {
    case 0: case 3: case 8: return 6;
    case 0xD8: case 0xD9: case 0xDA: case 0xDD: case 0xDE: return 10;
    default: return 0;
    }
}
}
void Bus::enable_cd_transport() { enable_cd_control(); cd.scsi.enabled=true; }
void CdControl::update_irq() {
    interrupt_active &= static_cast<std::uint8_t>(~0x60);
    if((scsi.signals&(bsy|io|req))==(bsy|io|req))
        interrupt_active |= (scsi.signals&cd) ? 0x20:0x40;
}
void CdControl::schedule(unsigned event,std::uint64_t delay) {
    if(delay>std::numeric_limits<std::uint64_t>::max()-scsi.master_ticks)
        throw Fault("CD transport clock overflow");
    scsi.event=event; scsi.deadline=scsi.master_ticks+delay;
}
void CdControl::phase(unsigned value) {
    if(scsi.phase==value) return; // Reselection does not discard a partial CDB.
    scsi.phase=value;
    scsi.signals &= static_cast<std::uint16_t>(~(bsy|req|msg|cd|io));
    switch(value) {
    case command_phase: scsi.signals|=bsy|cd|req; break;
    case status_phase: scsi.signals|=bsy|cd|io|req; break;
    case message_phase: scsi.signals|=bsy|cd|io|msg|req; break;
    default: break;
    }
}
void CdControl::handshake() {
    if(reset&2) {
        const auto ticks=scsi.master_ticks;
        scsi=Scsi{}; scsi.enabled=true; scsi.master_ticks=ticks; scsi.signals=rst;
        ack=false; update_irq(); return;
    }
    const bool request=(scsi.signals&req)!=0;
    if(scsi.phase==command_phase) {
        if(request && ack) {
            if(scsi.command_size==scsi.command.size()) throw Fault("CD command buffer overflow");
            scsi.command[scsi.command_size++]=scsi.latch;
            scsi.signals &= static_cast<std::uint16_t>(~req);
        } else if(!request && !ack && scsi.command_size) {
            const auto length=command_length(scsi.command[0]);
            if(!length || scsi.command_size>=length) {
                scsi.last_command=scsi.command; scsi.last_command_size=scsi.command_size;
                if(scsi.command[0]!=0) {
                    std::ostringstream message;
                    message<<"unsupported CD command $"<<std::hex<<std::uppercase<<std::setw(2)
                           <<std::setfill('0')<<unsigned(scsi.command[0])<<" (captured "
                           <<std::dec<<scsi.command_size<<" bytes; no sector/audio backend)";
                    throw Fault(message.str());
                }
                scsi.command_size=0;
                schedule(3,450000); // Reference-emulator TUR latency, not drive-ready evidence.
            } else schedule(2,3000);
        }
    } else if(scsi.phase==status_phase || scsi.phase==message_phase) {
        if(request && ack) scsi.signals &= static_cast<std::uint16_t>(~req);
        else if(!request && !ack) {
            if(scsi.phase==message_phase) schedule(5,1500);
            else if(scsi.status_pending) { scsi.status_pending=false; schedule(4,1500); }
        }
    }
    update_irq();
}
void CdControl::advance_to(std::uint64_t ticks) {
    if(!scsi.enabled) return;
    if(ticks<scsi.master_ticks) throw Fault("CPU/CD clock regression");
    // Process events at their guest timestamp, including a held ACK at REQ.
    // No host timers and no per-tick polling or unbounded response buffers.
    while(scsi.event && scsi.deadline<=ticks) {
        scsi.master_ticks=scsi.deadline;
        const auto event=scsi.event; scsi.event=0; scsi.deadline=0;
        const auto old_signals=scsi.signals;
        switch(event) {
        case 1: phase(command_phase); break;
        case 2: scsi.signals|=req; break;
        case 3: scsi.data=0; scsi.status_pending=true; phase(status_phase); break;
        case 4: phase(message_phase); break;
        case 5: phase(free_phase); break;
        default: throw Fault("invalid CD transport event");
        }
        if(old_signals!=scsi.signals) handshake();
    }
    scsi.master_ticks=ticks;
}
std::uint8_t CdControl::transport_read(unsigned port) const {
    if(port==0) return static_cast<std::uint8_t>(scsi.signals&0xF8);
    // $1808 auto-ACK is specific to DATA IN, which requires a future backend.
    // STATUS/MESSAGE reads must never consume the response themselves.
    return scsi.phase==data_phase || scsi.phase==status_phase || scsi.phase==message_phase ? scsi.data:scsi.latch;
}
void CdControl::transport_write(unsigned port,std::uint8_t value) {
    switch(port) {
    case 0: schedule(1,75000); return;
    case 1: scsi.latch=value; return;
    case 2: {
        interrupt_enable=value&0x7F;
        // A new ACK assertion while RST is held clocks another reset. Merely
        // rewriting an unchanged low ACK does not clear a newly written latch.
        if((reset&2) && (value&0x80)) { handshake(); return; }
        const bool next=(value&0x80) && !(reset&2);
        if(next==ack) return; // Only an edge, or a later REQ event, clocks a byte.
        ack=next;
        if(ack) scsi.signals|=ack_bit; else scsi.signals &= static_cast<std::uint16_t>(~ack_bit);
        handshake(); return;
    }
    case 4: {
        const bool was_reset=(reset&2)!=0;
        reset=value&15;
        if(reset&2) { interrupt_active &= 0x8F; if(!was_reset) handshake(); }
        else scsi.signals &= static_cast<std::uint16_t>(~rst);
        return;
    }
    default: throw Fault("invalid CD transport port");
    }
}
} // namespace pce

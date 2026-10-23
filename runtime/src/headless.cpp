#include "pce/runtime.hpp"
#include "pce/sector.hpp"
#include "pce/input_script.hpp"
#include <fstream>
#include <filesystem>
#include <iostream>
#include <limits>
#include <sstream>
#include <vector>

static std::uint64_t number(const char* text) {
    std::size_t end=0;
    auto value=std::stoull(text,&end,0);
    if(text[0]=='-' || text[end]!='\0') throw pce::Fault("invalid nonnegative number");
    return value;
}
int main(int argc, char** argv) {
    // Baseline developer sandbox: one contiguous payload, no settings/saves,
    // no GUI, and no implicit BIOS or hardware implementation.
    if(argc<8 || argc>30 || (argc-8)%2) {
        std::cerr << "usage: pce-headless IMAGE PHYSICAL_LOAD PC MPR_CSV MAX_STEPS MAX_TICKS native|hybrid [--bios RAW_256K_SYSTEM_CARD] [--toc PCE_TOC_DESCRIPTOR] [--disc ISO_OR_CHD] [--libchdr LIBRARY] [--joypad 2|6] [--joypad-region usa|japan] [--multitap off|on] [--buttons MASK_CSV] [--frame-out NEW_PPM_FILE] [--input-script PCE_INPUT_FILE] [--cd-unknown-status fault|gear-good]\n";
        return 2;
    }
    try {
        const char* unknown_status=nullptr;
        const char* input_path=nullptr;
        const char* bios_path=nullptr;
        const char* frame_path=nullptr;
        const char* toc_path=nullptr;
        const char* disc_path=nullptr;
        const char* chdr_path=nullptr;
        const char* pad_type=nullptr;
        const char* pad_region=nullptr;
        const char* pad_tap=nullptr;
        const char* pad_buttons=nullptr;
        for(int option=8;option<argc;option+=2) {
            const std::string name=argv[option];
            if(name=="--cd-unknown-status" && !unknown_status) unknown_status=argv[option+1];
            else if(name=="--input-script" && !input_path) input_path=argv[option+1];
            else if(name=="--bios" && !bios_path) bios_path=argv[option+1];
            else if(name=="--toc" && !toc_path) toc_path=argv[option+1];
            else if(name=="--frame-out" && !frame_path) frame_path=argv[option+1];
            else if(name=="--disc" && !disc_path) disc_path=argv[option+1];
            else if(name=="--libchdr" && !chdr_path) chdr_path=argv[option+1];
            else if(name=="--joypad" && !pad_type) pad_type=argv[option+1];
            else if(name=="--joypad-region" && !pad_region) pad_region=argv[option+1];
            else if(name=="--multitap" && !pad_tap) pad_tap=argv[option+1];
            else if(name=="--buttons" && !pad_buttons) pad_buttons=argv[option+1];
            else throw pce::Fault("unknown or duplicate optional argument");
        }
        if(frame_path && std::filesystem::exists(std::filesystem::path(std::u8string(reinterpret_cast<const char8_t*>(frame_path))))) throw pce::Fault("snapshot output exists; choose a new output path");
        if(unknown_status && std::string(unknown_status)!="fault" && std::string(unknown_status)!="gear-good") throw pce::Fault("--cd-unknown-status requires fault or gear-good");
        const auto input_events=input_path ? pce::read_input_script(input_path) : std::vector<pce::InputEvent>{};
        std::size_t input_applied=0;
        if(chdr_path && !disc_path) throw pce::Fault("--libchdr requires --disc");
        const unsigned buttons=pad_type ? static_cast<unsigned>(number(pad_type)):2;
        if(pad_type && std::string(pad_type)!="2" && std::string(pad_type)!="6") throw pce::Fault("--joypad requires 2 or 6");
        const std::string region=pad_region ? pad_region:"usa";
        if(region!="usa" && region!="japan") throw pce::Fault("--joypad-region requires usa or japan");
        const std::string tap=pad_tap ? pad_tap:"off";
        if(tap!="off" && tap!="on") throw pce::Fault("--multitap requires off or on");
        std::array<unsigned,5> pressed{};
        if(pad_buttons) {
            const std::string values=pad_buttons;
            if(values.empty() || values.back()==',') throw pce::Fault("--buttons requires one to five 12-bit masks");
            std::stringstream masks(values); std::string mask; unsigned slot=0;
            while(std::getline(masks,mask,',')) {
                const auto value=number(mask.c_str());
                if(slot==5 || value>0xFFF) throw pce::Fault("--buttons requires one to five 12-bit masks");
                pressed[slot++]=static_cast<unsigned>(value);
            }
        }
        const auto load=number(argv[2]), pc=number(argv[3]), max_steps=number(argv[5]), deadline=number(argv[6]);
        if(load>=0x200000 || pc>0xFFFF || !max_steps || max_steps>500000000) throw pce::Fault("load/PC/step limit out of range");
        const std::string tier=argv[7];
        if(tier!="native" && tier!="hybrid") throw pce::Fault("tier must be native or hybrid");
        pce::Cpu s;
        s.pc=static_cast<std::uint16_t>(pc);
        std::stringstream mprs(argv[4]); std::string item; unsigned index=0;
        while(std::getline(mprs,item,',')) {
            auto value=number(item.c_str());
            if(index>=8 || value>255) throw pce::Fault("MPR must have eight bytes");
            s.mpr[index++]=static_cast<std::uint8_t>(value);
        }
        if(index!=8) throw pce::Fault("MPR must have eight bytes");
        std::ifstream stream(argv[1],std::ios::binary|std::ios::ate);
        if(!stream) throw pce::Fault("cannot open input");
        const auto length=stream.tellg();
        if(length<=0 || static_cast<std::uint64_t>(length)>0x200000-load) throw pce::Fault("input exceeds physical address space");
        std::vector<std::uint8_t> payload(static_cast<std::size_t>(length));
        stream.seekg(0); stream.read(reinterpret_cast<char*>(payload.data()),length);
        if(!stream) throw pce::Fault("short input read");
        pce::Bus bus;
        if(bios_path) {
            std::ifstream firmware(bios_path,std::ios::binary|std::ios::ate);
            if(!firmware) throw pce::Fault("cannot open System Card ROM");
            if(firmware.tellg()!=262144) throw pce::Fault("System Card ROM must be a raw 256 KiB image");
            std::vector<std::uint8_t> rom(262144);
            firmware.seekg(0); firmware.read(reinterpret_cast<char*>(rom.data()),static_cast<std::streamsize>(rom.size()));
            if(!firmware) throw pce::Fault("short System Card ROM read");
            for(unsigned bank=0; bank<32; ++bank) bus.kind[bank]=pce::BankKind::rom;
            bus.load(0,rom.data(),rom.size());
            bus.enable_cd_transport();
            bus.enable_video();
            bus.enable_interrupts();
            bus.enable_psg();
            bus.enable_adpcm();
        }
        if(unknown_status && std::string(unknown_status)=="gear-good") {
            if(!bus.cd.scsi.enabled) bus.enable_cd_transport();
            bus.cd.reference_unknown_status=true;
        }
        if(toc_path) {
            if(!bus.cd.scsi.enabled) bus.enable_cd_transport();
            bus.cd.set_toc(pce::read_toc(toc_path));
        }
        if(disc_path) {
            if(!bus.cd.scsi.enabled) bus.enable_cd_transport();
            bus.cd.set_sector_provider(pce::open_sector_provider(disc_path,chdr_path ? chdr_path:""));
        }
        if(bios_path || toc_path || disc_path || pad_type || pad_region || pad_tap || pad_buttons || input_path) {
            bus.enable_joypad(region=="japan",bus.cd.enabled);
            bus.joypad.set_multitap(tap=="on");
            for(unsigned slot=0;slot<5;++slot) {
                bus.joypad.set_type(slot,buttons); bus.joypad.set_pressed(slot,pressed[slot]);
            }
        }
        for(unsigned bank=0x80; bank<=0x87; ++bank) bus.kind[bank]=pce::BankKind::ram;
        bus.kind[0xF8]=pce::BankKind::ram; bus.kind[0xFF]=pce::BankKind::io;
        for(std::size_t bank=load>>13; bank<=(load+payload.size()-1)>>13; ++bank) {
            if(bus.kind[bank]!=pce::BankKind::ram) throw pce::Fault("payload must reside in standard CD RAM or work RAM");
        }
        bus.load(static_cast<std::uint32_t>(load),payload.data(),payload.size());
        auto status=pce::Exit::executed;
        std::string diagnostic;
        try {
            for(std::uint64_t i=0; i<max_steps; ++i) {
                while(input_applied<input_events.size() && input_events[input_applied].ticks<=s.ticks) {
                    for(unsigned slot=0;slot<5;++slot) bus.joypad.set_pressed(slot,input_events[input_applied].buttons[slot]);
                    ++input_applied;
                }
                status=pce::step(bus,s,deadline,tier=="hybrid");
                if(status!=pce::Exit::executed) break;
            }
        } catch(const pce::Fault& error) { diagnostic=error.what(); }
        std::cout << "{\"scope\":\"headless CPU sandbox, not game boot\",\"stop\":\""
                  << (diagnostic.empty() ? (status==pce::Exit::executed ? "step_limit" : pce::exit_name(status)) : "bus_fault")
                  << "\",\"pc\":" << s.pc << ",\"a\":" << unsigned(s.a) << ",\"x\":" << unsigned(s.x)
                  << ",\"y\":" << unsigned(s.y) << ",\"sp\":" << unsigned(s.sp) << ",\"p\":" << unsigned(s.p)
                  << ",\"ticks\":" << s.ticks << ",\"cycles\":" << s.cycles << ",\"clock_divisor\":" << s.clock_divisor
                  << ",\"native_steps\":" << s.native_steps << ",\"interpreter_steps\":" << s.interpreter_steps
                  << ",\"native_block_steps\":" << s.native_block_steps << ",\"interpreter_block_steps\":" << s.interpreter_block_steps
                  << ",\"block_bytes\":" << s.block_bytes
                  << ",\"irq_entries\":" << s.irq_entries << ",\"irq_vector\":" << s.irq_vector << ",\"rti_steps\":" << s.rti_steps
                  << ",\"irq_mask\":" << unsigned(bus.irq.mask) << ",\"irq_requests\":" << unsigned(bus.irq_requests())
                  << ",\"input_events_applied\":" << input_applied
                  << ",\"guard_misses\":" << s.guard_misses << ",\"mpr_latch\":" << unsigned(s.mpr_latch) << ",\"mpr\":[";
        for(unsigned i=0; i<8; ++i) std::cout << (i ? "," : "") << unsigned(s.mpr[i]);
        std::cout << "],\"instruction_bytes\":[";
        for(unsigned i=0;i<7;++i) {
            const auto byte=bus.peek(pce::Bus::physical(s,static_cast<std::uint16_t>(s.pc+i)));
            if(i) std::cout<<',';
            if(byte) std::cout<<unsigned(*byte); else std::cout<<"null";
        }
        std::cout << "],\"cd_control\":{\"enabled\":" << (bus.cd.enabled ? "true":"false")
                  << ",\"bram_unlocked\":" << (bus.cd.bram_unlocked ? "true":"false")
                  << ",\"irq_enable\":" << unsigned(bus.cd.interrupt_enable) << ",\"irq_active\":" << unsigned(bus.cd.interrupt_active)
                  << ",\"ack\":" << (bus.cd.ack ? "true":"false") << ",\"reset\":" << unsigned(bus.cd.reset)
                  << ",\"reads\":" << bus.cd.reads << ",\"writes\":" << bus.cd.writes
                  << ",\"bram_changes\":" << bus.generation[0xF7] << "},\"scsi\":{\"enabled\":" << (bus.cd.scsi.enabled ? "true":"false")
                  << ",\"profile\":\"clocked control, TOC and read-only sector streaming; deterministic 1x access\",\"phase\":" << bus.cd.scsi.phase
                  << ",\"signals\":" << bus.cd.scsi.signals << ",\"host_latch\":" << unsigned(bus.cd.scsi.latch)
                  << ",\"drive_data\":" << unsigned(bus.cd.scsi.data) << ",\"master_ticks\":" << bus.cd.scsi.master_ticks
                  << ",\"event\":" << bus.cd.scsi.event << ",\"deadline\":" << bus.cd.scsi.deadline
                  << ",\"auto_ack_deadline\":" << bus.cd.scsi.auto_ack_deadline
                  << ",\"response_length\":" << bus.cd.scsi.response_size << ",\"response_index\":" << bus.cd.scsi.response_index
                  << ",\"toc_replies\":" << bus.cd.toc_replies << ",\"data_bytes_acked\":" << bus.cd.data_bytes_acked
                  << ",\"provider_attached\":" << (bus.cd.provider ? "true":"false")
                  << ",\"read_active\":" << (bus.cd.scsi.read_active ? "true":"false")
                  << ",\"load_lba\":" << bus.cd.scsi.load_lba << ",\"load_remaining\":" << bus.cd.scsi.load_remaining
                  << ",\"load_deadline\":" << bus.cd.scsi.load_deadline << ",\"current_lba\":" << bus.cd.scsi.current_lba
                  << ",\"read_commands\":" << bus.cd.read_commands << ",\"sectors_read\":" << bus.cd.sectors_read
                  << ",\"read_retries\":" << bus.cd.read_retries << ",\"read_errors\":" << bus.cd.read_errors
                  << ",\"reference_unknown_status\":" << (bus.cd.reference_unknown_status ? "true":"false") << ",\"unknown_commands\":" << bus.cd.unknown_commands
                  << ",\"cd_audio_state\":" << bus.cd.audio.state << ",\"cd_audio_lba\":" << bus.cd.audio.current_lba << ",\"cd_audio_commands\":" << bus.cd.audio.commands
                  << ",\"command_size\":" << bus.cd.scsi.command_size << ",\"last_command\":[";
        for(unsigned i=0;i<bus.cd.scsi.last_command_size;++i) std::cout<<(i?",":"")<<unsigned(bus.cd.scsi.last_command[i]);
        std::cout << "]},\"joypad\":{\"enabled\":" << (bus.joypad.enabled ? "true":"false")
                  << ",\"profile\":\"Gear-reference latched two/six-button protocol\",\"japanese\":" << (bus.joypad.japanese ? "true":"false")
                  << ",\"cd\":" << (bus.joypad.cd ? "true":"false") << ",\"multitap\":" << (bus.joypad.multitap ? "true":"false")
                  << ",\"sel\":" << (bus.joypad.sel ? "true":"false") << ",\"clr\":" << (bus.joypad.clr ? "true":"false")
                  << ",\"extra\":" << (bus.joypad.extra ? "true":"false") << ",\"selected\":" << bus.joypad.selected
                  << ",\"latched\":" << unsigned(bus.joypad.latched) << ",\"reads\":" << bus.joypad.reads << ",\"writes\":" << bus.joypad.writes << ",\"pads\":[";
        for(unsigned slot=0;slot<5;++slot) std::cout<<(slot?",":"")<<"{\"buttons\":"<<bus.joypad.pads[slot].buttons<<",\"pressed\":"<<bus.joypad.pads[slot].pressed<<"}";
        std::cout << "]},\"toc\":{\"attached\":" << (bus.cd.toc ? "true":"false")
                  << ",\"image_sha256\":\"" << (bus.cd.toc ? bus.cd.toc->image_sha256:"")
                  << "\",\"track_count\":" << (bus.cd.toc ? bus.cd.toc->track_count:0)
                  << ",\"leadout_lba\":" << (bus.cd.toc ? bus.cd.toc->leadout_lba:0)
                  << "},\"vdc\":{\"enabled\":" << (bus.vdc.enabled ? "true":"false")
                  << ",\"profile\":\"functional synchronous single VDC\",\"selected\":" << unsigned(bus.vdc.selected)
                  << ",\"mawr\":" << bus.vdc.reg[0] << ",\"marr\":" << bus.vdc.reg[1] << ",\"read_buffer\":" << bus.vdc.read_buffer
                  << ",\"cr\":" << bus.vdc.reg[5] << ",\"reads\":" << bus.vdc.reads << ",\"writes\":" << bus.vdc.writes
                  << ",\"psg_writes\":" << bus.psg.writes << ",\"adpcm_reads\":" << bus.adpcm.reads << ",\"adpcm_writes\":" << bus.adpcm.writes << ",\"adpcm_dma_bytes\":" << bus.adpcm.dma_bytes
                  << ",\"vce_writes\":" << bus.vce.writes << ",\"dma_words\":" << bus.vdc.dma_words << ",\"satb_words\":" << bus.vdc.satb_words
                  << ",\"vram_changes\":" << bus.vdc.vram_changes << "},\"raster\":{\"enabled\":" << (bus.vdc.raster.enabled ? "true":"false")
                  << ",\"master_ticks\":" << bus.vdc.raster.master_ticks << ",\"hclock\":" << bus.vdc.raster.hclock
                  << ",\"line\":" << bus.vdc.raster.line << ",\"dot\":" << bus.vdc.raster.dot << ",\"frames\":" << bus.vdc.raster.frames
                  << ",\"divider\":" << bus.vdc.raster.divider << ",\"total_lines\":" << bus.vdc.raster.total_lines
                  << ",\"vblank_events\":" << bus.vdc.raster.vblank_events << ",\"rcr_events\":" << bus.vdc.raster.rcr_events
                  << ",\"status\":" << unsigned(bus.vdc.status) << ",\"irq1\":" << (bus.vdc.irq1 ? "true":"false") << "}}\n";
        if(frame_path) pce::write_ppm(pce::render_snapshot(bus.vdc,bus.vce,bus.vdc.satb),frame_path);
        if(!diagnostic.empty()) std::cerr << diagnostic << '\n';
        return diagnostic.empty() && (status==pce::Exit::executed || status==pce::Exit::budget) ? 0 : 3;
    } catch(const std::exception& error) { std::cerr << error.what() << '\n'; return 2; }
}

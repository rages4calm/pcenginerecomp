#include "pce/runtime.hpp"
#include "pce/sector.hpp"
#include "pce/cartridge.hpp"
#include "pce/input_script.hpp"
#include "pce/dev_server.hpp"
#include "pce/code_capture.hpp"
#include "pce/wav.hpp"
#include <fstream>
#include <filesystem>
#include <iostream>
#include <limits>
#include <sstream>
#include <vector>
#include <chrono>
#include <thread>
#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif
#ifdef PCE_DESKTOP
#include "pce/desktop.hpp"
#include "pce/audio_host.hpp"
#endif

static std::uint64_t number(const char* text) {
    std::size_t end=0;
    auto value=std::stoull(text,&end,0);
    if(text[0]=='-' || text[end]!='\0') throw pce::Fault("invalid nonnegative number");
    return value;
}
static bool same_path(const std::filesystem::path& first,const std::filesystem::path& second) {
    const auto a=std::filesystem::weakly_canonical(first),b=std::filesystem::weakly_canonical(second);
#ifdef _WIN32
    const auto& x=a.native();const auto& y=b.native();
    return CompareStringOrdinal(x.data(),static_cast<int>(x.size()),y.data(),static_cast<int>(y.size()),TRUE)==CSTR_EQUAL;
#else
    return a==b;
#endif
}
int main(int argc, char** argv) {
    // Baseline developer sandbox: one contiguous payload, no settings/saves,
    // no implicit BIOS or hardware implementation. Optional desktop uses the
    // same loader/dispatcher and volatile state as this headless sandbox.
    const bool system_card_boot=argc>1 && std::string(argv[1])=="--system-card-reset";
    const bool hucard_boot=argc>1 && std::string(argv[1])=="--hucard-reset";
    const bool reset_boot=system_card_boot || hucard_boot;
    const int option_start=reset_boot ? 7:8;
    if(argc<option_start || argc>option_start+64 || (argc-option_start)%2) {
        std::cerr << "usage: pce-headless IMAGE PHYSICAL_LOAD PC MPR_CSV MAX_STEPS MAX_TICKS native|hybrid [--bios RAW_256K_SYSTEM_CARD] [--bram RAW_2048_IMAGE] [--toc PCE_TOC_DESCRIPTOR] [--disc ISO_CHD_OR_CUE] [--libchdr LIBRARY] [--joypad 2|6] [--joypad-region usa|japan] [--multitap off|on] [--buttons MASK_CSV] [--frame-out NEW_PPM_FILE] [--input-script PCE_INPUT_FILE] [--cd-unknown-status fault|gear-good] [--video-output snapshot|continuous] [--dev-port 0..65535] [--dev-start-paused on|off] [--dev-memory-write on|off] [--wall-seconds 1..600] [--code-capture NEW_PRIVATE_JSON] [--capture-limit 1..65536] [--code-capture-start-frame N] [--audio-output on|off] [--audio-profile raw|filtered] [--audio-rate 44100|48000] [--audio-timing gear|legacy] [--audio-out NEW_WAV] [--audio-frames 1..RATE*120]\nMAX_STEPS: 1..20000000000; tick deadlines remain active.\nDesktop only: [--window-scale 1..6] [--unthrottled on|off] [--hidden on|off] [--window-capture NEW_PPM]\n";
        std::cerr << "reset boot: pce-headless --system-card-reset standard|super RAW_256K_SYSTEM_CARD MAX_STEPS MAX_TICKS native|hybrid [same options except --bios] [--arcade-card duo (super only)]\n";
        std::cerr << "HuCard boot: pce-headless --hucard-reset base|sf2|populous RAW_ROM MAX_STEPS MAX_TICKS native|hybrid [--rom-header none|copier512] [--rom-encoding linear|bit-reversed] [ordinary non-CD options]\n";
        return 2;
    }
    try {
        const char* video_mode=nullptr;
        const char* dev_port=nullptr;
        const char* dev_start_paused=nullptr;
        const char* dev_memory_write=nullptr;
        const char* wall_seconds=nullptr;
        const char* code_capture_path=nullptr;
        const char* capture_limit=nullptr;
        const char* capture_start_frame=nullptr;
        const char* audio_mode=nullptr;
        const char* audio_path=nullptr;
        const char* audio_frames=nullptr;
        const char* audio_profile=nullptr;
        const char* audio_rate=nullptr;
        const char* audio_timing=nullptr;
#ifdef PCE_DESKTOP
        const char* window_scale=nullptr;
        const char* unthrottled=nullptr;
        const char* hidden=nullptr;
        const char* capture_path=nullptr;

#endif
        const char* unknown_status=nullptr;
        const char* input_path=nullptr;
        const char* bios_path=system_card_boot ? argv[3]:nullptr;
        const char* cartridge_path=hucard_boot ? argv[3]:nullptr;
        const char* payload_path=reset_boot ? nullptr:argv[1];
        const char* rom_header=nullptr;
        const char* rom_encoding=nullptr;
        const char* arcade_card=nullptr;
        pce::SystemCardProfile system_card=pce::SystemCardProfile::none;
        if(system_card_boot) {
            const std::string selected=argv[2];
            if(selected=="standard") system_card=pce::SystemCardProfile::standard;
            else if(selected=="super") system_card=pce::SystemCardProfile::super;
            else throw pce::Fault("System Card reset requires standard or super profile");
        }
        pce::HuCardProfile hucard_profile=pce::HuCardProfile::none;
        const char* hucard_name=hucard_boot ? argv[2]:"none";
        if(hucard_boot) {
            const std::string selected=hucard_name;
            if(selected=="base") hucard_profile=pce::HuCardProfile::base;
            else if(selected=="sf2") hucard_profile=pce::HuCardProfile::sf2;
            else if(selected=="populous") hucard_profile=pce::HuCardProfile::populous;
            else throw pce::Fault("HuCard reset requires an explicit base, sf2 or populous profile");
        }
        const char* bram_path=nullptr;
        const char* frame_path=nullptr;
        const char* toc_path=nullptr;
        const char* disc_path=nullptr;
        const char* chdr_path=nullptr;
        const char* pad_type=nullptr;
        const char* pad_region=nullptr;
        const char* pad_tap=nullptr;
        const char* pad_buttons=nullptr;
        for(int option=option_start;option<argc;option+=2) {
            const std::string name=argv[option];
            if(name=="--video-output" && !video_mode) video_mode=argv[option+1];
            else if(name=="--audio-output" && !audio_mode) audio_mode=argv[option+1];
            else if(name=="--audio-out" && !audio_path) audio_path=argv[option+1];
            else if(name=="--audio-frames" && !audio_frames) audio_frames=argv[option+1];
            else if(name=="--audio-profile" && !audio_profile) audio_profile=argv[option+1];
            else if(name=="--audio-rate" && !audio_rate) audio_rate=argv[option+1];
            else if(name=="--audio-timing" && !audio_timing) audio_timing=argv[option+1];
            else if(name=="--dev-port" && !dev_port) dev_port=argv[option+1];
            else if(name=="--dev-start-paused" && !dev_start_paused) dev_start_paused=argv[option+1];
            else if(name=="--dev-memory-write" && !dev_memory_write) dev_memory_write=argv[option+1];
            else if(name=="--code-capture" && !code_capture_path) code_capture_path=argv[option+1];
            else if(name=="--capture-limit" && !capture_limit) capture_limit=argv[option+1];
            else if(name=="--code-capture-start-frame" && !capture_start_frame) capture_start_frame=argv[option+1];
            else if(name=="--wall-seconds" && !wall_seconds) wall_seconds=argv[option+1];
#ifdef PCE_DESKTOP
            else if(name=="--window-scale" && !window_scale) window_scale=argv[option+1];
            else if(name=="--unthrottled" && !unthrottled) unthrottled=argv[option+1];
            else if(name=="--hidden" && !hidden) hidden=argv[option+1];
            else if(name=="--window-capture" && !capture_path) capture_path=argv[option+1];

#endif
            else if(name=="--cd-unknown-status" && !unknown_status) unknown_status=argv[option+1];
            else if(name=="--input-script" && !input_path) input_path=argv[option+1];
            else if(name=="--bios" && !bios_path) bios_path=argv[option+1];
            else if(name=="--bram" && !bram_path) bram_path=argv[option+1];
            else if(name=="--toc" && !toc_path) toc_path=argv[option+1];
            else if(name=="--frame-out" && !frame_path) frame_path=argv[option+1];
            else if(name=="--disc" && !disc_path) disc_path=argv[option+1];
            else if(name=="--libchdr" && !chdr_path) chdr_path=argv[option+1];
            else if(name=="--rom-header" && !rom_header) rom_header=argv[option+1];
            else if(name=="--rom-encoding" && !rom_encoding) rom_encoding=argv[option+1];
            else if(name=="--arcade-card" && !arcade_card) arcade_card=argv[option+1];
            else if(name=="--joypad" && !pad_type) pad_type=argv[option+1];
            else if(name=="--joypad-region" && !pad_region) pad_region=argv[option+1];
            else if(name=="--multitap" && !pad_tap) pad_tap=argv[option+1];
            else if(name=="--buttons" && !pad_buttons) pad_buttons=argv[option+1];
            else throw pce::Fault("unknown or duplicate optional argument");
        }
        if(!hucard_boot && (rom_header || rom_encoding))
            throw pce::Fault("ROM header/encoding options require --hucard-reset");
        if(arcade_card && (!system_card_boot || system_card!=pce::SystemCardProfile::super ||
                           std::string(arcade_card)!="duo"))
            throw pce::Fault("--arcade-card duo requires explicit Super System Card reset boot");
        if(rom_header && std::string(rom_header)!="none" && std::string(rom_header)!="copier512")
            throw pce::Fault("--rom-header requires none or copier512");
        if(rom_encoding && std::string(rom_encoding)!="linear" && std::string(rom_encoding)!="bit-reversed")
            throw pce::Fault("--rom-encoding requires linear or bit-reversed");
        if(hucard_boot && (bios_path || bram_path || toc_path || disc_path || chdr_path ||
           (unknown_status && std::string(unknown_status)!="fault")))
            throw pce::Fault("Base HuCard reset does not accept CD, firmware or BRAM inputs/profiles");
        if(frame_path && std::filesystem::exists(std::filesystem::path(std::u8string(reinterpret_cast<const char8_t*>(frame_path))))) throw pce::Fault("snapshot output exists; choose a new output path");
        if(audio_mode && std::string(audio_mode)!="on" && std::string(audio_mode)!="off")throw pce::Fault("--audio-output requires on or off");
        const bool audio_enabled=audio_mode ? std::string(audio_mode)=="on":
#ifdef PCE_DESKTOP
            true;
#else
            audio_path!=nullptr;
#endif
        if(audio_profile && std::string(audio_profile)!="raw" && std::string(audio_profile)!="filtered")
            throw pce::Fault("--audio-profile requires raw or filtered");
        const auto profile=audio_profile && std::string(audio_profile)=="filtered" ? pce::AudioProfile::filtered:pce::AudioProfile::raw;
        if(audio_rate && std::string(audio_rate)!="44100" && std::string(audio_rate)!="48000")
            throw pce::Fault("--audio-rate requires 44100 or 48000");
        const unsigned output_rate=audio_rate && std::string(audio_rate)=="48000" ? 48000:44100;
        if(audio_timing && std::string(audio_timing)!="gear" && std::string(audio_timing)!="legacy")
            throw pce::Fault("--audio-timing requires gear or legacy");
        const auto timing=audio_timing && std::string(audio_timing)=="legacy" ? pce::AudioTiming::legacy:pce::AudioTiming::gear;
        if((audio_profile || audio_rate || audio_timing) && !audio_enabled)throw pce::Fault("--audio-profile, --audio-rate and --audio-timing require enabled audio");
        if(profile==pce::AudioProfile::raw && output_rate!=44100)throw pce::Fault("raw audio requires 44100 Hz");
        if(audio_frames && !audio_path)throw pce::Fault("--audio-frames requires --audio-out");
        const auto capture_frames=audio_frames ? number(audio_frames):output_rate*30;
        if(audio_path && (!audio_enabled || capture_frames<1 || capture_frames>output_rate*120))throw pce::Fault("WAV capture requires enabled audio and 1..120 seconds of output frames");
        if(audio_path) {
            const auto path=std::filesystem::path(std::u8string(reinterpret_cast<const char8_t*>(audio_path)));
            if(std::filesystem::exists(path) || std::filesystem::is_symlink(path))throw pce::Fault("WAV capture exists; choose a new file");
            for(const auto* other:{frame_path,code_capture_path,
#ifdef PCE_DESKTOP
                capture_path,
#endif
                bios_path,bram_path,toc_path,disc_path,chdr_path,input_path,payload_path,cartridge_path}) {
                if(other && same_path(path,std::filesystem::path(std::u8string(reinterpret_cast<const char8_t*>(other)))))throw pce::Fault("WAV capture aliases another input or output");
            }
        }
        if(unknown_status && std::string(unknown_status)!="fault" && std::string(unknown_status)!="gear-good") throw pce::Fault("--cd-unknown-status requires fault or gear-good");
        const std::string output_mode=video_mode ? video_mode:
#ifdef PCE_DESKTOP
            "continuous";
#else
            (dev_port ? "continuous":"snapshot");
#endif
        const auto network_port=dev_port ? number(dev_port):0;
        if(network_port>65535) throw pce::Fault("--dev-port requires 0..65535");
        if(dev_start_paused && (!dev_port || (std::string(dev_start_paused)!="on" && std::string(dev_start_paused)!="off"))) throw pce::Fault("--dev-start-paused requires --dev-port and on or off");
        if(dev_memory_write && (!dev_port || (std::string(dev_memory_write)!="on" && std::string(dev_memory_write)!="off"))) throw pce::Fault("--dev-memory-write requires --dev-port and on or off");
        const bool memory_write_enabled=dev_memory_write && std::string(dev_memory_write)=="on";
        std::uint64_t memory_write_requests=0, memory_bytes_changed=0;
        if(dev_port && output_mode!="continuous") throw pce::Fault("development server requires continuous video output");
        const auto wall_limit=wall_seconds ? number(wall_seconds):0;
        if(wall_seconds && (wall_limit<1 || wall_limit>600)) throw pce::Fault("--wall-seconds requires 1..600");
        if(output_mode!="snapshot" && output_mode!="continuous") throw pce::Fault("--video-output requires snapshot or continuous");
#ifdef PCE_DESKTOP
        if(output_mode!="continuous") throw pce::Fault("desktop requires continuous video output");
        const auto scale=window_scale ? number(window_scale):3;
        if(scale<1 || scale>6) throw pce::Fault("--window-scale requires 1..6");
        for(const auto* toggle:{unthrottled,hidden})
            if(toggle && std::string(toggle)!="on" && std::string(toggle)!="off") throw pce::Fault("desktop toggle requires on or off");
        const bool fast_forward=unthrottled && std::string(unthrottled)=="on";
        if(capture_path && std::filesystem::exists(std::filesystem::path(std::u8string(reinterpret_cast<const char8_t*>(capture_path))))) throw pce::Fault("desktop capture output exists; choose a new output path");
        if(capture_path && frame_path && same_path(std::filesystem::path(capture_path),std::filesystem::path(frame_path))) throw pce::Fault("frame and desktop captures require different output paths");
#endif
        const auto observation_limit=capture_limit ? number(capture_limit):16384;
        const auto observation_start=capture_start_frame ? number(capture_start_frame):0;
        if(capture_start_frame && (!code_capture_path || output_mode!="continuous"))
            throw pce::Fault("--code-capture-start-frame requires --code-capture and continuous video");
        if(capture_limit && !code_capture_path) throw pce::Fault("--capture-limit requires --code-capture");
        if(observation_limit<1 || observation_limit>65536) throw pce::Fault("--capture-limit requires 1..65536");
        if(code_capture_path) {
            const auto path=std::filesystem::path(std::u8string(reinterpret_cast<const char8_t*>(code_capture_path)));
            if(std::filesystem::exists(path) || std::filesystem::is_symlink(path)) throw pce::Fault("code capture exists; choose a new output file");
            for(const auto* other:{frame_path,
#ifdef PCE_DESKTOP
                capture_path,
#endif
                bios_path,bram_path,toc_path,disc_path,chdr_path,input_path,payload_path,cartridge_path}) {
                if(other && same_path(path,std::filesystem::path(std::u8string(reinterpret_cast<const char8_t*>(other)))))
                    throw pce::Fault("code capture aliases another input or output");
            }
        }
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
        const auto load=reset_boot ? 0:number(argv[2]), pc=reset_boot ? 0:number(argv[3]);
        const auto max_steps=number(argv[reset_boot ? 4:5]), deadline=number(argv[reset_boot ? 5:6]);
        if(load>=0x200000 || pc>0xFFFF || !max_steps || max_steps>20000000000ULL) throw pce::Fault("load/PC/step limit out of range");
        const std::string tier=argv[reset_boot ? 6:7];
        if(tier!="native" && tier!="hybrid") throw pce::Fault("tier must be native or hybrid");
        pce::Cpu s;
        std::vector<std::uint8_t> payload;
        if(!reset_boot) {
            s.pc=static_cast<std::uint16_t>(pc);
            std::stringstream mprs(argv[4]); std::string item; unsigned index=0;
            while(std::getline(mprs,item,',')) {
                auto value=number(item.c_str());
                if(index>=8 || value>255) throw pce::Fault("MPR must have eight bytes");
                s.mpr[index++]=static_cast<std::uint8_t>(value);
            }
            if(index!=8) throw pce::Fault("MPR must have eight bytes");
            std::ifstream stream(payload_path,std::ios::binary|std::ios::ate);
            if(!stream) throw pce::Fault("cannot open input");
            const auto length=stream.tellg();
            if(length<=0 || static_cast<std::uint64_t>(length)>0x200000-load) throw pce::Fault("input exceeds physical address space");
            payload.resize(static_cast<std::size_t>(length));
            stream.seekg(0); stream.read(reinterpret_cast<char*>(payload.data()),length);
            if(!stream) throw pce::Fault("short input read");
        }
        pce::Bus bus;
        std::size_t hucard_rom_bytes=0;
        if(hucard_boot) {
            const auto path=std::filesystem::path(std::u8string(reinterpret_cast<const char8_t*>(cartridge_path)));
            std::ifstream cartridge(path,std::ios::binary|std::ios::ate);
            if(!cartridge) throw pce::Fault("cannot open HuCard ROM");
            const auto length=cartridge.tellg();
            const std::uint64_t maximum=hucard_profile==pce::HuCardProfile::sf2 ? 0x280000:0x100000;
            if(length<=0 || static_cast<std::uint64_t>(length)>maximum+512)
                throw pce::Fault("HuCard input exceeds the bounded raw ROM size");
            std::vector<std::uint8_t> raw(static_cast<std::size_t>(length));
            cartridge.seekg(0);cartridge.read(reinterpret_cast<char*>(raw.data()),length);
            if(!cartridge || cartridge.peek()!=std::ifstream::traits_type::eof())
                throw pce::Fault("HuCard input changed size during read");
            const auto decoded=pce::decode_hucard(raw,
                rom_header && std::string(rom_header)=="copier512" ? pce::HuCardHeader::copier512:pce::HuCardHeader::none,
                rom_encoding && std::string(rom_encoding)=="bit-reversed" ? pce::HuCardEncoding::bit_reversed:pce::HuCardEncoding::linear,hucard_profile);
            hucard_rom_bytes=decoded.rom.size();
            bus.configure_hucard(hucard_profile,decoded.rom);
            if(output_mode=="continuous")bus.enable_continuous_video();else bus.enable_video();
            bus.enable_interrupts();bus.enable_psg();
        }
        if(bios_path) {
            std::ifstream firmware(bios_path,std::ios::binary|std::ios::ate);
            if(!firmware) throw pce::Fault("cannot open System Card ROM");
            if(firmware.tellg()!=262144) throw pce::Fault("System Card ROM must be a raw 256 KiB image");
            std::vector<std::uint8_t> rom(262144);
            firmware.seekg(0); firmware.read(reinterpret_cast<char*>(rom.data()),static_cast<std::streamsize>(rom.size()));
            if(!firmware) throw pce::Fault("short System Card ROM read");
            if(system_card_boot) {
                bus.configure_system_card(system_card,rom);
                if(arcade_card) bus.configure_arcade_card_duo();
            }
            else {
                for(unsigned bank=0; bank<32; ++bank) bus.kind[bank]=pce::BankKind::rom;
                bus.load(0,rom.data(),rom.size());
            }
            bus.enable_cd_transport();
            if(output_mode=="continuous") bus.enable_continuous_video(); else bus.enable_video();
            bus.enable_interrupts();
            bus.enable_psg();
            bus.enable_adpcm();
        }
        if(output_mode=="continuous" && !bios_path && !hucard_boot) bus.enable_continuous_video();
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
        if(bram_path) {
            const auto path=std::filesystem::path(std::u8string(reinterpret_cast<const char8_t*>(bram_path)));
            std::ifstream bram(path,std::ios::binary|std::ios::ate);
            if(!bram) throw pce::Fault("cannot open initial BRAM image");
            if(bram.tellg()!=2048) throw pce::Fault("initial BRAM image must be exactly 2048 raw bytes");
            std::array<std::uint8_t,2048> initial{};
            bram.seekg(0); bram.read(reinterpret_cast<char*>(initial.data()),static_cast<std::streamsize>(initial.size()));
            if(!bram) throw pce::Fault("short initial BRAM image read");
            if(bram.peek()!=std::ifstream::traits_type::eof()) throw pce::Fault("initial BRAM image changed size while reading");
            if(!bus.cd.enabled) bus.enable_cd_control();
            bus.load(0xF7u<<13,initial.data(),initial.size());
        }
        if(hucard_boot || bios_path || bram_path || toc_path || disc_path || pad_type || pad_region || pad_tap || pad_buttons || input_path || output_mode=="continuous") {
            bus.enable_joypad(region=="japan",bus.cd.enabled);
            bus.joypad.set_multitap(tap=="on");
            for(unsigned slot=0;slot<5;++slot) {
                bus.joypad.set_type(slot,buttons); bus.joypad.set_pressed(slot,pressed[slot]);
            }
        }
        if(reset_boot) bus.power_on_cpu(s);
        else {
            for(unsigned bank=0x80; bank<=0x87; ++bank) bus.kind[bank]=pce::BankKind::ram;
            bus.kind[0xF8]=pce::BankKind::ram; bus.kind[0xFF]=pce::BankKind::io;
            bus.enable_work_ram_mirrors();
            for(std::size_t bank=load>>13; bank<=(load+payload.size()-1)>>13; ++bank) {
                if(bus.kind[bank]!=pce::BankKind::ram) throw pce::Fault("payload must reside in standard CD RAM or work RAM");
            }
            bus.load(static_cast<std::uint32_t>(load),payload.data(),payload.size());
        }
        const auto initial_cpu=s;
        auto boot_json=[&] {
            std::ostringstream json;
            json<<"{\"mode\":\""<<(hucard_boot ? "hucard-reset":system_card_boot ? "system-card-reset":"snapshot")<<'"';
            if(reset_boot) {
                json<<",\"profile\":\""<<(hucard_boot ? hucard_name:system_card==pce::SystemCardProfile::super ? "super":"standard")
                    <<"\",\"initialization\":\"gear-deterministic-zero-v1\",\"vector_physical\":8190"
                    <<",\"pc\":"<<initial_cpu.pc<<",\"a\":"<<unsigned(initial_cpu.a)<<",\"x\":"<<unsigned(initial_cpu.x)
                    <<",\"y\":"<<unsigned(initial_cpu.y)<<",\"sp\":"<<unsigned(initial_cpu.sp)<<",\"p\":"<<unsigned(initial_cpu.p)
                    <<",\"clock_divisor\":"<<initial_cpu.clock_divisor<<",\"ticks\":0,\"cycles\":0,\"mpr\":[";
                for(unsigned i=0;i<8;++i)json<<(i ? ",":"")<<unsigned(initial_cpu.mpr[i]);
                json<<']';
                if(hucard_boot) {
                    json<<",\"header\":\""<<(rom_header ? rom_header:"none")
                        <<"\",\"encoding\":\""<<(rom_encoding ? rom_encoding:"linear")
                        <<"\",\"rom_bytes\":"<<hucard_rom_bytes<<",\"cd\":false";
                    if(hucard_profile==pce::HuCardProfile::sf2) json<<",\"mapper_latch\":0";
                    if(hucard_profile==pce::HuCardProfile::populous) json<<",\"cartridge_ram_bytes\":32768";
                }
                else {
                    json<<",\"bram\":\""<<(bram_path ? "explicit-image":"blank-unformatted")<<"\"";
                    if(arcade_card) json<<",\"arcade_card\":\"duo\"";
                }
            }
            json<<'}';return json.str();
        };
        const auto write_cartridge_status=[&](std::ostream& json) {
            json<<"\"cartridge\":{\"profile\":\""<<hucard_name
                <<"\",\"mapper_latch\":"<<unsigned(bus.hucard_mapper_latch)
                <<",\"rom_bytes\":"<<hucard_rom_bytes
                <<",\"ram_bytes\":"<<(hucard_profile==pce::HuCardProfile::populous ? 32768:0)<<'}';
        };
        const auto write_arcade_status=[&](std::ostream& json) {
            const auto& card=*bus.arcade_card;
            json<<"\"arcade_card\":{\"profile\":\"duo\",\"ram_bytes\":2097152"
                <<",\"shift_register\":"<<card.shift_register
                <<",\"shift_amount\":"<<unsigned(card.shift_amount)
                <<",\"rotate_amount\":"<<unsigned(card.rotate_amount)
                <<",\"reads\":"<<card.reads<<",\"writes\":"<<card.writes<<",\"ports\":[";
            for(unsigned i=0;i<card.ports.size();++i) {
                const auto& port=card.ports[i];
                json<<(i ? ",":"")<<"{\"base\":"<<port.base<<",\"offset\":"<<port.offset
                    <<",\"increment\":"<<port.increment<<",\"control\":"<<unsigned(port.control)
                    <<",\"effective_address\":"<<card.effective_address(i)<<'}';
            }
            json<<"]}";
        };
        if(audio_enabled)bus.enable_audio_output(profile,output_rate,timing);
        std::unique_ptr<pce::WaveWriter> wave;
        if(audio_path)wave=std::make_unique<pce::WaveWriter>(audio_path,static_cast<std::uint32_t>(capture_frames),output_rate);
        std::unique_ptr<pce::CodeCapture> code_capture;
        if(code_capture_path) code_capture=std::make_unique<pce::CodeCapture>(std::filesystem::path(std::u8string(reinterpret_cast<const char8_t*>(code_capture_path))),static_cast<std::size_t>(observation_limit));
        bool capture_started=false;
        std::uint64_t capture_actual_frame=0,capture_actual_ticks=0,capture_native_before=0,capture_interpreted_before=0;
        auto status=pce::Exit::executed;
        std::string diagnostic;
        const auto wall_start=std::chrono::steady_clock::now();
        bool host_quit=false,wall_expired=false;
        std::uint64_t next_poll=0;
#ifdef PCE_DESKTOP
        pce::DesktopHost host({"PC Engine Recomp - development host",static_cast<unsigned>(scale),hidden && std::string(hidden)=="on",!fast_forward});
        std::unique_ptr<pce::AudioHost> audio_device;
        if(audio_enabled) {
            try{audio_device=std::make_unique<pce::AudioHost>(output_rate);}
            catch(const std::exception& error) {
                if(audio_mode)throw;
                std::cerr<<"PCE_AUDIO_DEVICE_UNAVAILABLE="<<error.what()<<'\n';
            }
        }
        std::uint64_t last_presented=0;
#endif
        std::unique_ptr<pce::DevServer> dev;
        if(dev_port) {
            dev=std::make_unique<pce::DevServer>(static_cast<std::uint16_t>(network_port),dev_start_paused && std::string(dev_start_paused)=="on");
            std::cerr<<"PCE_DEV_PORT="<<dev->port()<<'\n';
        }
        const auto apply_buttons=[&] {
            for(unsigned slot=0;slot<5;++slot) bus.joypad.set_pressed(slot,pressed[slot]
                | (dev ? dev->input_masks()[slot]:0)
#ifdef PCE_DESKTOP
                | (slot==0 ? host.buttons():0)
#endif
            );
        };
        const auto paused=[&] {return (dev && dev->paused(bus.vdc.video.sequence()))
#ifdef PCE_DESKTOP
            || host.paused()
#endif
            ;};
        const auto drain_audio=[&] {
            if(!bus.pcm.enabled)return;
            const auto samples=bus.pcm.drain();
            if(wave)wave->write(samples);
#ifdef PCE_DESKTOP
            if(audio_device) {
                audio_device->set_paused(fast_forward || paused());
                for(std::size_t offset=0;offset<samples.size();) {
                    const auto count=std::min<std::size_t>(samples.size()-offset,4410*2);
                    audio_device->submit(std::span<const std::int16_t>(samples.data()+offset,count));offset+=count;
                }
            }
#endif
        };
        const auto write_pcm_status=[&](std::ostream& json) {
            const auto& p=bus.pcm;
            json<<"\"audio_output\":{\"enabled\":"<<(p.enabled?"true":"false")
                <<",\"sample_rate\":"<<p.output_rate()<<",\"channels\":2,\"frames\":"<<p.frames
                <<",\"psg_nonzero\":"<<p.psg_nonzero<<",\"adpcm_nonzero\":"<<p.adpcm_nonzero
                <<",\"cdda_nonzero\":"<<p.cdda_nonzero<<",\"mixed_nonzero\":"<<p.mixed_nonzero
                <<",\"peak\":"<<p.peak<<",\"pcm_hash\":"<<p.pcm_hash
                <<",\"discarded_frames\":"<<p.discarded_frames<<",\"wav_frames\":"<<(wave?wave->frames():0)
                <<",\"wav_truncated\":"<<(wave&&wave->truncated()?"true":"false");
            if(p.timing()==pce::AudioTiming::gear)json<<",\"timing\":\"gear-v1\"";
            if(p.profile()==pce::AudioProfile::filtered) {
                const auto processing=p.processing_stats();
                json<<",\"processing\":{\"profile\":\"filtered-v1\",\"source_rate\":44100"
                    <<",\"source_frames\":"<<processing.source_frames<<",\"raw_pcm_hash\":"<<processing.raw_pcm_hash
                    <<",\"raw_peak\":"<<processing.raw_peak<<",\"raw_mixed_nonzero\":"<<processing.raw_mixed_nonzero
                    <<",\"resampler\":\""<<(p.output_rate()==48000?"sinc64-q30-v1":"identity")
                    <<"\",\"latency_source_frames\":"<<processing.latency_source_frames<<",\"tail_flushed\":false}";
            }
#ifdef PCE_DESKTOP
            json<<",\"device_open\":"<<(audio_device?"true":"false")
                <<",\"fast_forward_muted\":"<<(fast_forward?"true":"false");
            if(audio_device) {
                const auto& a=audio_device->stats();
                json<<",\"host\":{\"submitted_frames\":"<<a.submitted_frames<<",\"dropped_frames\":"<<a.dropped_frames
                    <<",\"clears\":"<<a.clears<<",\"pauses\":"<<a.pauses<<",\"queued_frames\":"<<a.queued_frames
                    <<",\"peak_queue_frames\":"<<a.peak_queue_frames;
                if(p.profile()==pce::AudioProfile::filtered)
                    json<<",\"input_rate\":"<<a.input_rate<<",\"device_rate\":"<<a.device_rate
                        <<",\"device_channels\":"<<a.device_channels<<",\"device_format\":"<<a.device_format;
                json<<'}';
            }
#endif
            json<<'}';
        };
        // Stored state only: diagnostics must not acknowledge ports or advance clocks.
        const auto write_unknown_status=[&](std::ostream& json) {
            json<<"\"cd_unknown\":{\"accepted_responses\":"<<bus.cd.unknown_commands<<",\"opcodes\":[";
            bool first=true;
            for(unsigned i=0;i<256;++i) if(bus.cd.unknown_opcodes[i]) {
                json<<(first ? "":",")<<"{\"opcode\":"<<i<<",\"attempts\":"<<bus.cd.unknown_opcodes[i]<<'}';
                first=false;
            }
            json<<"],\"last_command\":[";
            for(unsigned i=0;i<bus.cd.last_unknown_size;++i)
                json<<(i ? ",":"")<<unsigned(bus.cd.last_unknown_command[i]);
            json<<"],\"origin\":";
            const auto& origin=bus.cd.last_unknown_origin;
            if(!origin.valid) json<<"null";
            else {
                json<<"{\"pc\":"<<origin.pc<<",\"ticks\":"<<origin.ticks<<",\"mpr\":[";
                for(unsigned i=0;i<8;++i) json<<(i ? ",":"")<<unsigned(origin.mpr[i]);
                json<<"],\"physical_pc\":"<<((unsigned(origin.mpr[origin.pc>>13])<<13)|(origin.pc&8191))
                    <<",\"fetch\":[";
                for(unsigned i=0;i<7;++i) {
                    if(i) json<<',';
                    if(origin.readable&(1u<<i)) json<<unsigned(origin.fetch[i]);else json<<"null";
                }
                json<<"]}";
            }
            json<<'}';
        };
        const auto write_audio_status=[&](std::ostream& json) {
            const auto& audio=bus.cd.audio;
            const auto& adpcm=bus.adpcm;
            json<<"\"cd_audio\":{\"enabled\":"<<(bus.cd.audio_enabled ? "true":"false")
                <<",\"state\":"<<audio.state<<",\"stop_mode\":"<<audio.stop_mode
                <<",\"start_lba\":"<<audio.start_lba<<",\"current_lba\":"<<audio.current_lba
                <<",\"stop_lba\":"<<audio.stop_lba<<",\"seek_start_lba\":"<<audio.seek_start_lba
                <<",\"deadline\":"<<audio.deadline<<",\"seek_deadline\":"<<audio.seek_deadline
                <<",\"sector_deadline\":"<<audio.sector_deadline<<",\"playback_deadline\":"<<audio.playback_deadline
                <<",\"sectors_played\":"<<audio.sectors_played<<",\"commands\":"<<audio.commands
                <<",\"sector_fraction\":"<<audio.sector_fraction<<",\"fader\":"<<unsigned(audio.fader)
                <<",\"fade_start\":"<<audio.fade_start<<",\"fade_duration\":"<<audio.fade_duration
                <<"},\"adpcm\":{\"enabled\":"<<(adpcm.enabled ? "true":"false")
                <<",\"playing\":"<<(adpcm.playing ? "true":"false")
                <<",\"play_pending\":"<<(adpcm.play_pending ? "true":"false")
                <<",\"nibble\":"<<(adpcm.nibble ? "true":"false")
                <<",\"end_irq\":"<<(adpcm.end_irq ? "true":"false")
                <<",\"half_irq\":"<<(adpcm.half_irq ? "true":"false")
                <<",\"control\":"<<unsigned(adpcm.control)<<",\"dma\":"<<unsigned(adpcm.dma)
                <<",\"sample_rate\":"<<unsigned(adpcm.sample_rate)<<",\"last_nibble\":"<<unsigned(adpcm.last_nibble)
                <<",\"address\":"<<adpcm.address<<",\"read_address\":"<<adpcm.read_address
                <<",\"write_address\":"<<adpcm.write_address<<",\"length\":"<<adpcm.length
                <<",\"master_ticks\":"<<adpcm.master_ticks<<",\"read_deadline\":"<<adpcm.read_deadline
                <<",\"write_deadline\":"<<adpcm.write_deadline<<",\"dma_deadline\":"<<adpcm.dma_deadline
                <<",\"sample_phase\":"<<adpcm.sample_phase<<",\"samples\":"<<adpcm.samples
                <<",\"reads\":"<<adpcm.reads<<",\"writes\":"<<adpcm.writes<<",\"dma_bytes\":"<<adpcm.dma_bytes<<'}';
            if(bus.pcm.enabled){json<<',';write_pcm_status(json);}
        };
        const auto pump=[&] {
#ifdef PCE_DESKTOP
            if(!host.poll()) host_quit=true;
#endif
            if(dev) {
                pce::DevSnapshot snapshot;
                snapshot.frame=bus.vdc.video.sequence();snapshot.ticks=s.ticks;
                snapshot.frame_ticks=bus.vdc.video.completed_ticks();
#ifdef PCE_DESKTOP
                snapshot.local_paused=host.paused();
#endif
                snapshot.read_memory=[&](std::uint32_t address,std::uint32_t count) {
                    if(!count || count>256 || address>=0x200000 || count>0x200000-address) throw pce::Fault("debug memory range out of bounds");
                    for(std::uint32_t i=0;i<count;++i) {
                        const auto kind=bus.kind[(address+i)>>13];
                        if(kind!=pce::BankKind::ram && kind!=pce::BankKind::rom) throw pce::Fault("debug memory reads require RAM or ROM; MMIO/BRAM/unmapped rejected");
                    }
                    std::vector<std::uint8_t> result;
                    result.reserve(count);
                    for(std::uint32_t i=0;i<count;++i) result.push_back(*bus.peek(address+i));
                    return result;
                };
                if(memory_write_enabled) snapshot.write_memory=[&](std::uint32_t address,const std::vector<std::uint8_t>& data,const std::vector<std::uint8_t>& expected) {
                    if(data.empty() || data.size()>256 || data.size()!=expected.size() || address>=0x200000 || data.size()>0x200000-address) throw pce::Fault("debug memory range out of bounds");
                    std::array<std::uint64_t,256> changes{};
                    std::uint64_t changed=0;
                    // Preflight the complete compare-and-write. Rejected requests
                    // cannot partially edit RAM, generations, counters or MMIO.
                    for(std::size_t i=0;i<data.size();++i) {
                        const auto pa=address+i;
                        if(bus.kind[pa>>13]!=pce::BankKind::ram) throw pce::Fault("debug memory writes require RAM; ROM/MMIO/BRAM/unmapped rejected");
                        const auto backing=bus.backing_address(static_cast<std::uint32_t>(pa));
                        if((*bus.bytes)[backing]!=expected[i]) throw pce::Fault("debug memory expected bytes mismatch");
                        if((*bus.bytes)[backing]!=data[i]) {
                            ++changed;
                            if(bus.work_ram_mirrors && (backing>>13)==0xF8)
                                for(unsigned alias=0xF8;alias<=0xFB;++alias) ++changes[alias];
                            else if(bus.hucard_profile==pce::HuCardProfile::populous && pa>=0x80000 && pa<0xC0000)
                                for(unsigned alias=0x40+(unsigned(pa>>13)&3);alias<0x60;alias+=4) ++changes[alias];
                            else ++changes[pa>>13];
                        }
                    }
                    if(memory_write_requests==std::numeric_limits<std::uint64_t>::max() || changed>std::numeric_limits<std::uint64_t>::max()-memory_bytes_changed) throw pce::Fault("debug memory counter overflow");
                    for(unsigned bank=0;bank<256;++bank)
                        if(changes[bank]>std::numeric_limits<std::uint64_t>::max()-bus.generation[bank]) throw pce::Fault("debug memory generation overflow");
                    for(std::size_t i=0;i<data.size();++i)
                        (*bus.bytes)[bus.backing_address(static_cast<std::uint32_t>(address+i))]=data[i];
                    for(unsigned bank=0;bank<256;++bank) bus.generation[bank]+=changes[bank];
                    ++memory_write_requests; memory_bytes_changed+=changed;
                };
                snapshot.status=[&] {
                    std::ostringstream json;
                    json<<'{';
                    if(reset_boot)json<<"\"boot\":"<<boot_json()<<',';
                    if(hucard_boot && hucard_profile!=pce::HuCardProfile::base) {write_cartridge_status(json);json<<',';}
                    if(bus.arcade_card) {write_arcade_status(json);json<<',';}
                    json<<"\"debug_memory\":{\"write_enabled\":"<<(memory_write_enabled ? "true":"false")
                        <<",\"write_requests\":"<<memory_write_requests<<",\"bytes_changed\":"<<memory_bytes_changed
                        <<"},\"pc\":"<<s.pc<<",\"native_steps\":"<<s.native_steps<<",\"interpreter_steps\":"<<s.interpreter_steps
                        <<",\"irq_entries\":"<<s.irq_entries<<",\"rti_steps\":"<<s.rti_steps<<",\"sectors_read\":"<<bus.cd.sectors_read
                        <<",\"read_errors\":"<<bus.cd.read_errors<<",\"unknown_commands\":"<<bus.cd.unknown_commands
                        <<",\"adpcm_dma_bytes\":"<<bus.adpcm.dma_bytes<<",\"buttons\":[";
                    for(unsigned slot=0;slot<5;++slot) json<<(slot ? ",":"")<<bus.joypad.pads[slot].pressed;
                    json<<"],\"cpu\":{\"a\":"<<unsigned(s.a)<<",\"x\":"<<unsigned(s.x)<<",\"y\":"<<unsigned(s.y)
                        <<",\"sp\":"<<unsigned(s.sp)<<",\"p\":"<<unsigned(s.p)<<",\"clock_divisor\":"<<s.clock_divisor
                        <<",\"mpr_latch\":"<<unsigned(s.mpr_latch)<<",\"irq_sampled\":"<<unsigned(s.irq_sampled)
                        <<",\"irq_vector\":"<<s.irq_vector<<",\"mpr\":[";
                    for(unsigned i=0;i<8;++i) json<<(i ? ",":"")<<unsigned(s.mpr[i]);
                    json<<"],\"physical_pc\":"<<pce::Bus::physical(s,s.pc)<<",\"instruction_bytes\":[";
                    for(unsigned i=0;i<7;++i) {
                        const auto byte=bus.peek(pce::Bus::physical(s,static_cast<std::uint16_t>(s.pc+i)));
                        if(i) json<<',';
                        if(byte) json<<unsigned(*byte);else json<<"null";
                    }
                    json<<"],\"instruction_physical\":[";
                    for(unsigned i=0;i<7;++i) json<<(i ? ",":"")<<pce::Bus::physical(s,static_cast<std::uint16_t>(s.pc+i));
                    json<<"],\"instruction_generations\":[";
                    for(unsigned i=0;i<7;++i) json<<(i ? ",":"")<<bus.generation[pce::Bus::physical(s,static_cast<std::uint16_t>(s.pc+i))>>13];
                    json<<"]},\"cd_control\":{\"enabled\":"<<(bus.cd.enabled ? "true":"false")
                        <<",\"bram_seeded\":"<<(bram_path ? "true":"false")
                        <<",\"irq_enable\":"<<unsigned(bus.cd.interrupt_enable)<<",\"irq_active\":"<<unsigned(bus.cd.interrupt_active)
                        <<",\"ack\":"<<(bus.cd.ack ? "true":"false")<<",\"reset\":"<<unsigned(bus.cd.reset)
                        <<",\"reads\":"<<bus.cd.reads<<",\"writes\":"<<bus.cd.writes
                        <<"},\"scsi\":{\"enabled\":"<<(bus.cd.scsi.enabled ? "true":"false")
                        <<",\"phase\":"<<bus.cd.scsi.phase<<",\"signals\":"<<bus.cd.scsi.signals
                        <<",\"status_pending\":"<<(bus.cd.scsi.status_pending ? "true":"false")
                        <<",\"host_latch\":"<<unsigned(bus.cd.scsi.latch)<<",\"drive_data\":"<<unsigned(bus.cd.scsi.data)
                        <<",\"master_ticks\":"<<bus.cd.scsi.master_ticks<<",\"event\":"<<bus.cd.scsi.event
                        <<",\"deadline\":"<<bus.cd.scsi.deadline<<",\"auto_ack_deadline\":"<<bus.cd.scsi.auto_ack_deadline
                        <<",\"response_length\":"<<bus.cd.scsi.response_size<<",\"response_index\":"<<bus.cd.scsi.response_index
                        <<",\"data_bytes_acked\":"<<bus.cd.data_bytes_acked<<",\"toc_replies\":"<<bus.cd.toc_replies
                        <<",\"provider_attached\":"<<(bus.cd.provider ? "true":"false")
                        <<",\"read_active\":"<<(bus.cd.scsi.read_active ? "true":"false")
                        <<",\"load_lba\":"<<bus.cd.scsi.load_lba<<",\"load_remaining\":"<<bus.cd.scsi.load_remaining
                        <<",\"load_deadline\":"<<bus.cd.scsi.load_deadline<<",\"current_lba\":"<<bus.cd.scsi.current_lba
                        <<",\"read_commands\":"<<bus.cd.read_commands<<",\"read_retries\":"<<bus.cd.read_retries
                        <<",\"command_size\":"<<bus.cd.scsi.command_size<<",\"last_command\":[";
                    for(unsigned i=0;i<bus.cd.scsi.last_command_size && i<bus.cd.scsi.last_command.size();++i)
                        json<<(i ? ",":"")<<unsigned(bus.cd.scsi.last_command[i]);
                    json<<"]},";
                    write_unknown_status(json);json<<',';write_audio_status(json);
                    json<<",\"vdc\":{\"enabled\":"<<(bus.vdc.enabled ? "true":"false")
                        <<",\"status\":"<<unsigned(bus.vdc.status)<<",\"irq1\":"<<(bus.vdc.irq1 ? "true":"false")
                        <<",\"selected\":"<<unsigned(bus.vdc.selected)<<",\"registers\":[";
                    for(unsigned i=0;i<bus.vdc.reg.size();++i) json<<(i ? ",":"")<<bus.vdc.reg[i];
                    json<<"],\"satb\":[";
                    for(unsigned i=0;i<bus.vdc.satb.size();++i) json<<(i ? ",":"")<<bus.vdc.satb[i];
                    json<<"],\"vram_changes\":"<<bus.vdc.vram_changes<<",\"reads\":"<<bus.vdc.reads
                        <<",\"writes\":"<<bus.vdc.writes<<",\"satb_pending\":"<<bus.vdc.satb_pending
                        <<",\"vram_dma_pending\":"<<bus.vdc.vram_dma_pending
                        <<"},\"raster\":{\"enabled\":"<<(bus.vdc.raster.enabled ? "true":"false")
                        <<",\"master_ticks\":"<<bus.vdc.raster.master_ticks<<",\"line\":"<<bus.vdc.raster.line
                        <<",\"dot\":"<<bus.vdc.raster.dot<<",\"hclock\":"<<bus.vdc.raster.hclock
                        <<",\"frames\":"<<bus.vdc.raster.frames<<",\"vblank_events\":"<<bus.vdc.raster.vblank_events
                        <<",\"rcr_events\":"<<bus.vdc.raster.rcr_events<<",\"h_state\":"<<bus.vdc.raster.h_state
                        <<",\"v_state\":"<<bus.vdc.raster.v_state<<",\"raster_line\":"<<bus.vdc.raster.raster_line
                        <<"},\"interrupts\":{\"enabled\":"<<(bus.irq.enabled ? "true":"false")
                        <<",\"mask\":"<<unsigned(bus.irq.mask)<<",\"external\":"<<unsigned(bus.irq.external)
                        <<",\"timer_pending\":"<<(bus.irq.timer_pending ? "true":"false")
                        <<",\"timer_counter\":"<<unsigned(bus.irq.timer_counter)<<",\"timer_deadline\":"<<bus.irq.timer_deadline
                        <<"}}";return json.str();
                };
                snapshot.capture=[&](bool present) {
                    if(!bus.vdc.video.sequence()) throw pce::Fault("no completed video frame to capture");
                    if(!present) return bus.vdc.video.completed();
#ifdef PCE_DESKTOP
                    return host.readback();
#else
                    throw pce::Fault("SDL presentation is unavailable in the headless runner");
#endif
                };
                dev->poll(snapshot);
                if(dev->quit_requested()) host_quit=true;
            }
            apply_buttons();
            drain_audio();
            if(wall_limit && std::chrono::steady_clock::now()-wall_start>=std::chrono::seconds(wall_limit)) wall_expired=true;
        };
        try {
            for(std::uint64_t i=0; i<max_steps; ++i) {
                if(s.ticks>=next_poll && (dev || wall_limit || audio_enabled
#ifdef PCE_DESKTOP
                    || true
#endif
                )) {pump();next_poll=s.ticks+20000;}
#ifdef PCE_DESKTOP
                if(paused()) host.reset_pacing();
#endif
                while(paused() && !host_quit && !wall_expired) {
                    pump();
                    std::this_thread::sleep_for(std::chrono::milliseconds(1));
                }
                if(host_quit || wall_expired) break;
                while(input_applied<input_events.size() && input_events[input_applied].ticks<=s.ticks) {
                    for(unsigned slot=0;slot<5;++slot) pressed[slot]=input_events[input_applied].buttons[slot];
                    apply_buttons();++input_applied;
                }
                if(code_capture && (!capture_start_frame || bus.vdc.video.sequence()>=observation_start)) {
                    if(!capture_started) {
                        capture_started=true;capture_actual_frame=bus.vdc.video.sequence();capture_actual_ticks=s.ticks;
                        capture_native_before=s.native_steps;capture_interpreted_before=s.interpreter_steps;
                    }
                    const auto pending=code_capture->before(bus,s);
                    try {status=pce::step(bus,s,deadline,tier=="hybrid");}
                    catch(...) {code_capture->after(pending,s);throw;}
                    code_capture->after(pending,s);
                } else status=pce::step(bus,s,deadline,tier=="hybrid");
#ifdef PCE_DESKTOP
                if(bus.vdc.video.sequence()!=last_presented) {
                    host.present(bus.vdc.video.completed());
                    last_presented=bus.vdc.video.sequence();
                    host.pace(bus.vdc.video.completed_ticks());
                }
#endif
                if(status!=pce::Exit::executed) break;
            }
        } catch(const pce::Fault& error) { diagnostic=error.what(); }
        if(code_capture) code_capture->finish();
        drain_audio();
        if(wave)wave->finish();
        std::ostringstream report;
        const char* stop=diagnostic.empty() ? (status==pce::Exit::executed ? "step_limit":pce::exit_name(status)):"bus_fault";
        if(host_quit) stop=dev && dev->quit_requested() ? "dev_quit":"window_closed";
        else if(wall_expired) stop="wall_limit";
        report << "{\"scope\":\"" << (hucard_boot ?
            (hucard_profile==pce::HuCardProfile::base ?
            "Base HuCard reset-vector boot; deterministic reference initialization; not hardware power-on certification":
            "Enhanced HuCard reset-vector boot; deterministic reference initialization; not hardware power-on certification"):system_card_boot ?
            "System Card reset-vector boot; deterministic reference initialization; not hardware power-on certification":
            "IPL-entry CPU/device sandbox; not authentic reset or game certification") << "\",";
        if(reset_boot)report<<"\"boot\":"<<boot_json()<<',';
        if(hucard_boot && hucard_profile!=pce::HuCardProfile::base) {write_cartridge_status(report);report<<',';}
        if(bus.arcade_card) {write_arcade_status(report);report<<',';}
        report << "\"stop\":\"" << stop
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
        for(unsigned i=0; i<8; ++i) report << (i ? "," : "") << unsigned(s.mpr[i]);
        report << "],\"instruction_bytes\":[";
        for(unsigned i=0;i<7;++i) {
            const auto byte=bus.peek(pce::Bus::physical(s,static_cast<std::uint16_t>(s.pc+i)));
            if(i) report<<',';
            if(byte) report<<unsigned(*byte); else report<<"null";
        }
        report << "],\"cd_control\":{\"enabled\":" << (bus.cd.enabled ? "true":"false")
                  << ",\"bram_seeded\":" << (bram_path ? "true":"false")
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
        for(unsigned i=0;i<bus.cd.scsi.last_command_size;++i) report<<(i?",":"")<<unsigned(bus.cd.scsi.last_command[i]);
        report << "]},";
        write_unknown_status(report);report<<',';write_audio_status(report);
        if(capture_start_frame) {
            report<<",\"code_capture_window\":{\"requested_start_frame\":"<<observation_start
                  <<",\"started\":"<<(capture_started?"true":"false");
            if(capture_started)
                report<<",\"actual_start_frame\":"<<capture_actual_frame<<",\"actual_start_ticks\":"<<capture_actual_ticks
                      <<",\"native_steps_before\":"<<capture_native_before<<",\"interpreter_steps_before\":"<<capture_interpreted_before;
            else report<<",\"actual_start_frame\":null,\"actual_start_ticks\":null,\"native_steps_before\":null,\"interpreter_steps_before\":null";
            report<<'}';
        }
        report << ",\"joypad\":{\"enabled\":" << (bus.joypad.enabled ? "true":"false")
                  << ",\"profile\":\"Gear-reference latched two/six-button protocol\",\"japanese\":" << (bus.joypad.japanese ? "true":"false")
                  << ",\"cd\":" << (bus.joypad.cd ? "true":"false") << ",\"multitap\":" << (bus.joypad.multitap ? "true":"false")
                  << ",\"sel\":" << (bus.joypad.sel ? "true":"false") << ",\"clr\":" << (bus.joypad.clr ? "true":"false")
                  << ",\"extra\":" << (bus.joypad.extra ? "true":"false") << ",\"selected\":" << bus.joypad.selected
                  << ",\"latched\":" << unsigned(bus.joypad.latched) << ",\"reads\":" << bus.joypad.reads << ",\"writes\":" << bus.joypad.writes << ",\"pads\":[";
        for(unsigned slot=0;slot<5;++slot) report<<(slot?",":"")<<"{\"buttons\":"<<bus.joypad.pads[slot].buttons<<",\"pressed\":"<<bus.joypad.pads[slot].pressed<<"}";
        report << "]},\"toc\":{\"attached\":" << (bus.cd.toc ? "true":"false")
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
                  << ",\"status\":" << unsigned(bus.vdc.status) << ",\"irq1\":" << (bus.vdc.irq1 ? "true":"false") << "},\"video_output\":{\"continuous\":" << (output_mode=="continuous" ? "true":"false")
                  << ",\"frames\":" << bus.vdc.video.sequence() << ",\"completed_ticks\":" << bus.vdc.video.completed_ticks()
                  << ",\"lines\":" << bus.vdc.video.lines_rendered() << ",\"pixels\":" << bus.vdc.video.pixels_rendered()
                  << ",\"width\":" << bus.vdc.video.completed().width << ",\"height\":" << bus.vdc.video.completed().height
#ifdef PCE_DESKTOP
                  << "},\"desktop\":{\"presented\":" << host.stats().presented << ",\"polls\":" << host.stats().polls
                  << ",\"focus_losses\":" << host.stats().focus_losses << ",\"gamepad_connections\":" << host.stats().gamepad_connections
                  << ",\"resize_events\":" << host.stats().resize_events << ",\"pacing_resets\":" << host.stats().pacing_resets
                  << ",\"keyboard_events\":" << host.stats().keyboard_events << ",\"gamepad_events\":" << host.stats().gamepad_events
                  << ",\"input_pulses\":" << host.stats().input_pulses
                  << ",\"unmapped_key_down\":" << host.stats().unmapped_key_down << ",\"last_unmapped_scancode\":" << host.stats().last_unmapped_scancode
#endif
                  << "},\"development\":{\"enabled\":" << (dev ? "true":"false") << ",\"port\":" << (dev ? dev->port():0)
                  << ",\"memory_write_enabled\":" << (memory_write_enabled ? "true":"false")
                  << ",\"memory_write_requests\":" << memory_write_requests << ",\"memory_bytes_changed\":" << memory_bytes_changed
                  << "}}\n";
        if(frame_path && output_mode=="continuous" && !bus.vdc.video.sequence()) throw pce::Fault("no completed video frame to capture");
        if(frame_path) pce::write_ppm(output_mode=="continuous" ? bus.vdc.video.completed():pce::render_snapshot(bus.vdc,bus.vce,bus.vdc.satb),frame_path);
#ifdef PCE_DESKTOP
        if(capture_path) host.capture(capture_path);
#endif
        std::cout << report.str();
        if(!diagnostic.empty()) std::cerr << diagnostic << '\n';
        return diagnostic.empty() && (status==pce::Exit::executed || status==pce::Exit::budget) ? 0 : 3;
    } catch(const std::exception& error) { std::cerr << error.what() << '\n'; return 2; }
}

// Host-seeded authored state coverage, distinct from the guest-only IRQ oracle.
#include "pce/checkpoint.hpp"
#include "pce/checkpoint_file.hpp"
#include "pce/sector.hpp"
#include <algorithm>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>

namespace {
unsigned checks=0;
void require(bool value,const char* why) {++checks;if(!value)throw std::runtime_error(why);}
class AuthoredDisc final:public pce::SectorProvider {
    pce::CdToc geometry_;
public:
    AuthoredDisc() {geometry_.track_count=2;geometry_.leadout_lba=12;geometry_.tracks[0]={0,4};geometry_.tracks[1]={4,0};geometry_.image_sha256=std::string(64,'b');}
    pce::Sector read(std::uint32_t lba) override {pce::Sector result{};for(unsigned i=0;i<result.size();++i)result[i]=std::uint8_t(lba*37+i*11);return result;}
    bool audio_playable(std::uint32_t lba)const override{return lba>=4&&lba<12;}
    pce::AudioSector read_audio(std::uint32_t lba) override {pce::AudioSector result{};for(unsigned i=0;i<588;++i){result[i*2]=std::int16_t(lba*600+i);result[i*2+1]=std::int16_t(-int(lba*600+i));}return result;}
    const pce::CdToc& toc()const override{return geometry_;}
};
struct Machine {pce::Bus bus;pce::Cpu cpu;};
void reg(pce::Vdc& v,unsigned index,unsigned value) {v.write(0,std::uint8_t(index));v.write(2,std::uint8_t(value));v.write(3,std::uint8_t(value>>8));}
std::unique_ptr<Machine> configured(pce::AudioProfile profile,unsigned rate,pce::AudioTiming timing) {
    auto m=std::make_unique<Machine>();auto& b=m->bus;
    std::vector<std::uint8_t> rom(262144,0xEA);rom[0x1FFE]=0;rom[0x1FFF]=0xE0;
    b.configure_system_card(pce::SystemCardProfile::super,rom);b.configure_arcade_card_duo(0x39);
    b.enable_cd_transport();b.cd.audio_enabled=true;b.cd.set_sector_provider(std::make_shared<AuthoredDisc>());
    b.enable_continuous_video();b.enable_interrupts();b.enable_joypad(false,true);b.joypad.multitap=true;b.joypad.pads[2].buttons=6;
    b.enable_psg();b.enable_adpcm();b.enable_audio_output(profile,rate,timing);b.power_on_cpu(m->cpu,0,0);
    return m;
}
void seed(Machine& m) {
    auto& b=m.bus;auto& c=m.cpu;c.mpr={255,248,128,129,130,131,132,0};c.mpr_latch=0xA7;c.a=0x63;c.x=0x87;c.y=0x29;c.sp=0xFD;c.p=pce::I|pce::D|pce::T;
    b.io_latch=0x7B;
    for(unsigned i=0;i<8192;++i)(*b.bytes)[0x1F0000+i]=std::uint8_t(i*19+5);
    for(unsigned i=0;i<32768;++i)(*b.vdc.vram)[i]=std::uint16_t(i*29+0x84A5);
    for(unsigned i=0;i<512;++i)b.vce.palette[i]=std::uint16_t(i);
    reg(b.vdc,5,0xC8);reg(b.vdc,6,0x45);reg(b.vdc,7,0x49);reg(b.vdc,8,0x27);
    b.psg.synthesis_enabled=true;b.psg.main_volume=0xFF;
    for(unsigned i=0;i<6;++i) {auto& ch=b.psg.channels[i];ch.frequency=std::uint16_t(53+i*37);ch.control=0x9F;ch.balance=0xFF;
        for(unsigned j=0;j<32;++j)ch.waveform[j]=std::uint8_t((j*7+i*3)&31);}
    b.psg.channels[4].noise=0x87;b.psg.lfo_frequency=3;b.psg.lfo_control=0;
    for(unsigned i=0;i<b.adpcm.ram.size();++i)b.adpcm.ram[i]=std::uint8_t(i*23+7);
    b.adpcm.write(8,0x83);b.adpcm.write(9,0x51);b.adpcm.write(13,0x10);b.adpcm.write(13,0);
    b.adpcm.write(14,0xD);b.adpcm.write(13,0x20,&b.cd);
    auto& a=b.cd.audio;a.state=0;a.start_lba=a.current_lba=4;a.stop_lba=10;a.sector_deadline=286363;a.sector_fraction=48;a.reschedule();
    b.cd.write_fader(8);
    b.joypad.pads[0].pressed=0x9;b.joypad.pads[2].pressed=0x535;b.joypad.write(0);b.joypad.write(1);
    b.arcade_card->ports[2]={0x123456,0x87,0x319,0x19};b.arcade_card->write_data(2,0xD9);
    b.arcade_card->shift_register=0xAB7F913C;b.arcade_card->shift_amount=3;b.arcade_card->rotate_amount=7;
    b.write(c,0xC00,2);b.write(c,0xC01,1);b.write(c,0x1402,0);
    // Warm both source caches, partially completed RGB back buffer, queue and
    // filtered resampler. These clocks are deliberately host-seeded fixture work.
    b.clock_cpu(c,18003);
    b.cd.audio.latch_sample(c.ticks);
    reg(b.vdc,1,0x391);b.clock_cpu(c,10);
    // A real partially consumed bounded DATA IN response with pending automatic
    // ACK; the source cache and drive DAC above remain independently active.
    auto& s=b.cd.scsi;s.phase=4;s.signals=0x8A;s.response_size=2048;s.response_index=17;s.data=0xA4;s.read_active=true;
    s.current_lba=1;s.load_lba=2;s.load_remaining=2;s.load_deadline=c.ticks+900;
    for(unsigned i=0;i<s.response.size();++i)s.response[i]=std::uint8_t(i*11+3);
    s.auto_ack_deadline=c.ticks+15;b.cd.ack=true;
    b.adpcm.write(10,0x6D,&b.cd);(void)b.adpcm.read(10);
    b.cd.interrupt_enable=0x3C;b.cd.interrupt_active|=0x20;
    reg(b.vdc,0,0x278);reg(b.vdc,2,0xB57E);(void)b.vdc.read(3);
    b.vdc.satb_pending=41;b.vdc.vram_dma_pending=31;b.vdc.dma_source=0x190;b.vdc.dma_dest=0x370;
    require(b.vdc.pending_vram_read&&b.vdc.pending_vram_write,"Fixture must retain both active CPU VRAM requests");
    b.irq.external=2;b.sample_interrupt(c);c.irq_sampled=3;
    require(b.pcm.queued_frames()>64&&(b.pcm.profile()==pce::AudioProfile::raw||b.pcm.processing_stats().source_frames>64),"Fixture must have PCM/FIR history");
    require(b.adpcm.playing&&b.cd.audio.sample_frames>0,"Fixture must have active source decoders");
}
void continuation(Machine& a,Machine& b) {
    require(a.bus.pcm.drain()==b.bus.pcm.drain(),"Imported pending PCM queue differs");
    for(unsigned cycles:{1u,4u,7u,31u,257u,997u,4097u,11999u,100001u}) {
        a.bus.clock_cpu(a.cpu,cycles);b.bus.clock_cpu(b.cpu,cycles);
        require(a.bus.pcm.drain()==b.bus.pcm.drain(),"Continued signed PCM differs");
        require(a.bus.vdc.video.completed().rgb==b.bus.vdc.video.completed().rgb,"Continued raw guest RGB differs");
        require(pce::encode_checkpoint(a.bus,a.cpu)==pce::encode_checkpoint(b.bus,b.cpu),"Full canonical continued state differs");
    }
}
void audio_device_matrix() {
    for(auto profile:{pce::AudioProfile::raw,pce::AudioProfile::filtered})for(unsigned rate:{44100u,48000u})for(auto timing:{pce::AudioTiming::gear,pce::AudioTiming::legacy}) {
        if(profile==pce::AudioProfile::raw&&rate!=44100)continue;
        auto a=configured(profile,rate,timing);seed(*a);const auto saved=pce::encode_checkpoint(a->bus,a->cpu);
        require(saved==pce::encode_checkpoint(a->bus,a->cpu),"Saving changes state");
        auto b=configured(profile,rate,timing);const auto* provider=b->bus.cd.provider.get();pce::restore_checkpoint(b->bus,b->cpu,saved);
        require(b->bus.cd.provider.get()==provider&&b->bus.cd.provider.get()!=a->bus.cd.provider.get(),"Restore copied a foreign provider pointer");
        require(saved==pce::encode_checkpoint(b->bus,b->cpu),"Device state is not canonical after restore");
        continuation(*a,*b);
        auto invalid=saved;invalid.pop_back();const auto before=pce::encode_checkpoint(b->bus,b->cpu);bool rejected=false;
        try{pce::restore_checkpoint(b->bus,b->cpu,invalid);}catch(const std::exception&){rejected=true;}
        require(rejected&&before==pce::encode_checkpoint(b->bus,b->cpu),"Truncated load mutated live state");
    }
}
void mapper_matrix() {
    for(auto profile:{pce::HuCardProfile::base,pce::HuCardProfile::populous,pce::HuCardProfile::sf2}) {
        auto a=std::make_unique<Machine>(),b=std::make_unique<Machine>();
        std::vector<std::uint8_t> rom(profile==pce::HuCardProfile::sf2?0x280000:0x80000);
        for(unsigned i=0;i<rom.size();++i)rom[i]=std::uint8_t((i>>13)*17+(i&255));
        for(auto* m:{a.get(),b.get()}) {m->bus.configure_hucard(profile,rom);m->bus.enable_work_ram_mirrors();m->bus.power_on_cpu(m->cpu);}
        if(profile==pce::HuCardProfile::sf2)a->bus.select_hucard_bank(3);
        if(profile==pce::HuCardProfile::populous){a->cpu.mpr[4]=0x44;a->bus.write(a->cpu,0x8523,0xA7);}
        a->cpu.mpr[1]=0xFA;a->bus.write(a->cpu,0x2491,0x59);a->cpu.mpr_latch=0xCA;a->bus.generation[248]+=19;
        const auto saved=pce::encode_checkpoint(a->bus,a->cpu);pce::restore_checkpoint(b->bus,b->cpu,saved);
        require(saved==pce::encode_checkpoint(b->bus,b->cpu),"Mapper/alias/dirty generation checkpoint differs");
        require(b->bus.peek(0x1F0491)==0x59,"WRAM mirrored backing was lost");
        if(profile==pce::HuCardProfile::sf2)require(b->bus.hucard_mapper_latch==3&&b->bus.peek(0x80000)==a->bus.peek(0x80000),"SF2 active executable window differs");
        if(profile==pce::HuCardProfile::populous)require(b->bus.peek(0x80523)==0xA7,"Populous mirrored volatile RAM differs");
    }
}
struct PrivateFiles {
    std::filesystem::path dir;
    std::vector<std::filesystem::path> files;
    PrivateFiles() {
        dir=std::filesystem::temp_directory_path()/("pce-checkpoint-authored-"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        require(std::filesystem::create_directory(dir),"Cannot create new isolated checkpoint fixture directory");
    }
    ~PrivateFiles(){std::error_code error;for(const auto& path:files)std::filesystem::remove(path,error);std::filesystem::remove(dir,error);}
    std::filesystem::path path(const std::string& name) {auto p=pce::checkpoint_path(dir,name);files.push_back(p);return p;}
    static std::vector<std::uint8_t> read(const std::filesystem::path& path) {
        std::ifstream in(path,std::ios::binary);return {std::istreambuf_iterator<char>(in),std::istreambuf_iterator<char>()};
    }
    std::filesystem::path copy(const std::string& name,const std::vector<std::uint8_t>& bytes) {
        const auto p=path(name);std::ofstream out(p,std::ios::binary);out.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());require(bool(out),"Cannot write new corrupted test copy");return p;
    }
};
template<class F> void refuses(F operation,const char* why) {bool rejected=false;try{operation();}catch(const std::exception&){rejected=true;}require(rejected,why);}
void envelope() {
    PrivateFiles f;const std::string identity(64,'a');auto live=configured(pce::AudioProfile::filtered,48000,pce::AudioTiming::gear);seed(*live);
    const auto before=pce::encode_checkpoint(live->bus,live->cpu);const auto path=f.path("frontier.pcec");
    pce::CheckpointHostState host;host.scripted={1,2,4,8,0x535};host.remote={16,32,64,128,0x789};host.input_applied=17;host.memory_requests=0;host.memory_changes=0;host.source_wav_frames=197;host.next_poll=live->cpu.ticks+9000;
    const auto saved=pce::save_checkpoint_file(path,identity,live->bus,live->cpu,host);const auto bytes=PrivateFiles::read(path);
    require(saved.sha256==pce::checkpoint_hash(bytes)&&saved.payload_sha256==pce::checkpoint_hash(before),"Envelope hashes do not bind actual file/payload");
    require(pce::encode_checkpoint(live->bus,live->cpu)==before,"Saving envelope advanced/mutated guest state");
    auto destination=configured(pce::AudioProfile::filtered,48000,pce::AudioTiming::gear);
    const auto loaded=pce::load_checkpoint_file(path,identity,destination->bus);
    require(loaded.sha256==saved.sha256&&loaded.payload_sha256==saved.payload_sha256&&loaded.machine&&
            pce::encode_checkpoint(loaded.machine->bus,loaded.machine->cpu)==before,"Envelope payload restore differs");
    require(loaded.host.scripted==host.scripted&&loaded.host.remote==host.remote&&loaded.host.input_applied==17&&loaded.host.source_wav_frames==197&&loaded.host.next_poll==host.next_poll,"Envelope input/WAV/poll recipe state differs");
    refuses([&]{pce::save_checkpoint_file(path,identity,live->bus,live->cpu,host);},"Envelope overwrote an existing file");
    require(PrivateFiles::read(path)==bytes,"Exclusive create changed existing checkpoint");
    refuses([&]{pce::load_checkpoint_file(path,std::string(64,'c'),live->bus);},"Mismatched binary/module/media/profile identity accepted");
    require(pce::encode_checkpoint(live->bus,live->cpu)==before,"Identity rejection mutated live state");
    for(unsigned mutation=0;mutation<11;++mutation) {
        auto corrupt=bytes;
        if(mutation==0)corrupt.clear();
        if(mutation==1)corrupt.pop_back();
        if(mutation==2)corrupt.push_back(0);
        if(mutation==3)corrupt[0]^=255;
        if(mutation==4)corrupt[8]^=1; // explicit LE schema field
        if(mutation==5)corrupt[12]^=1; // explicit LE runtime ABI field
        if(mutation==6)corrupt[16]=255; // bounded identity length
        if(mutation==7)corrupt[152]^=1; // explicit body byte length
        if(mutation==8)corrupt.back()^=1; // body digest violation
        if(mutation==9||mutation==10) {
            // Integrity-correct malformed decoded host/core copies exercise the
            // semantic decoder after digest acceptance (body begins at160).
            constexpr unsigned host_bytes=10*2+5*8;
            corrupt[160+(mutation==9?0:host_bytes)]^=255;
            if(mutation==9)corrupt[161]=255; // invalid 12-bit host mask
            const auto digest=pce::checkpoint_hash(std::span<const std::uint8_t>(corrupt).subspan(160));
            std::copy(digest.begin(),digest.end(),corrupt.begin()+88);
        }
        const auto copy=f.copy("corrupt-"+std::to_string(mutation)+".pcec",corrupt);
        refuses([&]{pce::load_checkpoint_file(copy,identity,live->bus);},"Written/reloaded corrupt envelope accepted");
        require(pce::encode_checkpoint(live->bus,live->cpu)==before,"Rejected envelope changed live state");
    }
    for(const auto* name:{"../outside.pcec",".hidden.pcec","NUL.pcec","com0.pcec","bad:stream.pcec","bad/file.pcec","frontier.state","a..pcec"})
        refuses([&]{pce::checkpoint_path(f.dir,name);},"Nonportable checkpoint socket basename accepted");
    require(!pce::checkpoint_hex_identity(std::string(64,'A'))&&!pce::checkpoint_hex_identity(std::string(63,'a'))&&pce::checkpoint_hex_identity(identity),"Exact lowercase identity syntax differs");
}
}
int main(){try{audio_device_matrix();mapper_matrix();envelope();std::cout<<checks<<" checkpoint state/continuation checks; host-seeded authored fixtures, no retail\n";return 0;}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}

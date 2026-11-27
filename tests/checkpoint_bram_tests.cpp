// Authored offline fixtures: no game data, save eligibility or campaign claims.
#include "pce/checkpoint_bram.hpp"
#include "pce/sector.hpp"
#include <chrono>
#include <fstream>
#include <iostream>

namespace {
unsigned checks=0;
void require(bool value,const char* why) {++checks;if(!value)throw std::runtime_error(why);}
template<class F> void refused(F&& f,const char* why) {
    bool rejected=false;try{f();}catch(const std::exception&){rejected=true;}require(rejected,why);
}
class NoReadDisc final:public pce::SectorProvider {
    pce::CdToc toc_;
public:
    NoReadDisc() {toc_.track_count=1;toc_.leadout_lba=12;toc_.tracks[0]={0,4};toc_.image_sha256=std::string(64,'d');}
    pce::Sector read(std::uint32_t) override {throw pce::Fault("Diagnostic must not read sectors");}
    pce::AudioSector read_audio(std::uint32_t) override {throw pce::Fault("Diagnostic must not read audio");}
    std::optional<pce::SubchannelSector> read_subchannel(std::uint32_t) override {throw pce::Fault("Diagnostic must not read subchannels");}
    const pce::CdToc& toc()const override{return toc_;}
};
std::unique_ptr<pce::Bus> configured(pce::SystemCardProfile profile=pce::SystemCardProfile::none) {
    auto bus=std::make_unique<pce::Bus>();
    if(profile!=pce::SystemCardProfile::none) {
        std::vector<std::uint8_t> rom(262144,0xEA);
        bus->configure_system_card(profile,rom);
    }
    bus->enable_cd_transport();bus->cd.set_sector_provider(std::make_shared<NoReadDisc>());return bus;
}
std::vector<std::uint8_t> read(const std::filesystem::path& path) {
    std::ifstream f(path,std::ios::binary);return {std::istreambuf_iterator<char>(f),{}};
}
void write(const std::filesystem::path& path,const std::vector<std::uint8_t>& bytes) {
    std::ofstream f(path,std::ios::binary);f.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());
}
}
int main() {
    const auto root=std::filesystem::temp_directory_path()/
        ("pce-bram-test-"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    try {
        if(!std::filesystem::create_directory(root))throw std::runtime_error("Fixture directory already exists");
        const std::string identity(64,'a');
        for(auto profile:{pce::SystemCardProfile::none,pce::SystemCardProfile::standard,pce::SystemCardProfile::super}) {
            auto bus=configured(profile),expected=configured(profile);pce::Cpu cpu;
            std::array<std::uint8_t,2048> pattern{};
            for(unsigned i=0;i<pattern.size();++i)pattern[i]=std::uint8_t(i*73+(i>>3)+19);
            std::copy(pattern.begin(),pattern.end(),bus->bytes->begin()+0x1EE000);
            std::fill_n(bus->bytes->begin()+0x1EE800,6144,0xC9);
            bus->cd.bram_unlocked=false;cpu.pc=0x8123;cpu.mpr={1,2,3,4,5,6,7,8};
            // Distinguish completed presentation frames from raster wraps.
            bus->vdc.raster.frames=7;
            cpu.native_steps=17;cpu.interpreter_steps=29;
            pce::CheckpointHostState host;host.memory_requests=7;host.memory_changes=3;
            const auto path=root/(std::to_string(unsigned(profile))+".pcec");
            const auto saved=pce::save_checkpoint_file(path,identity,*bus,cpu,host);
            const auto original=read(path),before=pce::encode_checkpoint(*bus,cpu);
            const auto configuration_before=pce::encode_checkpoint(*expected,pce::Cpu{});
            const auto result=pce::inspect_checkpoint_bram(path,identity,saved.sha256,*expected);
            require(result.bytes==pattern,"Exact independent 2048-byte pattern differs");
            // Independently calculated with Python hashlib from the authored
            // pattern; this expected value does not reuse the runtime hasher.
            require(result.bram_sha256=="6f700d0f84becd4656d8542e6d84647e573e2fb38b27f730658f5a2121fd2f83","BRAM digest differs");
            require(result.checkpoint_sha256==saved.sha256&&result.core_sha256==saved.payload_sha256,"File/core hashes differ");
            require(result.cpu.pc==0x8123&&result.cpu.mpr==cpu.mpr&&result.cpu.native_steps==17&&result.cpu.interpreter_steps==29,"Original CPU/accounting lost");
            require(result.host.memory_requests==7&&result.host.memory_changes==3,"Host metadata lost");
            require(result.frame==0&&result.raster_frames==7&&result.pending_pcm_frames==0,"Initial frame/PCM metadata differs");
            const auto metadata_path=root/(std::to_string(unsigned(profile))+"-metadata.pcec");
            pce::save_checkpoint_file(metadata_path,identity,*bus,result.cpu,result.host);
            require(read(metadata_path)==original,"Complete CPU/HOST metadata differs");
            require(!bus->peek(0x1EE000),"Diagnostic changed BRAM peek policy");
            require(read(path)==original&&pce::encode_checkpoint(*bus,cpu)==before,"Source changed");
            require(pce::encode_checkpoint(*expected,pce::Cpu{})==configuration_before,"Configured machine changed");
            refused([&]{pce::inspect_checkpoint_bram(path,identity,"",*expected);},"Missing hash accepted");
            refused([&]{pce::inspect_checkpoint_bram(root,identity,saved.sha256,*expected);},"Directory source accepted");
            refused([&]{pce::inspect_checkpoint_bram(path,identity,std::string(64,'b'),*expected);},"Wrong hash accepted");
            refused([&]{pce::inspect_checkpoint_bram(path,std::string(64,'b'),saved.sha256,*expected);},"Wrong identity accepted");
            const auto alias=root/(std::to_string(unsigned(profile))+"-hardlink.pcec");
            std::filesystem::create_hard_link(path,alias);
            refused([&]{pce::inspect_checkpoint_bram(path,identity,saved.sha256,*expected);},"Multiply linked original accepted");
            refused([&]{pce::inspect_checkpoint_bram(alias,identity,saved.sha256,*expected);},"Hard-link alias accepted");
            std::filesystem::remove(alias);
            for(unsigned mutation=0;mutation<5;++mutation) {
                auto bytes=original;
                if(mutation==0)bytes.pop_back();
                else if(mutation==1)bytes[0]^=1;
                else if(mutation==2)bytes[12]^=1; // Authored file ABI field.
                else if(mutation==3)bytes.back()^=1;
                else bytes.push_back(0);
                const auto malformed=root/(std::to_string(unsigned(profile))+"-bad"+std::to_string(mutation));write(malformed,bytes);
                refused([&]{pce::inspect_checkpoint_bram(malformed,identity,pce::checkpoint_hash(bytes),*expected);},"Malformed/checksum/ABI file accepted");
            }
            // Validly encoded generic checkpoints must still fail their exact
            // independently reconstructed CD memory configuration checks.
            for(unsigned mutation=0;mutation<2;++mutation) {
                auto foreign=configured(profile);
                if(mutation==0)foreign->kind[0xF7]=pce::BankKind::ram;
                else foreign->kind[0xF6]=pce::BankKind::bram;
                const auto foreign_path=root/(std::to_string(unsigned(profile))+"-foreign"+std::to_string(mutation)+".pcec");
                const auto foreign_saved=pce::save_checkpoint_file(foreign_path,identity,*foreign,pce::Cpu{},{});
                refused([&]{pce::inspect_checkpoint_bram(foreign_path,identity,foreign_saved.sha256,*expected);},"Foreign encoded BRAM geometry accepted");
            }
            expected->kind[0xF7]=pce::BankKind::ram;
            refused([&]{pce::inspect_checkpoint_bram(path,identity,saved.sha256,*expected);},"Wrong F7 kind accepted");
            expected->kind[0xF7]=pce::BankKind::bram;expected->kind[0xF6]=pce::BankKind::bram;
            refused([&]{pce::inspect_checkpoint_bram(path,identity,saved.sha256,*expected);},"Extra BRAM bank accepted");
            expected->kind[0xF6]=pce::BankKind::unmapped;expected->cd.enabled=false;
            refused([&]{pce::inspect_checkpoint_bram(path,identity,saved.sha256,*expected);},"Disabled CD accepted");
            expected->cd.enabled=true;expected->hucard=true;
            refused([&]{pce::inspect_checkpoint_bram(path,identity,saved.sha256,*expected);},"HuCard accepted");
            expected->hucard=false;expected->bytes.reset();
            refused([&]{pce::inspect_checkpoint_bram(path,identity,saved.sha256,*expected);},"Missing backing accepted");
            auto enhanced=configured(profile);host.adapter=pce::CheckpointAdapterState{std::string(64,'c'),{1,2,3}};
            const auto enhanced_path=root/(std::to_string(unsigned(profile))+"-enhanced.pcec");
            const auto enhanced_saved=pce::save_checkpoint_file(enhanced_path,identity,*enhanced,pce::Cpu{},host);
            refused([&]{pce::inspect_checkpoint_bram(enhanced_path,identity,enhanced_saved.sha256,*enhanced);},"Unbound adapter accepted");
            if(profile!=pce::SystemCardProfile::none) {
                auto changed=configured(profile);(*changed->bytes)[0x123]=0;
                refused([&]{pce::inspect_checkpoint_bram(path,identity,saved.sha256,*changed);},"Different immutable ROM accepted");
            }
            require(read(path)==original&&pce::encode_checkpoint(*bus,cpu)==before,"Rejection changed original source");
        }
        std::filesystem::remove_all(root);
        std::cout<<"Checkpoint BRAM checks passed: "<<checks<<'\n';return 0;
    } catch(const std::exception& e) {std::cerr<<e.what()<<"; authored fixture retained at "<<root<<'\n';return 1;}
}

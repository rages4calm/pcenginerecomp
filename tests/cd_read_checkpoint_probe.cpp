// Real translated/interpreted LDA/STA operations, authored immutable media.
#include "pce/checkpoint.hpp"
#include "pce/checkpoint_file.hpp"
#include "pce/code_capture.hpp"
#include "pce/sector.hpp"
#include "cd_read_checkpoint_fixture.hpp"
#include "cd_read_checkpoint_support.hpp"
#include <filesystem>
#include <memory>
#include <map>
namespace {
void require(bool value,const char* reason){if(!value)throw std::runtime_error(reason);}
std::vector<std::uint8_t> read(const std::string& path) {
    std::ifstream in(path,std::ios::binary);require(bool(in),"checkpoint input missing");
    return {std::istreambuf_iterator<char>(in),{}};
}
void write(const std::string& path,const std::vector<std::uint8_t>& bytes) {
    require(!std::filesystem::exists(path),"new checkpoint required");std::ofstream out(path,std::ios::binary);
    out.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());require(bool(out),"checkpoint write failed");
}
struct Provider final:pce::SectorProvider {
    std::shared_ptr<pce::SectorProvider> source;unsigned reads=0;
    explicit Provider(const char* cue):source(pce::open_sector_provider(cue)){}
    const pce::CdToc& toc()const override{return source->toc();}
    pce::Sector read(std::uint32_t lba)override{++reads;return source->read(lba);}
};
struct Adapter {
    std::unique_ptr<pce::Bus> bus=std::make_unique<pce::Bus>();pce::Cpu cpu;
    std::shared_ptr<Provider> provider;bool native;std::unique_ptr<pce::CodeCapture> capture;
    std::map<unsigned,unsigned> hits;
    Adapter(const std::vector<std::uint8_t>& rom,const char* cue,bool n,unsigned speed):provider(std::make_shared<Provider>(cue)),native(n) {
        bus->configure_system_card(pce::SystemCardProfile::super,rom);bus->enable_cd_transport();
        bus->cd.set_sector_provider(provider);cpu.mpr=checkpoint_mpr;cpu.clock_divisor=speed;cpu.p=pce::I;
        for(auto [physical,value]:checkpoint_program)(*bus->bytes)[physical]=value;
    }
    void operation(unsigned opcode,unsigned address,unsigned value=0) {
        unsigned site=0;for(const auto& row:checkpoint_sites)if(row.op==opcode&&row.address==address)site=row.pc;
        require(site!=0,"missing authored port site");cpu.pc=static_cast<std::uint16_t>(site);cpu.a=static_cast<std::uint8_t>(value);
        const auto pending=capture->before(*bus,cpu);
        require((native?pce::generated_step(*bus,cpu,UINT64_MAX):pce::interpret_step(*bus,cpu,UINT64_MAX))==pce::Exit::executed,"actual guest port opcode refused");
        capture->after(pending,cpu);++hits[site];
    }
    void advance(unsigned n){cpu.ticks+=n;bus->sync(cpu);}
    unsigned load_wait()const{const auto due=bus->cd.scsi.load_deadline;require(due>cpu.ticks&&due-cpu.ticks<10000000,"bounded pending load required");return static_cast<unsigned>(due-cpu.ticks);}
    unsigned signals()const{return bus->cd.scsi.signals;}
    bool busy()const{return signals()&128;}bool request()const{return signals()&64;}
    bool input()const{return signals()&8;}bool control()const{return signals()&16;}bool message()const{return signals()&32;}
    void select(){operation(0x8d,0x1800);}void write_data(unsigned v){operation(0x8d,0x1801,v);}
    void ack(bool v){operation(0x8d,0x1802,v?128:0);}void reset_line(bool v){operation(0x8d,0x1804,v?2:0);}
    unsigned read_data(bool automatic){operation(0xad,automatic?0x1808:0x1801);return cpu.a;}
    void captured(const std::string& path){capture=std::make_unique<pce::CodeCapture>(path,64);hits.clear();}
};
void hits_json(const std::map<unsigned,unsigned>& hits){std::cout<<'{';bool first=true;for(auto [pc,count]:hits){std::cout<<(first?"":",")<<'"'<<pc<<"\":"<<count;first=false;}std::cout<<'}';}
}
int main(int argc,char** argv) {
    try {
        if(argc!=9)throw std::runtime_error("PLAN ROM CUE MODE TIER CHECKPOINT NEW_CAPTURE NEW_REPORT");
        const auto plan=cd_checkpoint::plan(argv[1]);const std::string mode=argv[4],tier=argv[5];
        require((mode=="write"||mode=="resume")&&(tier=="native"||tier=="interpreter"),"explicit mode/tier required");
        require(!std::filesystem::exists(argv[8]),"new execution report required");
        Adapter a(reset_probe::rom(argv[2]),argv[3],tier=="native",plan.divisor);
        std::vector<unsigned> prefix;std::vector<std::uint8_t> saved;
        if(mode=="write") {
            a.captured(std::string(argv[7])+".prefix.json");prefix=cd_checkpoint::prefix(a,plan);a.capture->finish();
            const auto before_reads=a.provider->reads;saved=pce::encode_checkpoint(*a.bus,a.cpu);
            require(a.provider->reads==before_reads,"save read provider");write(argv[6],saved);
            require(pce::encode_checkpoint(*a.bus,a.cpu)==saved,"save mutated live machine");
        } else {
            saved=read(argv[6]);require(a.provider->reads==0,"configuration read payload");
            pce::restore_checkpoint(*a.bus,a.cpu,saved);require(a.provider->reads==0,"restore read provider");
        }
        require(pce::encode_checkpoint(*a.bus,a.cpu)==saved,"noncanonical checkpoint roundtrip");
        const auto origin_n=a.cpu.native_steps,origin_i=a.cpu.interpreter_steps,origin_ticks=a.cpu.ticks;
        const auto before_reads=a.provider->reads;const auto& s=a.bus->cd.scsi;
        std::vector<unsigned> cut{static_cast<unsigned>(s.phase),static_cast<unsigned>(s.signals),unsigned(a.bus->cd.ack),s.response_size,s.response_index,s.load_lba,s.load_remaining,unsigned(s.read_active)};
        auto residual=[&](std::uint64_t deadline){return deadline?deadline-s.master_ticks:0;};
        std::vector<std::uint64_t> timing{s.event,residual(s.deadline),residual(s.auto_ack_deadline),residual(s.load_deadline),s.current_lba,a.bus->cd.interrupt_active,s.command_size,s.data,a.bus->cd.read_retries,a.bus->cd.sectors_read};
        std::vector<unsigned> source{a.cpu.pc};for(auto bank:a.cpu.mpr)source.push_back(bank);
        for(unsigned i=0;i<7;++i){const auto physical=pce::Bus::physical(a.cpu,static_cast<std::uint16_t>(a.cpu.pc+i));source.push_back(physical);const auto value=a.bus->peek(physical);require(value.has_value(),"cut source unreadable");source.push_back(*value);}
        a.captured(argv[7]);if(mode=="resume")a.capture->set_checkpoint_origin(pce::checkpoint_hash(saved),a.cpu.ticks,0,origin_n,origin_i);
        const auto reply=cd_checkpoint::suffix(a,plan);a.capture->finish();
        require(a.cpu.guard_misses==0,"guard miss in authored guest");
        const auto suffix_n=a.cpu.native_steps-origin_n,suffix_i=a.cpu.interpreter_steps-origin_i;
        require(tier=="native"?(suffix_n>0&&!suffix_i):(!suffix_n&&suffix_i>0),"wrong actual suffix tier");
        std::ofstream report(argv[8]);require(bool(report),"execution report open");
        report<<"{\"runtime_abi\":"<<pce::abi_version<<",\"prefix_native\":"<<origin_n<<",\"prefix_interpreted\":"<<origin_i
              <<",\"suffix_native\":"<<suffix_n<<",\"suffix_interpreted\":"<<suffix_i<<",\"guard_misses\":"<<a.cpu.guard_misses
              <<",\"provider_reads_before_suffix\":"<<before_reads<<",\"provider_reads_suffix\":"<<a.provider->reads-before_reads<<'}';
        std::cout<<"{\"cut\":";cd_checkpoint::vector_json(cut);std::cout<<",\"timing\":[";for(unsigned i=0;i<timing.size();++i)std::cout<<(i?",":"")<<timing[i];
        std::cout<<"],\"cut_source\":";cd_checkpoint::vector_json(source);std::cout<<",\"prefix\":";cd_checkpoint::vector_json(prefix);
        std::cout<<",\"reply\":";cd_checkpoint::reply_json(reply);std::cout<<",\"hits\":";hits_json(a.hits);
        std::cout<<",\"origin_ticks\":"<<origin_ticks<<",\"final_ticks\":"<<a.cpu.ticks<<",\"checkpoint_sha256\":\""<<pce::checkpoint_hash(saved)
                 <<"\",\"final_sha256\":\""<<pce::checkpoint_hash(pce::encode_checkpoint(*a.bus,a.cpu))<<"\"}\n";
        return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}

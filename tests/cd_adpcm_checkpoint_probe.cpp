// Actual translated/interpreted port operations; independent authored media.
#include "pce/checkpoint.hpp"
#include "pce/checkpoint_file.hpp"
#include "pce/code_capture.hpp"
#include "pce/sector.hpp"
#include "cd_adpcm_checkpoint_fixture.hpp"
#include "cd_adpcm_checkpoint_support.hpp"
#include <filesystem>
#include <memory>
#include <map>
namespace {
using dma_checkpoint::require;
std::vector<std::uint8_t> read_file(const char* path){std::ifstream in(path,std::ios::binary);require(bool(in),"checkpoint missing");return {std::istreambuf_iterator<char>(in),{}};}
void write_file(const char* path,const std::vector<std::uint8_t>& bytes){require(!std::filesystem::exists(path),"new checkpoint required");std::ofstream out(path,std::ios::binary);out.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());require(bool(out),"checkpoint write");}
struct Provider:pce::SectorProvider{std::shared_ptr<pce::SectorProvider> source;unsigned reads=0;explicit Provider(const char* cue):source(pce::open_sector_provider(cue)){}const pce::CdToc& toc()const override{return source->toc();}pce::Sector read(std::uint32_t lba)override{++reads;return source->read(lba);}};
struct Adapter{
 std::unique_ptr<pce::Bus> bus=std::make_unique<pce::Bus>();pce::Cpu cpu;std::shared_ptr<Provider> provider;bool native;
 std::unique_ptr<pce::CodeCapture> capture;std::map<unsigned,unsigned> hits;std::vector<dma_checkpoint::Mark> journal;std::uint64_t calls=0,advanced=0;
 Adapter(const std::vector<std::uint8_t>& rom,const char* cue,bool n,unsigned divisor):provider(std::make_shared<Provider>(cue)),native(n){bus->configure_system_card(pce::SystemCardProfile::super,rom);bus->enable_cd_transport();bus->adpcm.enabled=true;bus->cd.set_sector_provider(provider);cpu.mpr=checkpoint_mpr;cpu.clock_divisor=divisor;cpu.p=pce::I;for(auto[a,v]:checkpoint_program)(*bus->bytes)[a]=v;}
 void operation(unsigned op,unsigned address,unsigned value=0){unsigned pc=0;for(auto site:checkpoint_sites)if(site.op==op&&site.address==address)pc=site.pc;require(pc!=0,"authored port site missing");cpu.pc=pc;cpu.a=value;const auto before=capture->before(*bus,cpu);require((native?pce::generated_step(*bus,cpu,UINT64_MAX):pce::interpret_step(*bus,cpu,UINT64_MAX))==pce::Exit::executed,"direct port operation refused");capture->after(before,cpu);++hits[pc];}
 void write(unsigned address,unsigned value){operation(0x8d,address,value);}unsigned read(unsigned address){operation(0xad,address);return cpu.a;}
 void advance(unsigned n){++calls;advanced+=n;cpu.ticks+=n;bus->sync(cpu);}void advance_safe(unsigned n){require(!request()&&(!(dma()&3)||!dma_remaining())&&!write_remaining(),"unsafe pre-load coarse wait");const auto before=dma_remaining(),len=length(),address=write_address();const auto sectors=bus->cd.sectors_read;const auto bytes=ram();advance(n);require(ram()==bytes&&length()==len&&write_address()==address&&bus->cd.sectors_read==sectors,"coarse pre-load wait transferred data");if(!(dma()&3))require(dma_remaining()==before,"coarse wait changed frozen DMA residual");}
 unsigned load_wait()const{auto due=bus->cd.scsi.load_deadline;require(due>cpu.ticks&&due-cpu.ticks<10000000,"bounded pending load required");return due-cpu.ticks;}
 unsigned signals()const{return bus->cd.scsi.signals;}bool busy()const{return signals()&128;}bool request()const{return signals()&64;}bool input()const{return signals()&8;}bool control()const{return signals()&16;}bool message()const{return signals()&32;}bool ack()const{return bus->cd.ack;}
 unsigned dma()const{return bus->adpcm.dma;}unsigned dma_remaining()const{return bus->adpcm.dma_deadline?bus->adpcm.dma_deadline-cpu.ticks:0;}unsigned write_remaining()const{return bus->adpcm.write_deadline?bus->adpcm.write_deadline-cpu.ticks:0;}
 unsigned write_address()const{return bus->adpcm.write_address;}unsigned length()const{return bus->adpcm.length;}unsigned half()const{return bus->adpcm.half_irq;}unsigned end()const{return bus->adpcm.end_irq;}unsigned irq()const{return bus->cd.irq2();}
 std::vector<unsigned> ram()const{return {bus->adpcm.ram.begin(),bus->adpcm.ram.end()};}
 std::vector<std::uint64_t> snapshot()const{const auto& c=bus->cd;return {cpu.ticks,signals(),dma(),dma_remaining(),write_remaining(),write_address(),length(),half(),end(),irq(),c.interrupt_active,c.interrupt_enable,c.scsi.auto_ack_deadline?c.scsi.auto_ack_deadline-cpu.ticks:0};}
 std::string error_state()const{const auto&s=bus->cd.scsi;std::ostringstream out;out<<"phase="<<s.phase<<" response="<<s.response_index<<"/"<<s.response_size<<" load="<<s.load_lba<<" remaining="<<s.load_remaining<<" load_deadline="<<s.load_deadline<<" event="<<s.event<<" data="<<+s.data<<" control="<<+bus->adpcm.control<<" write_latch="<<+bus->adpcm.write_latch<<" dma_bytes="<<bus->adpcm.dma_bytes;return out.str();}
 void captured(const std::string& path){capture=std::make_unique<pce::CodeCapture>(path,64);hits.clear();}
};
void hits_json(const std::map<unsigned,unsigned>& rows){std::cout<<'{';bool first=true;for(auto[pc,n]:rows){std::cout<<(first?"":",")<<'"'<<pc<<"\":"<<n;first=false;}std::cout<<'}';}
}
int main(int argc,char** argv){try{
 require(argc==9,"PLAN ROM CUE MODE TIER CHECKPOINT NEW_CAPTURE NEW_EXECUTION");auto p=dma_checkpoint::plan(argv[1]);const std::string mode=argv[4],tier=argv[5];require((mode=="write"||mode=="resume")&&(tier=="native"||tier=="interpreter"),"explicit mode and tier");require(!std::filesystem::exists(argv[8]),"new report required");
 Adapter a(reset_probe::rom(argv[2]),argv[3],tier=="native",p.divisor);std::vector<std::uint8_t> saved;
 if(mode=="write"){a.captured(std::string(argv[7])+".prefix.json");dma_checkpoint::prefix(a,p);a.capture->finish();auto before=a.provider->reads;saved=pce::encode_checkpoint(*a.bus,a.cpu);require(a.provider->reads==before,"save read provider");write_file(argv[6],saved);}else{saved=read_file(argv[6]);pce::restore_checkpoint(*a.bus,a.cpu,saved);require(a.provider->reads==0,"restore read provider");}
 require(pce::encode_checkpoint(*a.bus,a.cpu)==saved,"canonical checkpoint roundtrip");auto origin_n=a.cpu.native_steps,origin_i=a.cpu.interpreter_steps,origin_ticks=a.cpu.ticks;const auto reads_before=a.provider->reads;auto cut=a.snapshot();
 std::vector<unsigned> cut_source{a.cpu.pc};cut_source.insert(cut_source.end(),a.cpu.mpr.begin(),a.cpu.mpr.end());for(unsigned i=0;i<7;++i){auto address=pce::Bus::physical(a.cpu,static_cast<std::uint16_t>(a.cpu.pc+i));auto value=a.bus->peek(address);require(bool(value),"pure cut source peek");cut_source.insert(cut_source.end(),{address,*value});}
 a.captured(argv[7]);if(mode=="resume")a.capture->set_checkpoint_origin(pce::checkpoint_hash(saved),a.cpu.ticks,0,origin_n,origin_i);auto reply=dma_checkpoint::suffix(a,p);a.capture->finish();require(a.cpu.guard_misses==0,"native guard miss");
 std::ofstream out(argv[8]);out<<"{\"runtime_abi\":"<<pce::abi_version<<",\"prefix_native\":"<<origin_n<<",\"prefix_interpreted\":"<<origin_i<<",\"suffix_native\":"<<a.cpu.native_steps-origin_n<<",\"suffix_interpreted\":"<<a.cpu.interpreter_steps-origin_i<<",\"guard_misses\":0,\"provider_reads_before_suffix\":"<<reads_before<<",\"provider_reads_suffix\":"<<a.provider->reads-reads_before<<'}';require(bool(out),"execution report write");
 std::cout<<"{\"cut\":";dma_checkpoint::vector_json(cut);std::cout<<",\"cut_source\":";dma_checkpoint::vector_json(cut_source);std::cout<<",\"prefix\":[],\"reply\":";dma_checkpoint::reply_json(reply);std::cout<<",\"hits\":";hits_json(a.hits);std::cout<<",\"origin_ticks\":"<<origin_ticks<<",\"final_ticks\":"<<a.cpu.ticks<<",\"checkpoint_sha256\":\""<<pce::checkpoint_hash(saved)<<"\",\"final_sha256\":\""<<pce::checkpoint_hash(pce::encode_checkpoint(*a.bus,a.cpu))<<"\",\"journal\":";dma_checkpoint::journal_json(a.journal);std::cout<<",\"advance_calls\":"<<a.calls<<",\"advanced_ticks\":"<<a.advanced<<"}\n";return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}

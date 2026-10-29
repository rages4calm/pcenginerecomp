// Autonomous translated/interpreted guest and exact-build fresh checkpoints.
#include "pce/checkpoint.hpp"
#include "pce/checkpoint_file.hpp"
#include "pce/code_capture.hpp"
#include "pce/sector.hpp"
#include "dma_irq_checkpoint_support.hpp"
#include <filesystem>
#include <memory>
namespace {
using namespace dma_irq;
struct Provider:pce::SectorProvider{std::shared_ptr<pce::SectorProvider> source;unsigned reads=0;explicit Provider(const char* path):source(pce::open_sector_provider(path)){}const pce::CdToc& toc()const override{return source->toc();}pce::Sector read(std::uint32_t lba)override{++reads;return source->read(lba);}};
struct Record{Source source;std::uint64_t ticks;unsigned vector;Observation after;};
struct Adapter {
 std::unique_ptr<pce::Bus> bus=std::make_unique<pce::Bus>();pce::Cpu cpu;bool native,window=false;
 std::shared_ptr<Provider> provider;std::unique_ptr<pce::CodeCapture> capture;Work work;
 std::map<Source,std::uint64_t> sources;std::vector<Record> journal;
 Adapter(const char* rom,const char* cue,bool n):native(n),provider(std::make_shared<Provider>(cue)){
  bus->configure_system_card(pce::SystemCardProfile::standard,reset_probe::rom(rom));bus->enable_video();bus->enable_interrupts();bus->enable_cd_transport();bus->enable_adpcm();bus->cd.set_sector_provider(provider);bus->power_on_cpu(cpu,0,0);
 }
 unsigned pc()const{return cpu.pc;}
 std::vector<unsigned> wram()const{return {bus->bytes->begin()+0x1f0000,bus->bytes->begin()+0x1f2000};}
 std::vector<unsigned> ram()const{return {bus->adpcm.ram.begin(),bus->adpcm.ram.end()};}
 Observation observe()const{const auto&a=bus->adpcm;const auto&c=bus->cd;Observation o;
  o.values={cpu.pc,cpu.a,cpu.x,cpu.y,cpu.sp,cpu.p,cpu.clock_divisor,cpu.ticks,cpu.irq_entries,cpu.rti_steps,bus->irq.mask,bus->irq_requests(),c.interrupt_enable,c.interrupt_active,c.scsi.signals,a.dma,a.length,a.write_address,a.half_irq,a.end_irq,a.dma_bytes,a.write_deadline?1u:0u,c.irq2()?1u:0u};
  o.stack.assign(bus->bytes->begin()+0x1f0100,bus->bytes->begin()+0x1f0200);o.wram=irq_trace::hash(std::span<const std::uint8_t>(bus->bytes->data()+0x1f0000,8192));return o;
 }
 void captured(const std::string& path,bool suffix){capture=std::make_unique<pce::CodeCapture>(path,4096);work={};sources.clear();journal.clear();window=suffix;}
 void step(){Source s{cpu.pc,{},{}};for(unsigned i=0;i<8;++i)s.mpr[i]=cpu.mpr[i];auto byte=[&](unsigned address){auto v=bus->peek(pce::Bus::physical(cpu,address));require(bool(v),"Authored instruction peek");return *v;};const unsigned length=size(byte(cpu.pc));for(unsigned i=0;i<length;++i)s.bytes.push_back(byte(cpu.pc+i));
  const auto ticks=cpu.ticks,entries=cpu.irq_entries,rtis=cpu.rti_steps;const unsigned a=cpu.a,p=cpu.p;const auto before=capture->before(*bus,cpu);
  require((native?pce::generated_step(*bus,cpu,UINT64_MAX):pce::interpret_step(*bus,cpu,UINT64_MAX))==pce::Exit::executed,"Autonomous opcode refused; fallback forbidden");capture->after(before,cpu);
  ++sources[s];++work.instructions;++work.calls;work.clock_ticks+=cpu.ticks-ticks;work.irqs+=cpu.irq_entries-entries;work.rtis+=cpu.rti_steps-rtis;
  const unsigned vector=cpu.irq_entries>entries?cpu.irq_vector:0;
  if(vector){require(vector==0xfff6,"Unexpected autonomous IRQ vector");irq_frame(s,a,p,cpu.a,observe());}
  if(s.bytes[0]==0x40)rti_frame(observe());
  if(vector||(window&&(work.instructions<=64||(s.pc>=0xf800&&s.pc<0xf820))))journal.push_back({s,cpu.ticks-ticks,vector,observe()});
 }
};
std::vector<std::uint8_t> read(const char* path){std::ifstream in(path,std::ios::binary);require(bool(in),"Checkpoint missing");return {std::istreambuf_iterator<char>(in),{}};}
void write(const char* path,const std::vector<std::uint8_t>& bytes){require(!std::filesystem::exists(path),"New checkpoint required");std::ofstream out(path,std::ios::binary);out.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());require(bool(out),"Checkpoint write failed");}
void records(const std::vector<Record>& rows){std::cout<<'[';bool first=true;for(const auto&r:rows){std::cout<<(first?"":",")<<"{\"pc\":"<<r.source.pc<<",\"mpr\":";vec(std::cout,r.source.mpr);std::cout<<",\"physical\":[";for(unsigned i=0;i<r.source.bytes.size();++i)std::cout<<(i?",":"")<<((r.source.mpr[((r.source.pc+i)&65535)>>13]<<13)|((r.source.pc+i)&8191));std::cout<<"],\"bytes\":";vec(std::cout,r.source.bytes);std::cout<<",\"ticks\":"<<r.ticks<<",\"vector\":"<<r.vector<<",\"after\":";observation(std::cout,r.after);std::cout<<'}';first=false;}std::cout<<']';}
}
int main(int argc,char**argv){try{
 require(argc==9,"CASE ROM CUE CUT write|resume TIER CHECKPOINT CAPTURE");const auto& c=dma_irq_case(argv[1]);const unsigned cut=std::stoul(argv[4]);require(cut<2,"Two authored cuts only");const std::string mode=argv[5],tier=argv[6];require((mode=="write"||mode=="resume")&&(tier=="native"||tier=="interpreter"),"Explicit mode/tier required");Adapter a(argv[2],argv[3],tier=="native");std::vector<std::uint8_t> saved;Work prefix;std::map<Source,std::uint64_t> prefix_hits;std::vector<Record> prefix_journal;
 if(mode=="write"){a.captured(std::string(argv[8])+".prefix.json",false);reach(a,cut_pc(a,c,cut));a.capture->finish();prefix=a.work;prefix_hits=a.sources;prefix_journal=a.journal;const auto reads=a.provider->reads;saved=pce::encode_checkpoint(*a.bus,a.cpu);require(reads==a.provider->reads,"Checkpoint save read provider");write(argv[7],saved);}else{saved=read(argv[7]);pce::restore_checkpoint(*a.bus,a.cpu,saved);require(!a.provider->reads,"Restore read provider");}
 require(pce::encode_checkpoint(*a.bus,a.cpu)==saved,"Canonical exact checkpoint roundtrip");require(a.pc()==cut_pc(a,c,cut),"Imported checkpoint boundary differs");const auto initial=a.observe();const auto origin_n=a.cpu.native_steps,origin_i=a.cpu.interpreter_steps;const auto reads=a.provider->reads;const auto origin_frame=a.bus->vdc.video.sequence();
 a.captured(argv[8],true);if(mode=="resume")a.capture->set_checkpoint_origin(pce::checkpoint_hash(saved),a.cpu.ticks,a.bus->vdc.video.sequence(),origin_n,origin_i);finish(a,c);a.capture->finish();final_checks(a,c);
 require(a.cpu.guard_misses==0&&a.cpu.native_steps-origin_n==(a.native?a.work.instructions:0)&&a.cpu.interpreter_steps-origin_i==(a.native?0:a.work.instructions),"Actual suffix execution tier differs");
 std::cout<<"{\"dma_counter_role\":\"captured-bytes\",\"case\":\""<<c.id<<"\",\"cut_id\":"<<cut<<",\"tier\":\""<<tier<<"\",\"mode\":\""<<mode<<"\",\"runtime_abi\":"<<pce::abi_version<<",\"prefix_native\":"<<origin_n<<",\"prefix_interpreted\":"<<origin_i<<",\"window_native\":"<<a.cpu.native_steps-origin_n<<",\"window_interpreted\":"<<a.cpu.interpreter_steps-origin_i<<",\"guard_misses\":0,\"provider_prefix\":"<<reads<<",\"provider_suffix\":"<<a.provider->reads-reads<<",\"origin_frame\":"<<origin_frame<<",\"checkpoint_sha256\":\""<<pce::checkpoint_hash(saved)<<"\",\"final_sha256\":\""<<pce::checkpoint_hash(pce::encode_checkpoint(*a.bus,a.cpu))<<"\",\"cut\":";observation(std::cout,initial);std::cout<<",\"final\":";observation(std::cout,a.observe());std::cout<<",\"prefix_work\":";work_json(std::cout,prefix);std::cout<<",\"window_work\":";work_json(std::cout,a.work);std::cout<<",\"prefix_hits\":";hits(std::cout,prefix_hits);std::cout<<",\"window_hits\":";hits(std::cout,a.sources);std::cout<<",\"prefix_journal\":";records(prefix_journal);std::cout<<",\"journal\":";records(a.journal);std::cout<<",\"ram\":";vec(std::cout,a.ram());std::cout<<"}\n";return 0;
 }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}

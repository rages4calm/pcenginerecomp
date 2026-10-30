// Authored guest-only phase sweep; translated execution has no fallback.
#include "pce/runtime.hpp"
#include "pce/code_capture.hpp"
#include "vdc_phase_fixture.hpp"
#include "reset_probe_support.hpp"
#include <array>
#include <memory>
#include <vector>

namespace {
using Row=std::vector<std::uint64_t>;
void require(bool ok,const char*why){if(!ok)throw std::runtime_error(why);}
template<class T>void vec(const T&v){std::cout<<'[';bool first=true;for(auto x:v){std::cout<<(first?"":",")<<+x;first=false;}std::cout<<']';}
struct Record{unsigned pc;std::array<std::uint8_t,8>mpr;std::vector<unsigned>bytes;Row before,after,cpu_before,cpu_after;std::uint64_t ticks,waits;};
struct Adapter{
 std::unique_ptr<pce::Bus>bus=std::make_unique<pce::Bus>();pce::Cpu cpu;bool native;std::vector<Record>records;std::uint64_t n=0,blocks=0,bytes=0;
 Adapter(const char*rom,bool tier):native(tier){bus->configure_hucard(pce::HuCardProfile::base,reset_probe::rom(rom));bus->enable_continuous_video();bus->enable_interrupts();bus->power_on_cpu(cpu,0,0);}
 Row phase()const{const auto&v=bus->vdc;const auto&r=v.raster;return{cpu.ticks,r.hclock,r.dot,r.vdc_line,r.line,r.v_state,r.h_state,static_cast<unsigned>(r.h_remaining),r.divider,v.pending_vram_read,v.pending_vram_write,static_cast<unsigned>(v.vram_transfer_delay),v.vram_cpu_cycles,v.vram_dma_pending,v.satb_pending,v.sprite_burst,v.sprite_control,v.sprite_mode,v.sprite_count,static_cast<unsigned>(v.load_bg_start_clock),static_cast<unsigned>(v.load_bg_end_clock),v.hsync_start_clock,v.read_buffer,v.reg[1],v.reg[0],v.reg[16],v.reg[17],v.reg[18],v.vram_bus_latch,v.selected,v.status,v.irq1,v.reg[10],v.reg[11],v.reg[5],((r.horizontal[3]/8-1)&31)|(((r.horizontal[0]/8-1)&127)<<8),((r.horizontal[1]/8-1)&127)|(((r.horizontal[2]/8-1)&127)<<8),r.horizontal[0],r.horizontal[1],r.horizontal[2],r.horizontal[3]};}
 Row cpu_row()const{Row r{cpu.pc,cpu.a,cpu.x,cpu.y,cpu.sp,cpu.p,cpu.clock_divisor,cpu.ticks};for(auto m:cpu.mpr)r.push_back(m);return r;}
 void step(pce::CodeCapture&capture,const PhaseCase&c){const auto pending=capture.before(*bus,cpu);require(pending.readable,"Authored phase source unreadable");const auto before=phase(),cb=cpu_row();const auto waits=cpu.vdc_wait_ticks;const auto&id=pending.identity;const bool selected=id.pc==c.launch||id.pc==c.target;
  require((native?pce::generated_step(*bus,cpu,UINT64_MAX):pce::interpret_step(*bus,cpu,UINT64_MAX))==pce::Exit::executed,"Phase opcode refused; native fallback forbidden");capture.after(pending,cpu);++n;
  if(id.data[0]==0x73||id.data[0]==0xf3){++blocks;bytes+=unsigned(id.data[5])|(unsigned(id.data[6])<<8);}
  if(selected){std::vector<unsigned>raw;for(unsigned i=0;i<id.length;++i)raw.push_back(id.data[i]);records.push_back({id.pc,id.mpr,raw,before,phase(),cb,cpu_row(),cpu.ticks-before[0],cpu.vdc_wait_ticks-waits});}
 }
};
void records(const std::vector<Record>&rows){std::cout<<'[';bool first=true;for(const auto&r:rows){std::cout<<(first?"":",")<<"{\"pc\":"<<r.pc<<",\"mpr\":";vec(r.mpr);std::cout<<",\"physical\":[";for(unsigned i=0;i<r.bytes.size();++i)std::cout<<(i?",":"")<<((unsigned(r.mpr[((r.pc+i)&65535)>>13])<<13)|((r.pc+i)&8191));std::cout<<"],\"bytes\":";vec(r.bytes);std::cout<<",\"before\":";vec(r.before);std::cout<<",\"after\":";vec(r.after);std::cout<<",\"cpu_before\":";vec(r.cpu_before);std::cout<<",\"cpu_after\":";vec(r.cpu_after);std::cout<<",\"ticks\":"<<r.ticks<<",\"wait_ticks\":"<<r.waits<<",\"calls\":1,\"internal\":0,\"clocks\":[],\"call_rows\":[],\"events\":[]}";first=false;}std::cout<<']';}
}
int main(int argc,char**argv){try{require(argc==5,"CASE ROM native|interpreter CAPTURE");const auto&c=phase_case(argv[1]);const std::string tier=argv[3];require(tier=="native"||tier=="interpreter","Explicit phase execution tier required");Adapter a(argv[2],tier=="native");pce::CodeCapture capture(argv[4],4096);while(a.cpu.pc!=c.done){require(a.n<1000,"Finite authored phase source bound exceeded");a.step(capture,c);}capture.finish();
 require(a.cpu.guard_misses==0&&a.cpu.native_steps==(a.native?a.n:0)&&a.cpu.interpreter_steps==(a.native?0:a.n)&&a.cpu.native_block_steps==(a.native?a.blocks:0)&&a.cpu.interpreter_block_steps==(a.native?0:a.blocks)&&a.cpu.block_bytes==a.bytes&&a.cpu.irq_entries==0&&a.cpu.rti_steps==0,"Actual phase tier/block/IRQ work differs");
 std::cout<<"{\"schema\":1,\"case\":\""<<c.id<<"\",\"tier\":\""<<tier<<"\",\"runtime_abi\":"<<pce::abi_version<<",\"instructions\":"<<a.n<<",\"calls\":"<<a.n<<",\"clock_calls\":0,\"blocks\":"<<a.blocks<<",\"block_bytes\":"<<a.bytes<<",\"wait_ticks\":"<<a.cpu.vdc_wait_ticks<<",\"records\":";records(a.records);std::cout<<",\"final_cpu\":";vec(a.cpu_row());std::cout<<",\"final_phase\":";vec(a.phase());std::cout<<",\"wram\":";vec(std::span<const std::uint8_t>(a.bus->bytes->data()+0x1f0000,8192));std::cout<<",\"vram\":";vec(*a.bus->vdc.vram);std::cout<<"}\n";return 0;
 }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}

// Authored adapter around unchanged Gear device bodies. Port queue settling
// invokes original completion methods without asserting CPU slot timing parity.
#include "geargrafx_core.h"
#include "huc6280.h"
#include "huc6270.h"
#include "huc6260.h"
#include "media.h"
#include "memory.h"
#include "vram_latch_probe_support.hpp"
#include <memory>
bool g_mcp_stdio_mode=true;
template<class T,typename T::type M>struct Access{friend typename T::type member(T){return M;}};
#define FIELD_TAG(N,T,F) struct N{using type=T HuC6270::*;friend type member(N);};template struct Access<N,&HuC6270::F>;
#define METHOD_TAG(N,T,F) struct N{using type=T;friend type member(N);};template struct Access<N,&HuC6270::F>;
FIELD_TAG(Latch,u16,m_vram_openbus)
FIELD_TAG(SatPending,u16,m_sat_transfer_pending)
FIELD_TAG(VramPending,u32,m_vram_transfer_pending)
FIELD_TAG(ReadPending,bool,m_pending_memory_read)
FIELD_TAG(WritePending,bool,m_pending_memory_write)
FIELD_TAG(SpriteCount,int,m_sprite_count)
struct Sprites{friend auto member(Sprites);};
template<auto M>struct SpriteAccess{friend auto member(Sprites){return M;}};
template struct SpriteAccess<&HuC6270::m_sprites>;
METHOD_TAG(Read,u16(HuC6270::*)(u16),ReadVRAM)
METHOD_TAG(CompleteRead,void(HuC6270::*)(),ProcessVramRead)
METHOD_TAG(CompleteWrite,void(HuC6270::*)(),ProcessVramWrite)
METHOD_TAG(Fetch,void(HuC6270::*)(),FetchSprites)
METHOD_TAG(Blank,void(HuC6270::*)(),VBlankIRQ)
struct Clock{using type=bool(GeargrafxCore::*)(u32);friend type member(Clock);};template struct Access<Clock,&GeargrafxCore::ClockHardware<false,false,false>>;
static void clock_cpu(void* context,u32 ticks){auto* c=static_cast<GeargrafxCore*>(context);(c->*member(Clock{}))(ticks);}
// Public state omits sprite cache. A narrow authored observer exposes its
// values via the original snapshot stream, without replacing fetch operations.
struct Adapter {
    std::unique_ptr<GeargrafxCore> core;const std::vector<std::uint8_t>& rom;
    HuC6270& v()const{return *core->GetHuC6270_1();}
    void reset(unsigned fast){core=std::make_unique<GeargrafxCore>();core->Init(nullptr);core->GetMedia()->SetConsoleType(GG_CONSOLE_PCE);core->GetHuC6280()->SetResetValue(0);core->GetMemory()->SetResetValues(0,0,0,0);core->GetHuC6260()->SetResetValue(0);v().SetSafeDefaults(false);if(!core->LoadHuCardFromBuffer(rom.data(),rom.size(),"authored-latch.pce"))throw std::runtime_error("ROM load");*core->GetHuC6280()->GetState()->SPEED=fast?1:0;core->GetHuC6280()->SetHardwareClock(clock_cpu,core.get());for(unsigned i=0;i<32768;++i)v().GetVRAM()[i]=latch_probe::pattern(i);}
    void settle(){if(v().*member(ReadPending{}))(v().*member(CompleteRead{}))();if(v().*member(WritePending{}))(v().*member(CompleteWrite{}))();}
    std::vector<std::uint64_t> device()const {auto* s=v().GetState();std::vector<std::uint64_t> out{v().*member(Latch{}),*s->READ_BUFFER,*s->AR,unsigned(*s->SR&63),v().*member(SatPending{}),v().*member(VramPending{})};for(unsigned i=0;i<20;++i)out.push_back(s->R[i]);out.push_back(reset_probe::hash(v().GetVRAM(),32768));out.push_back(reset_probe::hash(v().GetSAT(),256));return out;}
    std::vector<std::uint64_t> cpu()const {auto* s=core->GetHuC6280()->GetState();std::vector<std::uint64_t> out{s->PC->GetValue(),s->A->GetValue(),s->X->GetValue(),s->Y->GetValue(),s->S->GetValue(),s->P->GetValue(),*s->SPEED?3U:12U,core->GetMasterClockCycles()};for(unsigned i=0;i<8;++i)out.push_back(core->GetMemory()->GetMpr(i));return out;}
    std::vector<std::uint64_t> ram()const {return std::vector<std::uint64_t>(core->GetMemory()->GetWorkingRAM(),core->GetMemory()->GetWorkingRAM()+64);}
    void seed(bool sat,unsigned x,unsigned y){(sat?v().GetSAT():v().GetVRAM())[x]=static_cast<u16>(y);}
    unsigned word(unsigned x){return (v().*member(Read{}))(static_cast<u16>(x));}
    unsigned port(unsigned x){auto value=v().ReadRegister(x);settle();return value;}
    void reg(unsigned x,unsigned y){v().WriteRegister(0,x);v().WriteRegister(2,y&255);v().WriteRegister(3,y>>8);settle();}
    void dots(unsigned n){while(n--)v().Clock();}
    void vblank(){(v().*member(Blank{}))();}
    void fetch(){(v().*member(Fetch{}))();}
    std::vector<std::uint64_t> sprites()const {const auto count=v().*member(SpriteCount{});const auto& rows=v().*member(Sprites{});std::vector<std::uint64_t> out{static_cast<unsigned>(count)};for(int i=0;i<count;++i){const auto& r=rows[i];out.push_back(r.x-32+1024);out.push_back(r.index);out.push_back((r.flags&0x800)!=0);for(auto p:r.data)out.push_back(p);}return out;}
    void control(unsigned x){core->GetHuC6260()->WriteRegister(0,x);}
    void advance(unsigned n){while(n){unsigned chunk=n>3?3:n;clock_cpu(core.get(),chunk);n-=chunk;}}
    void instructions(unsigned n){while(n--){auto* c=core->GetHuC6280();auto ticks=c->RunInstruction(),done=c->GetClockedMasterCycles();if(ticks>done)clock_cpu(core.get(),ticks-done);settle();}}
};
int main(int argc,char** argv){try{if(argc!=3)throw std::runtime_error("usage: gear-latch PLAN AUTHORED_ROM");auto rom=reset_probe::rom(argv[2]);Adapter a{nullptr,rom};latch_probe::execute(a,argv[1]);return 0;}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}

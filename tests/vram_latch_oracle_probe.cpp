#include "pce/runtime.hpp"
#include "pce/code_capture.hpp"
#include "vram_latch_probe_support.hpp"
#include <memory>
#include <tuple>
struct Adapter {
    std::unique_ptr<pce::Bus> bus;pce::Cpu c;const std::vector<std::uint8_t>& rom;pce::CodeCapture* capture;
    bool guarded=false;unsigned guard_checks=0;
    void reset(unsigned fast) {guarded=false;bus=std::make_unique<pce::Bus>();bus->configure_hucard(pce::HuCardProfile::base,rom);bus->enable_continuous_video();bus->power_on_cpu(c);c.clock_divisor=fast?3:12;for(unsigned i=0;i<32768;++i)(*bus->vdc.vram)[i]=latch_probe::pattern(i);}
    std::vector<std::uint64_t> device()const {const auto& v=bus->vdc;std::vector<std::uint64_t> out{v.vram_bus_latch,v.read_buffer,v.selected,v.status&63,v.satb_pending,v.vram_dma_pending};for(auto r:v.reg)out.push_back(r);out.push_back(reset_probe::hash(v.vram->data(),32768));out.push_back(reset_probe::hash(v.satb.data(),256));return out;}
    std::vector<std::uint64_t> cpu()const {std::vector<std::uint64_t> out{c.pc,c.a,c.x,c.y,c.sp,c.p,c.clock_divisor,c.ticks};for(auto m:c.mpr)out.push_back(m);return out;}
    std::vector<std::uint64_t> ram()const {std::vector<std::uint64_t> out;for(unsigned i=0;i<64;++i)out.push_back((*bus->bytes)[0x1F0000+i]);return out;}
    void seed(bool sat,unsigned x,unsigned y) {if(sat)bus->vdc.satb[x]=static_cast<std::uint16_t>(y);else(*bus->vdc.vram)[x]=static_cast<std::uint16_t>(y);}
    unsigned word(unsigned x) {return bus->vdc.read_vram(static_cast<std::uint16_t>(x));}
    unsigned port(unsigned x) {return bus->vdc.read(x);}
    void reg(unsigned x,unsigned y) {bus->vdc.write(0,x);bus->vdc.write(2,y&255);bus->vdc.write(3,y>>8);}
    void dots(unsigned count) {while(count--)bus->vdc.dma_tick();}
    void vblank() {bus->vdc.vblank_dma();}
    void fetch() {bus->vdc.fetch_sprite_rows();}
    std::vector<std::uint64_t> sprites()const {const auto& v=bus->vdc;std::vector<std::uint64_t> out{v.sprite_count};for(unsigned i=0;i<v.sprite_count;++i){const auto& row=v.sprite_rows[i];out.push_back(row.x+1024);out.push_back(row.index);out.push_back(row.flip);for(auto p:row.planes)out.push_back(p);}return out;}
    void control(unsigned x) {bus->vdc.write_vce_control(x);bus->vce.write(0,x);}
    void advance(unsigned ticks) {bus->vdc.advance(ticks,&bus->vce);}
    void instructions(unsigned count) {
#ifdef PCE_LATCH_NATIVE_ONLY
        if(!guarded){
            const auto snapshot=[&]{return std::tuple{cpu(),device(),ram(),bus->generation,bus->io_latch,bus->vdc.reads,bus->vdc.writes,bus->vdc.raster.master_ticks};};
            const auto before=snapshot();const auto address=pce::Bus::physical(c,c.pc);const auto original=(*bus->bytes)[address];
            (*bus->bytes)[address]^=255;const auto changed=pce::generated_step(*bus,c,100000000);(*bus->bytes)[address]=original;
            if(changed!=pce::Exit::miss||snapshot()!=before)throw std::runtime_error("changed source guard mutated guest or latch");++guard_checks;
            c.mpr[3]^=1;const auto context=pce::generated_step(*bus,c,100000000);c.mpr[3]^=1;
            if(context!=pce::Exit::miss||snapshot()!=before)throw std::runtime_error("changed full MPR guard mutated guest or latch");++guard_checks;guarded=true;
        }
#endif
        while(count--){pce::CodeCapture::Pending pending;if(capture)pending=capture->before(*bus,c);
#ifdef PCE_LATCH_NATIVE_ONLY
        if(pce::generated_step(*bus,c,100000000)!=pce::Exit::executed)throw std::runtime_error("native miss; interpreter forbidden");
#else
        if(pce::interpret_step(*bus,c,100000000)!=pce::Exit::executed)throw std::runtime_error("interpreter refused");
#endif
        if(capture)capture->after(pending,c);}}
};
int main(int argc,char** argv) {try {if(argc!=3&&argc!=5)throw std::runtime_error("usage: latch-probe PLAN AUTHORED_ROM [--capture NEW]");auto rom=reset_probe::rom(argv[2]);std::unique_ptr<pce::CodeCapture> capture;if(argc==5){if(std::string(argv[3])!="--capture")throw std::runtime_error("capture option");capture=std::make_unique<pce::CodeCapture>(argv[4],65536);}Adapter a{nullptr,{},rom,capture.get()};latch_probe::execute(a,argv[1]);if(capture)capture->finish();std::cerr<<"PCE_VRAM_GUARDS="<<a.guard_checks<<'\n';return 0;}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}

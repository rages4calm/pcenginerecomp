// Authored device and actual CPU fixture. Third-party references are separate processes.
#include "pce/runtime.hpp"
#include "pce/sector.hpp"
#include "pce/code_capture.hpp"
#include "sense_probe_support.hpp"
#include <memory>
struct Medium final:pce::SectorProvider {
    unsigned mode; pce::CdToc geometry;
    explicit Medium(unsigned m):mode(m){geometry.track_count=1;geometry.leadout_lba=20;geometry.tracks[0]={0,static_cast<std::uint8_t>(m==2?0:4)};}
    pce::Sector read(std::uint32_t lba)override {
        if(lba>=20)throw pce::SectorReadError(pce::SectorReadReason::out_of_range,lba,"authored end");
        if(mode==2)throw pce::SectorReadError(pce::SectorReadReason::wrong_data_track,lba,"authored audio");
        if(mode==3)throw pce::SectorReadError(pce::SectorReadReason::unrecoverable_data,lba,"authored opaque read failure");
        if(mode==4)throw pce::SectorReadError(pce::SectorReadReason::media_data_error,lba,"authored validation outcome");
        pce::Sector bytes{};for(unsigned i=0;i<bytes.size();++i)bytes[i]=static_cast<std::uint8_t>(lba+i);return bytes;
    }
    const pce::CdToc& toc()const override{return geometry;}
};
struct Adapter {
    std::unique_ptr<pce::Bus> bus;pce::Cpu cpu;const std::vector<std::uint8_t>& rom;
    void reset(unsigned mode){if(mode>4)throw std::runtime_error("media mode");bus=std::make_unique<pce::Bus>();bus->configure_system_card(pce::SystemCardProfile::super,rom);
        bus->enable_cd_transport();bus->enable_video();bus->enable_interrupts();bus->enable_psg();bus->enable_joypad(false,true);bus->power_on_cpu(cpu);
        if(mode)bus->cd.set_sector_provider(std::make_shared<Medium>(mode));}
    void advance(unsigned n){cpu.ticks+=n;bus->sync(cpu);}
    unsigned signals()const{return bus->cd.scsi.signals;}
    bool busy()const{return signals()&0x80;}bool request()const{return signals()&0x40;}bool input()const{return signals()&8;}
    bool control()const{return signals()&0x10;}bool message()const{return signals()&0x20;}
    void select(){bus->cd.transport_write(0,0);}void write_data(unsigned v){bus->cd.transport_write(1,v);}
    void ack(bool v){bus->cd.transport_write(2,v?128:0);}unsigned read_data(bool automatic){return bus->cd.transport_read(automatic?8:1);}
    void finish_auto_ack(){advance(21);}void warm_reset(){bus->cd.transport_write(4,2);advance(1);bus->cd.transport_write(4,0);advance(1);}
    std::vector<std::uint64_t> pending()const{const auto&s=bus->cd.pending_sense;return{s.key,s.asc,s.ascq,s.fru};}
};
int main(int argc,char** argv) {
    try {
        if(argc!=3&&argc!=5)throw std::runtime_error("usage: sense-probe PLAN AUTHORED_ROM [--capture NEW]");const auto rom=reset_probe::rom(argv[2]);
        std::ifstream plan(argv[1]);if(!plan)throw std::runtime_error("missing plan");std::unique_ptr<pce::CodeCapture> capture;
        if(argc==5){if(std::string(argv[3])!="--capture")throw std::runtime_error("capture option");capture=std::make_unique<pce::CodeCapture>(argv[4],65536);}
        Adapter a{nullptr,{},rom};std::string op;bool first=true;std::cout<<'[';
        while(plan>>op){if(op=="r"){unsigned mode;if(!(plan>>mode))throw std::runtime_error("reset mode");a.reset(mode);}
            else if(!a.bus)throw std::runtime_error("operation before reset");
            else if(op=="c"){unsigned automatic;const auto cdb=sense_probe::command(plan,automatic);sense_probe::start(a,cdb);sense_probe::record(first,cdb,automatic,sense_probe::drain(a,automatic));}
            else if(op=="p")reset_probe::record(first,"pending",a.pending());
            else if(op=="z")a.warm_reset();
            else if(op=="b"){sense_probe::start(a,{3,0,0,0,18,0});a.warm_reset();}
            else if(op=="k"){unsigned offset;if(!(plan>>offset)||offset>8191)throw std::runtime_error("RAM bound");reset_probe::record(first,"ram",{offset,(*a.bus->bytes)[(0xF8<<13)|offset]});}
            else if(op=="g"){
                unsigned end;if(!(plan>>end)||end<0xE100||end>0xFF00)throw std::runtime_error("guest bound");unsigned retired=0;
                do {if(++retired>200000)throw std::runtime_error("bounded authored guest did not complete");pce::CodeCapture::Pending pending;if(capture)pending=capture->before(*a.bus,a.cpu);
#ifdef PCE_SENSE_NATIVE_ONLY
                    if(pce::generated_step(*a.bus,a.cpu,100000000)!=pce::Exit::executed)throw std::runtime_error("native miss; fallback forbidden");
#else
                    if(pce::interpret_step(*a.bus,a.cpu,100000000)!=pce::Exit::executed)throw std::runtime_error("guest interpreter refused");
#endif
                    if(capture)capture->after(pending,a.cpu);
                }while(a.cpu.pc!=end);
                std::vector<std::uint64_t> state{a.cpu.pc,a.cpu.a,a.cpu.x,a.cpu.y,a.cpu.sp,a.cpu.p,a.cpu.clock_divisor,a.cpu.ticks};
                for(auto m:a.cpu.mpr)state.push_back(m);state.push_back(retired);state.push_back(a.bus->cd.sense_commands);state.push_back(a.bus->cd.sense_errors);
                reset_probe::record(first,"guest",state);
            }else throw std::runtime_error("unknown operation");}
        std::cout<<"]\n";if(capture)capture->finish();return 0;
    }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}
}

// Authored transport supervisor. The Gear adapter includes only this shared
// supervision code; its original device implementation is a separate binary.
#include <filesystem>
#include <string>
#ifndef PCE_READ_HEAD_GEAR
#include "pce/runtime.hpp"
#include "pce/sector.hpp"
#include "pce/code_capture.hpp"
#include "scsi_fixture.hpp"
#include "sense_probe_support.hpp"
#include <memory>
#include <tuple>

struct HeadAdapter {
    std::unique_ptr<pce::Bus> bus;
    pce::Cpu cpu;
    const std::vector<std::uint8_t>& rom;
    const char* cue;
    bool native;
    unsigned divisor;
    pce::CodeCapture capture;
    std::uint64_t retired=0, guards=0;
    HeadAdapter(const std::vector<std::uint8_t>& image,const char* path,const std::string& tier,
                unsigned speed,const char* output):rom(image),cue(path),native(tier=="native"),
                divisor(speed),capture(output,1024) {}
    unsigned site(unsigned opcode,unsigned address=0) const {
        for(const auto& item:scsi_cases) if(item.op==opcode && item.address==address)return item.pc;
        throw std::runtime_error("Missing authored head transport site");
    }
    void execute(unsigned opcode,unsigned address=0,int value=-1) {
        cpu.pc=static_cast<std::uint16_t>(site(opcode,address));
        if(value>=0)cpu.a=static_cast<std::uint8_t>(value);
        const auto pending=capture.before(*bus,cpu);
        const auto result=native?pce::generated_step(*bus,cpu,UINT64_MAX):pce::interpret_step(*bus,cpu,UINT64_MAX);
        if(result!=pce::Exit::executed)throw std::runtime_error("Head transport opcode did not execute directly");
        capture.after(pending,cpu);++retired;
    }
    void reset() {
        bus=std::make_unique<pce::Bus>();bus->configure_system_card(pce::SystemCardProfile::super,rom);
        bus->enable_cd_transport();bus->enable_adpcm();bus->enable_video();bus->enable_interrupts();bus->enable_psg();
        bus->cd.set_sector_provider(pce::open_sector_provider(cue));
        for(auto [address,value]:scsi_program)(*bus->bytes)[address]=value;
        cpu=pce::Cpu{};cpu.mpr=scsi_mpr;cpu.clock_divisor=divisor;cpu.p=pce::I;
        if(native && !guards) {
            cpu.pc=static_cast<std::uint16_t>(site(0x8D,0x1800));
            auto guard=[&](pce::Cpu trial,std::uint64_t deadline,pce::Exit expected) {
                const auto before=std::tuple{trial.pc,trial.a,trial.p,trial.ticks,trial.native_steps,trial.interpreter_steps,trial.guard_misses};
                const auto head=bus->cd.scsi.current_lba;
                const auto signals=bus->cd.scsi.signals;
                if(pce::generated_step(*bus,trial,deadline)!=expected || before!=std::tuple{trial.pc,trial.a,trial.p,trial.ticks,trial.native_steps,trial.interpreter_steps,trial.guard_misses}
                    || head!=bus->cd.scsi.current_lba || signals!=bus->cd.scsi.signals || bus->cd.scsi.master_ticks)
                    throw std::runtime_error("Head source/deadline guard was impure");
                ++guards;
            };
            guard(cpu,cpu.ticks,pce::Exit::budget);
            auto wrong=cpu;wrong.mpr[3]^=1;guard(wrong,UINT64_MAX,pce::Exit::miss);
            for(unsigned byte:{0U,2U}) {
                const auto physical=pce::Bus::physical(cpu,cpu.pc+byte);const auto old=(*bus->bytes)[physical];
                (*bus->bytes)[physical]^=255;guard(cpu,UINT64_MAX,pce::Exit::miss);(*bus->bytes)[physical]=old;
            }
        }
    }
    void advance(unsigned n) {cpu.ticks+=n;bus->sync(cpu);}
    unsigned signals()const{return bus->cd.scsi.signals;}
    bool busy()const{return signals()&0x80;}bool request()const{return signals()&0x40;}
    bool input()const{return signals()&8;}bool control()const{return signals()&0x10;}bool message()const{return signals()&0x20;}
    void select(){execute(0x8D,0x1800,0);}void write_data(unsigned value){execute(0x8D,0x1801,value);}
    void ack(bool value){execute(0x8D,0x1802,value?128:0);}
    unsigned read_data(bool automatic){execute(0xAD,automatic?0x1808:0x1801);return cpu.a;}
    void finish_auto_ack(){execute(0xEA);execute(0xEA);advance(21);}
    unsigned head()const{return bus->cd.scsi.current_lba;}
    void finish(){capture.finish();}
};
#else
struct HeadAdapter:GearHeadAdapter {
    std::uint64_t retired=0,guards=0;
    HeadAdapter(const std::vector<std::uint8_t>& image,const char* path,const std::string&,
                unsigned,const char*):GearHeadAdapter{nullptr,image,path} {}
    void reset(){GearHeadAdapter::reset(1);}
    unsigned head()const{return core->GetCDROMMedia()->GetCurrentSector();}
    void finish(){}
};
#endif

sense_probe::Reply head_drain(HeadAdapter& a,bool automatic) {
    sense_probe::Reply result;unsigned polls=0;
    while(a.busy()) {
        if(++polls>200000)throw std::runtime_error("Bounded head response exceeded");
        if(!a.request()){a.advance(1000);continue;}
        if(!a.input())throw std::runtime_error("Head response direction differs");
        const bool data=!a.control();const auto byte=a.read_data(automatic&&data);
        if(data){if(result.data.size()>=8192)throw std::runtime_error("Bounded head payload exceeded");result.data.push_back(byte);}
        else if(a.message()){if(result.message<=255)throw std::runtime_error("Duplicate head message");result.message=byte;}
        else {if(result.status<=255)throw std::runtime_error("Duplicate head status");result.status=byte;}
        if(automatic&&data)a.finish_auto_ack();
        else {a.ack(true);a.advance(1);a.ack(false);a.advance(1);}
    }
    if(result.status>255||result.message>255)throw std::runtime_error("Missing head status/message");
    return result;
}

int main(int argc,char** argv) {
    try {
        if(argc!=8)throw std::runtime_error("read-head PLAN AUTHORED_ROM AUTHORED_CUE TIER SPEED NEW_CAPTURE NEW_REPORT");
        const std::string tier=argv[4];
#ifndef PCE_READ_HEAD_GEAR
        if(tier!="native"&&tier!="interpreter")throw std::runtime_error("Explicit CPU tier required");
#else
        if(tier!="gear")throw std::runtime_error("Explicit original Gear tier required");
#endif
        const std::string speed_text=argv[5];if(speed_text!="3"&&speed_text!="12")throw std::runtime_error("Explicit supported speed required");
        if(std::filesystem::exists(argv[7]))throw std::runtime_error("New head report required");
        const auto rom=reset_probe::rom(argv[2]);HeadAdapter a(rom,argv[3],tier,std::stoul(speed_text),argv[6]);
        std::ifstream plan(argv[1]);if(!plan)throw std::runtime_error("Missing head plan");
        std::vector<unsigned> active;unsigned automatic=0,rows=0,cases=0;bool first=true,ready=false;std::string op;
        std::cout<<'[';
        while(plan>>op) {
            if(op=="r"){a.reset();ready=true;active.clear();++cases;}
            else {
                if(!ready)throw std::runtime_error("Head operation before reset");
                if(op=="c"||op=="s") {
                    active=sense_probe::command(plan,automatic);sense_probe::start(a,active);
                    if(op=="c"){sense_probe::record(first,active,automatic,head_drain(a,automatic));++rows;active.clear();}
                } else if(op=="d") {
                    if(active.empty())throw std::runtime_error("Drain without outstanding command");
                    sense_probe::record(first,active,automatic,head_drain(a,automatic));++rows;active.clear();
                } else if(op=="w")sense_probe::wait_request(a);
                else if(op=="a") {unsigned ticks;if(!(plan>>ticks)||ticks>10000000)throw std::runtime_error("Bounded head wait required");a.advance(ticks);}
                else if(op=="h") {
                    const auto before=a.head();if(before!=a.head())throw std::runtime_error("Head inspection changed state");
                    reset_probe::record(first,"head",{before});++rows;
                } else throw std::runtime_error("Unknown head operation");
            }
        }
        if(!active.empty())throw std::runtime_error("Incomplete outstanding head command");
        std::cout<<"]\n";a.finish();
        std::ofstream report(argv[7]);if(!report)throw std::runtime_error("Head report creation failed");
        report<<"{\"schema\":1,\"tier\":\""<<tier<<"\",\"divisor\":"<<speed_text<<",\"retired_instructions\":"<<a.retired<<",\"pure_guards\":"<<a.guards<<",\"cases\":"<<cases<<",\"records\":"<<rows<<"}\n";
        return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}

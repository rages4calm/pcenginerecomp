#include "pce/runtime.hpp"
#include "pce/code_capture.hpp"
#include "state_route_input_support.hpp"
#include <filesystem>

int main(int argc,char** argv) {
    try {
        if(argc!=5)throw std::runtime_error("usage: input-probe PLAN CODE NEWCAPTURE NEWEXECUTION");
        if(std::filesystem::exists(argv[4]))throw std::runtime_error("execution exists");
        auto plan=input_probe::plan(argv[1]);auto code=input_probe::code(argv[2]);
        pce::Bus bus;pce::Cpu cpu;cpu.pc=0x2800;cpu.clock_divisor=plan.divisor;
        bus.kind[248]=pce::BankKind::ram;bus.load(0x1F0800,code.data(),code.size());bus.enable_joypad(true,false);
        pce::CodeCapture capture(argv[3],65536);bool first=true;unsigned held=0;
        std::cout<<'[';
        for(unsigned index=0;index<plan.count;++index) {
            if(plan.held.contains(index)){held=plan.held.at(index);bus.joypad.set_pressed(0,held);}
            auto row=input_probe::identity(index,cpu.pc,cpu.mpr,[&](unsigned pc){auto b=bus.peek(pce::Bus::physical(cpu,pc));if(!b)throw std::runtime_error("source peek");return *b;});
            row.insert(row.end(),{cpu.a,cpu.p,cpu.ticks,bus.joypad.latched,bus.joypad.pads[0].pressed});
            const auto pending=capture.before(bus,cpu);
#ifdef PCE_STATE_ROUTE_INPUT_NATIVE
            if(pce::generated_step(bus,cpu,10000000)!=pce::Exit::executed)throw std::runtime_error("native-only input step refused");
#else
            if(pce::interpret_step(bus,cpu,10000000)!=pce::Exit::executed)throw std::runtime_error("interpreted input step refused");
#endif
            capture.after(pending,cpu);
            row.insert(row.end(),{cpu.pc,cpu.a,cpu.p,cpu.ticks,bus.joypad.latched,(*bus.bytes)[0x1F0400]});
            reset_probe::record(first,"instruction",row);
        }
        std::vector<std::uint64_t> ram;for(unsigned i=0;i<64;++i)ram.push_back((*bus.bytes)[0x1F0400+i]);
        reset_probe::record(first,"ram",ram);std::cout<<"]\n";capture.finish();
        std::ofstream report(argv[4]);if(!report)throw std::runtime_error("execution output failed");
        report<<"{\"runtime_abi\":"<<pce::abi_version<<",\"native_steps\":"<<cpu.native_steps
            <<",\"interpreter_steps\":"<<cpu.interpreter_steps<<",\"guard_misses\":"<<cpu.guard_misses
            <<",\"joypad_reads\":"<<bus.joypad.reads<<",\"joypad_writes\":"<<bus.joypad.writes<<"}\n";
        return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}

// Authored storage observations; no firmware, title data or guest execution.
#include "pce/code_capture.hpp"
#include <chrono>
#include <fstream>
#include <iostream>
#include <iterator>

namespace {
unsigned checks=0;
void require(bool value,const char* message) {++checks;if(!value)throw std::runtime_error(message);}
bool has(const std::string& value,const std::string& fragment) {return value.find(fragment)!=std::string::npos;}
template<class F> void rejects(F action) {bool threw=false;try{action();}catch(const pce::Fault&){threw=true;}require(threw,"capture accepted invalid request");}
std::string contents(const std::filesystem::path& path) {
    std::ifstream stream(path,std::ios::binary);return {std::istreambuf_iterator<char>(stream),{}};
}
void retire(pce::CodeCapture& capture,pce::Bus& bus,pce::Cpu& cpu,bool native) {
    const auto pending=capture.before(bus,cpu);
    if(native)++cpu.native_steps;else ++cpu.interpreter_steps;
    capture.after(pending,cpu);
}
void mixed(const std::filesystem::path& path,bool inspect) {
    pce::Bus bus;bus.kind[0]=pce::BankKind::ram;bus.kind[1]=pce::BankKind::ram;
    pce::Cpu cpu;cpu.mpr.fill(0);cpu.pc=0x100;(*bus.bytes)[0x100]=0xA9;(*bus.bytes)[0x101]=1;
    pce::CodeCapture capture(path,2);
    require(has(capture.summary_json(),"\"retired_instructions\":0"),"nonempty fresh capture");
    retire(capture,bus,cpu,true); // First full identity.
    (*bus.bytes)[0x101]=2;retire(capture,bus,cpu,false); // Mutated operand, same PC/MPR.
    if(inspect) {
        const auto stable=capture.summary_json();
        const auto first=capture.sources_json(2,0,1),second=capture.sources_json(2,1,256);
        require(has(first,"\"source_id\":0,\"pc\":256,\"mpr\":[0,0,0,0,0,0,0,0],\"physical\":[256,257],\"native_hits\":1,\"interpreted_hits\":0"),"first full identity/tier mismatch");
        require(has(second,"\"source_id\":1,\"pc\":256")&&has(second,"\"native_hits\":0,\"interpreted_hits\":1"),"mutation identity merged");
        require(!has(first,"\"data\"")&&!has(second,"\"data\""),"live source bytes disclosed");
        require(has(first,"\"next_offset\":1,\"done\":false")&&has(second,"\"next_offset\":2,\"done\":true"),"page boundaries mismatch");
        require(capture.summary_json()==stable&&contents(path).empty(),"inspection mutated capture or finalized file");
        rejects([&]{capture.sources_json(1,0,1);});
        rejects([&]{capture.sources_json(2,3,1);});
        rejects([&]{capture.sources_json(2,0,0);});
        rejects([&]{capture.sources_json(2,0,257);});
        require(has(capture.sources_json(2,2,256),"\"sources\":[]"),"terminal empty page rejected");
    }
    cpu.mpr[7]=1;retire(capture,bus,cpu,true); // Even an otherwise unused MPR is identity.
    retire(capture,bus,cpu,false); // Capacity loss counts both execution tiers.
    cpu.mpr[7]=0;(*bus.bytes)[0x101]=1;retire(capture,bus,cpu,false); // Retained hit after capacity.
    cpu.mpr[0]=0xFF;retire(capture,bus,cpu,true);retire(capture,bus,cpu,false); // Never peek MMIO.
    const auto summary=capture.summary_json();
    require(has(summary,"\"identity_count\":2,\"retired_instructions\":7,\"native_instructions\":3,\"interpreted_instructions\":4,\"retained_native_instructions\":1,\"retained_interpreted_instructions\":2,\"dropped_instructions\":2,\"unreadable_instructions\":2,\"complete\":false"),"loss/tier conservation mismatch");
    const auto pending=capture.before(bus,cpu);capture.after(pending,cpu);
    require(summary==capture.summary_json(),"zero retirement creates an observation");
    if(inspect)rejects([&]{capture.sources_json(2,0,1);});
    capture.finish();
}
}
int main() {
    const auto directory=std::filesystem::temp_directory_path()/("pce-capture-test-"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    const auto a=directory/"observed.json",b=directory/"plain.json",c=directory/"pages.json";
    try {
        require(std::filesystem::create_directory(directory),"cannot create isolated capture fixture");
        mixed(a,true);mixed(b,false);
        require(contents(a)==contents(b),"live inspection changed finalized capture byte contract");
        {
            pce::Bus bus;bus.kind[0]=pce::BankKind::ram;bus.kind[1]=pce::BankKind::ram;
            bus.kind[2]=pce::BankKind::ram;
            pce::Cpu cpu;cpu.mpr.fill(0);cpu.mpr[0]=1;cpu.mpr[1]=2;
            // Three-byte fetch spans a logical bank and physical mapping edge.
            cpu.pc=0x1FFF;(*bus.bytes)[0x3FFF]=0x4C;(*bus.bytes)[0x4000]=0;(*bus.bytes)[0x4001]=0;
            pce::CodeCapture capture(c,258);retire(capture,bus,cpu,true);
            for(unsigned i=0;i<257;++i){cpu.pc=static_cast<std::uint16_t>(0x100+i);(*bus.bytes)[0x2100+i]=0xEA;retire(capture,bus,cpu,false);}
            require(has(capture.sources_json(258,0,256),"\"physical\":[16383,16384,16385]"),"per-byte bank mapping lost");
            require(has(capture.sources_json(258,0,256),"\"next_offset\":256,\"done\":false"),"maximum page lost entries");
            require(has(capture.sources_json(258,256,256),"\"source_id\":257")&&has(capture.sources_json(258,256,256),"\"next_offset\":258,\"done\":true"),"last page lost entries");
            capture.finish();
        }
        std::filesystem::remove(a);std::filesystem::remove(b);std::filesystem::remove(c);std::filesystem::remove(directory);
        std::cout<<checks<<" code-capture live summary/page/loss checks passed\n";return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}

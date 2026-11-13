// Original arithmetic fixture; host resets/presets are declared preconditions.
#include "pce/runtime.hpp"
#include "pce/code_capture.hpp"
#include "cases.hpp"
#include <array>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <memory>
#include <vector>
static void require(bool value,const char* message){if(!value)throw std::runtime_error(message);}
static auto path(const char* s){return std::filesystem::path(std::u8string(reinterpret_cast<const char8_t*>(s)));}
int main(int argc,char** argv){try{
 require(argc==4,"usage: eval-probe card mode capture");const std::string mode=argv[2];
 const bool matrix=mode=="matrix"||mode=="matrix-reference",reference=mode=="reference"||mode=="matrix-reference";
 const bool value=mode=="value-change",bank=mode=="bank-change",source=mode=="source-change";
 require(matrix||reference||value||bank||source||mode=="main","invalid mode");
 std::ifstream file(path(argv[1]),std::ios::binary);std::vector<std::uint8_t> image((std::istreambuf_iterator<char>(file)),{});
 require(image.size()==32768,"image size");if(value)image[0x4180]=0x19;if(bank)image[0x100]=0xF3;if(source)image[0x4201]=0x70;
 pce::CodeCapture capture(path(argv[3]),4096);std::uint64_t native=0,interpreted=0,guards=0;
 for(unsigned n=0;n<(matrix?280U:1U);++n){auto bus=std::make_unique<pce::Bus>();pce::Cpu cpu;
  bus->configure_hucard(pce::HuCardProfile::base,image);bus->power_on_cpu(cpu);const auto& c=cases[n];
  if(matrix){cpu.mpr={0,248,0,0,0,0,0,0};cpu.pc=c.pc;cpu.p=0x44;}
  const unsigned steps=matrix?c.steps:bank?7U:source?14U:24U;
  for(unsigned i=0;i<steps;++i){const auto before=capture.before(*bus,cpu);
   require(pce::step(*bus,cpu,100000,reference?pce::ExecutionPolicy::interpreter_only:pce::ExecutionPolicy::native_only)==pce::Exit::executed,"unexpected refusal");capture.after(before,cpu);}
  if(bank||source){require(cpu.pc==(bank?0xE00D:0xE200),"guard endpoint");
   const auto ticks=cpu.ticks,cycles=cpu.cycles;const auto generation=bus->generation;
   const auto memory=std::make_unique<std::array<std::uint8_t,0x200000>>(*bus->bytes);
   require(pce::step(*bus,cpu,100000,pce::ExecutionPolicy::native_only)==pce::Exit::miss,"changed mapping/source accepted");
   require(cpu.ticks==ticks&&cpu.cycles==cycles&&cpu.native_steps==steps&&cpu.interpreter_steps==0&&cpu.guard_misses==1&&bus->generation==generation&&*bus->bytes==*memory,"guard effects");
  }else if(matrix){require(cpu.pc==c.end&&cpu.a==c.a&&cpu.x==7&&cpu.y==0&&cpu.p==c.p&&cpu.sp==0&&cpu.cycles==c.cycles&&cpu.ticks==12*c.cycles&&cpu.mpr==std::array<std::uint8_t,8>{0,248,0,0,0,0,0,0},"matrix CPU/clocks mismatch");
  }else{require(cpu.pc==0xE01B&&cpu.a==(value?0x31:0x41)&&cpu.x==2&&cpu.y==3&&cpu.sp==0&&cpu.p==5&&cpu.cycles==88&&cpu.ticks==1056&&cpu.mpr==std::array<std::uint8_t,8>{0,248,1,0,0,0,0,2},"main CPU/clocks mismatch");}
  require(cpu.native_steps==(reference?0U:steps)&&cpu.interpreter_steps==(reference?steps:0U)&&cpu.guard_misses==((bank||source)?1U:0U),"tier counts");
  for(unsigned i=0;i<8192;++i){unsigned expected=matrix?(i==7?c.ram:0):0;
   if(!matrix&&!bank){if(i==0x100)expected=0xE0;if(i==0x1FF)expected=0x1A;
    if(!source){if(i==0)expected=value?0x31:0x41;if(i==1)expected=2;if(i==2)expected=3;}}
   const auto actual=bus->peek(0x1F0000+i);require(actual&&*actual==expected,"full WRAM mismatch");}
  native+=cpu.native_steps;interpreted+=cpu.interpreter_steps;guards+=cpu.guard_misses;
 }
 capture.finish();std::cout<<"{\"passed\":true,\"cases\":"<<(matrix?280:1)<<",\"native\":"<<native<<",\"interpreted\":"<<interpreted<<",\"guards\":"<<guards<<"}\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}

// Original conditional matrix. Host resets/presets are explicit preconditions.
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
static void require(bool v,const char* m){if(!v)throw std::runtime_error(m);}
static auto path(const char* s){return std::filesystem::path(std::u8string(reinterpret_cast<const char8_t*>(s)));}
int main(int argc,char** argv){try{
 require(argc==4,"usage: branch-probe card mode capture");const std::string mode=argv[2];
 const bool matrix=mode=="matrix"||mode=="matrix-reference",reference=mode=="reference"||mode=="matrix-reference";
 const bool value=mode=="value-change",bank=mode=="bank-change",overflow=mode=="overflow-change",sign=mode=="sign-change",source=mode=="source-change";
 require(matrix||reference||value||bank||overflow||sign||source||mode=="main","invalid mode");
 std::ifstream f(path(argv[1]),std::ios::binary);std::vector<std::uint8_t> image((std::istreambuf_iterator<char>(f)),{});
 require(image.size()==32768,"image size");if(value)image[0x4180]=0x40;if(bank)image[0x100]=1;if(overflow)image[0x101]=0;if(sign)image[0x4180]=0xFF;if(source)image[0x4201]=0x81;
 pce::CodeCapture capture(path(argv[3]),4096);std::uint64_t native=0,interpreted=0,guards=0;
 for(unsigned n=0;n<(matrix?96U:1U);++n){auto bus=std::make_unique<pce::Bus>();pce::Cpu cpu;
  bus->configure_hucard(pce::HuCardProfile::base,image);bus->power_on_cpu(cpu);const auto& c=cases[n];
  if(matrix){cpu.mpr=c.bit?std::array<std::uint8_t,8>{0,0,0,248,0,0,0,0}:std::array<std::uint8_t,8>{0,248,0,0,0,0,0,0};cpu.pc=c.pc;cpu.p=4;}
  const unsigned steps=matrix?c.steps:bank?5U:overflow?14U:sign?22U:source?18U:28U;
  for(unsigned i=0;i<steps;++i){const auto before=capture.before(*bus,cpu);
   require(pce::step(*bus,cpu,100000,reference?pce::ExecutionPolicy::interpreter_only:pce::ExecutionPolicy::native_only)==pce::Exit::executed,"unexpected refusal");capture.after(before,cpu);}
  if(bank||overflow||sign||source){const auto pc=bank?bad_bank:overflow?bad_overflow:sign?bad_sign:0xE200;
   require(cpu.pc==pc,"guard endpoint");const auto ticks=cpu.ticks,cycles=cpu.cycles;const auto generation=bus->generation;
   const auto memory=std::make_unique<std::array<std::uint8_t,0x200000>>(*bus->bytes);
   require(pce::step(*bus,cpu,100000,pce::ExecutionPolicy::native_only)==pce::Exit::miss,"omitted/changed source accepted");
   require(cpu.ticks==ticks&&cpu.cycles==cycles&&cpu.native_steps==steps&&cpu.interpreter_steps==0&&cpu.guard_misses==1&&bus->generation==generation&&*bus->bytes==*memory,"guard effects");
  }else if(matrix){const auto m=c.bit?std::array<std::uint8_t,8>{0,0,0,248,0,0,0,0}:std::array<std::uint8_t,8>{0,248,0,0,0,0,0,0};
   require(cpu.pc==c.end&&cpu.a==c.a&&cpu.x==c.x&&cpu.y==3&&cpu.p==c.p&&cpu.sp==0&&cpu.cycles==c.cycles&&cpu.ticks==12*c.cycles&&cpu.mpr==m,"matrix CPU/clocks mismatch");
  }else{require(cpu.pc==main_end&&cpu.a==0x42&&cpu.x==2&&cpu.y==3&&cpu.p==0x44&&cpu.sp==0&&cpu.cycles==107&&cpu.ticks==1284&&cpu.mpr==std::array<std::uint8_t,8>{0,248,1,0,0,0,0,2},"main CPU/clocks mismatch");}
  const bool refused=bank||overflow||sign||source;
  require(cpu.native_steps==(reference?0U:steps)&&cpu.interpreter_steps==(reference?steps:0U)&&cpu.guard_misses==(refused?1U:0U),"tier counts");
  for(unsigned i=0;i<8192;++i){unsigned expected=matrix?(i==0?c.x:0):0;
   if(!matrix&&!bank&&!overflow){if(i==0x100)expected=0xE0;if(i==0x1FF)expected=(main_end-1)&255;
    if(!source&&!sign){if(i==0)expected=0x42;if(i==1)expected=2;if(i==2)expected=3;if(i==3)expected=value?0xBF:0xBE;}}
   const auto actual=bus->peek(0x1F0000+i);require(actual&&*actual==expected,"full WRAM mismatch");}
  native+=cpu.native_steps;interpreted+=cpu.interpreter_steps;guards+=cpu.guard_misses;
 }
 capture.finish();std::cout<<"{\"passed\":true,\"cases\":"<<(matrix?96:1)<<",\"native\":"<<native<<",\"interpreted\":"<<interpreted<<",\"guards\":"<<guards<<"}\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}

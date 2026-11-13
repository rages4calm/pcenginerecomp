// Original sequential-copy and live-pointer qualification; no game bytes.
#include "pce/runtime.hpp"
#include "pce/code_capture.hpp"
#include "cases.hpp"
#include <array>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <memory>
#include <string>
#include <vector>
static void require(bool v,const char* s){if(!v)throw std::runtime_error(s);}
static auto path(const char* s){return std::filesystem::path(std::u8string(reinterpret_cast<const char8_t*>(s)));}
int main(int argc,char** argv){try{
 require(argc==4,"usage: memory-probe card mode capture");const std::string mode=argv[2];
 const bool matrix=mode=="matrix"||mode=="matrix-reference",reference=mode=="reference"||mode=="matrix-reference";
 const bool changed=mode=="changed-pointer",indices=mode=="indices";
 require(matrix||reference||changed||indices||mode=="main","invalid mode");
 std::ifstream f(path(argv[1]),std::ios::binary);std::vector<std::uint8_t> image((std::istreambuf_iterator<char>(f)),{});
 require(image.size()==32768||image.size()==0x280000,"image size");
 const auto profile=image.size()==32768?pce::HuCardProfile::base:pce::HuCardProfile::sf2;
 const std::array<std::uint8_t,8> mapped{0,248,251,3,0,0,0,0},final_mapped{0,248,251,3,0,0,0,2};
 pce::CodeCapture capture(path(argv[3]),8192);std::uint64_t native=0,interpreted=0,guards=0;
 const unsigned count=matrix?case_count:indices?256:1;
 for(unsigned n=0;n<count;++n){auto bus=std::make_unique<pce::Bus>();pce::Cpu cpu;
  bus->configure_hucard(profile,image);bus->power_on_cpu(cpu);
  if(matrix){cpu.mpr=mapped;cpu.pc=cases[n].pc;cpu.p=4;}
  else if(indices)cpu.x=static_cast<std::uint8_t>(n);
  const auto steps=matrix?cases[n].steps:changed?pointer_steps:main_steps;
  for(unsigned i=0;i<steps;++i){
   if(changed&&cpu.pc==jump_pc)bus->write(cpu,0x2000,0xE3);
   const auto before=capture.before(*bus,cpu);
   require(pce::step(*bus,cpu,100000,reference?pce::ExecutionPolicy::interpreter_only:pce::ExecutionPolicy::native_only)==pce::Exit::executed,"unexpected refusal");
   capture.after(before,cpu);
  }
  if(changed){
   require(cpu.pc==0xE3E2&&cpu.a==0xE2&&cpu.x==0&&cpu.y==0&&cpu.p==6&&cpu.sp==0,"changed pointer endpoint");
   const auto memory=std::make_unique<std::array<std::uint8_t,0x200000>>(*bus->bytes);
   const auto cycles=cpu.cycles,ticks=cpu.ticks;const auto generation=bus->generation;
   require(pce::step(*bus,cpu,100000,pce::ExecutionPolicy::native_only)==pce::Exit::miss,"omitted live target accepted");
   require(*memory==*bus->bytes&&cycles==cpu.cycles&&ticks==cpu.ticks&&generation==bus->generation,"guard guest effects");
  }else{
   const unsigned expected_p=4;
   require(cpu.pc==(matrix?cases[n].end:main_end)&&cpu.a==(matrix?0x55:0x42)&&cpu.x==(matrix?0x33:indices?n:0)&&cpu.y==(matrix?0x44:0)&&cpu.p==expected_p&&cpu.sp==0,"CPU endpoint");
   const auto cycles=matrix?cases[n].cycles:main_cycles;
   require(cpu.cycles==cycles&&cpu.ticks==12*cycles&&cpu.mpr==(matrix?mapped:final_mapped),"clocks/mapping");
  }
  require(cpu.native_steps==(reference?0U:steps)&&cpu.interpreter_steps==(reference?steps:0U)&&cpu.guard_misses==(changed?1U:0U),"execution tiers");
  for(unsigned i=0;i<8192;++i){unsigned expected=matrix?case_ram[n][i]:main_ram[i];
   if(indices&&i==0x100)expected=n;
   if(changed){if(i==0)expected=0xE3;if(i==1)expected=0xE2;}
   const auto actual=bus->peek(0x1F0000+i);
   require(actual&&*actual==expected,("case "+std::to_string(n)+" RAM offset "+std::to_string(i)).c_str());
  }
  native+=cpu.native_steps;interpreted+=cpu.interpreter_steps;guards+=cpu.guard_misses;
 }
 capture.finish();std::cout<<"{\"passed\":true,\"cases\":"<<count<<",\"native\":"<<native<<",\"interpreted\":"<<interpreted<<",\"guards\":"<<guards<<"}\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}

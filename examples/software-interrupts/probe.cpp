// Original nested software-interrupt qualification; no game bytes.
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
 require(argc==4,"usage: software-probe card mode capture");const std::string mode=argv[2];
 const bool matrix=mode=="matrix"||mode=="matrix-reference",reference=mode=="reference"||mode=="matrix-reference";
 const bool vector_changed=mode=="changed-vector",status_changed=mode=="changed-status",changed=vector_changed||status_changed;
 require(matrix||reference||changed||mode=="main","invalid mode");
 std::ifstream f(path(argv[1]),std::ios::binary);std::vector<std::uint8_t> image((std::istreambuf_iterator<char>(f)),{});
 require(image.size()==32768,"image size");
 const auto profile=pce::HuCardProfile::base;
 const std::array<std::uint8_t,8> mapped{0,248,251,0,0,0,0,3},final_mapped{0,251,2,0,0,0,0,248};
 pce::CodeCapture capture(path(argv[3]),16384);std::uint64_t native=0,interpreted=0,guards=0;
 const unsigned count=matrix?case_count*4:1;
 for(unsigned n=0;n<count;++n){const unsigned case_index=status_changed?1:n/4;const auto& c=cases[case_index];const unsigned initial_sp=std::array<unsigned,4>{0,1,254,255}[n%4];auto bus=std::make_unique<pce::Bus>();pce::Cpu cpu;
  bus->configure_hucard(profile,image);bus->power_on_cpu(cpu);
  if(matrix||status_changed){cpu.mpr=mapped;cpu.pc=c.pc;cpu.p=4;cpu.sp=static_cast<std::uint8_t>(initial_sp);}
  const auto steps=status_changed?c.steps-1:matrix?c.steps:vector_changed?negative_steps:main_steps;
  for(unsigned i=0;i<steps;++i){
   if(vector_changed&&cpu.pc==write_pc)bus->write(cpu,0x3FF6,0x80);
   if(status_changed&&cpu.pc==0xC706)bus->write(cpu,static_cast<std::uint16_t>(0x2100+static_cast<std::uint8_t>(cpu.sp+1)),0x10);
   const auto before=capture.before(*bus,cpu);
   require(pce::step(*bus,cpu,100000,reference?pce::ExecutionPolicy::interpreter_only:pce::ExecutionPolicy::native_only)==pce::Exit::executed,"unexpected refusal");
   capture.after(before,cpu);
  }
  if(changed){
   if(status_changed)require(cpu.pc==c.pc+12&&cpu.a==1&&cpu.x==1&&cpu.y==1&&cpu.p==0&&cpu.sp==0&&cpu.mpr==mapped,"changed saved status endpoint");
   else require(cpu.pc==negative_pc&&cpu.a==251&&cpu.x==3&&cpu.y==4&&cpu.p==0x85&&cpu.sp==243&&cpu.mpr==std::array<std::uint8_t,8>{0,251,251,0,0,0,0,248},"changed vector endpoint");
   const auto memory=std::make_unique<std::array<std::uint8_t,0x200000>>(*bus->bytes);
   const auto cycles=cpu.cycles,ticks=cpu.ticks;const auto generation=bus->generation;const auto old_cpu=cpu;
   require(pce::step(*bus,cpu,100000,pce::ExecutionPolicy::native_only)==pce::Exit::miss,"omitted live target accepted");
   require(cpu.pc==old_cpu.pc&&cpu.a==old_cpu.a&&cpu.x==old_cpu.x&&cpu.y==old_cpu.y&&cpu.sp==old_cpu.sp&&cpu.p==old_cpu.p&&cpu.mpr==old_cpu.mpr,"guard CPU effects");
   require(*memory==*bus->bytes&&cycles==cpu.cycles&&ticks==cpu.ticks&&generation==bus->generation,"guard guest effects");
  }else{
   const unsigned expected_p=matrix?c.p:12;
   require(cpu.pc==(matrix?c.end:main_end)&&cpu.a==(matrix?c.a:0x10)&&cpu.x==(matrix?c.x:3)&&cpu.y==(matrix?c.y:4)&&cpu.p==expected_p&&cpu.sp==(matrix?initial_sp:0),"CPU endpoint");
   const auto cycles=matrix?c.cycles:main_cycles;
   auto expected_mpr=matrix?mapped:final_mapped;
   require(cpu.cycles==cycles&&cpu.ticks==12*cycles&&cpu.mpr==expected_mpr,"clocks/mapping/latch");
  }
  require(cpu.native_steps==(reference?0U:steps)&&cpu.interpreter_steps==(reference?steps:0U)&&cpu.guard_misses==(changed?1U:0U),"execution tiers");
  for(unsigned i=0;i<8192;++i){unsigned expected=vector_changed?negative_ram[i]:matrix||status_changed?0:main_ram[i];
   if(matrix||status_changed){const unsigned resume=c.pc+10;const unsigned pos=i>=256&&i<512?(initial_sp+256-(i-256))%256:8192;
    if(pos==0)expected=resume>>8;else if(pos==1)expected=resume&255;else if(pos==2)expected=status_changed?0x10:(status_bytes[case_index]|16)&~32;}
   const auto actual=bus->peek(0x1F0000+i);
   require(actual&&*actual==expected,("case "+std::to_string(n)+" RAM offset "+std::to_string(i)).c_str());
  }
  native+=cpu.native_steps;interpreted+=cpu.interpreter_steps;guards+=cpu.guard_misses;
 }
 capture.finish();std::cout<<"{\"passed\":true,\"cases\":"<<count<<",\"native\":"<<native<<",\"interpreted\":"<<interpreted<<",\"guards\":"<<guards<<"}\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}

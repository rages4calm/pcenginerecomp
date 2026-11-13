// Original banked route and reset matrix. Expectations come from fixture.py.
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
 require(argc==4,"usage: stack-probe card mode capture");const std::string mode=argv[2];
 const bool matrix=mode=="matrix"||mode=="matrix-reference",reference=mode=="reference"||mode=="matrix-reference",changed=mode=="changed-stack";
 require(matrix||reference||changed||mode=="main","invalid mode");
 std::ifstream f(path(argv[1]),std::ios::binary);std::vector<std::uint8_t> image((std::istreambuf_iterator<char>(f)),{});
 require(image.size()==32768,"image size");
 pce::CodeCapture capture(path(argv[3]),4096);std::uint64_t native=0,interpreted=0,guards=0;
 for(unsigned n=0;n<(matrix?281U:1U);++n){auto bus=std::make_unique<pce::Bus>();pce::Cpu cpu;
  bus->configure_hucard(pce::HuCardProfile::base,image);bus->power_on_cpu(cpu);const auto& c=cases[n];
  if(matrix){cpu.mpr={0,248,0,0,0,0,0,0};cpu.pc=c.pc;cpu.p=4;}
  const unsigned steps=matrix?c.steps:main_steps;unsigned retired=0;
  for(unsigned i=0;i<steps;++i){
   // Alter saved Z before the actual PLP. The generated pop and BNE must read it.
   if(changed&&cpu.pc==0xE01A&&cpu.mpr[7]==3){bus->write(cpu,0x21FC,0x14);}
   const auto before=capture.before(*bus,cpu);
   const auto old_cycles=cpu.cycles,old_ticks=cpu.ticks;const auto old_generation=bus->generation;
   std::unique_ptr<std::array<std::uint8_t,0x200000>> old_memory;
   if(changed&&cpu.pc==bad_pc)old_memory=std::make_unique<std::array<std::uint8_t,0x200000>>(*bus->bytes);
   const auto exit=pce::step(*bus,cpu,100000,reference?pce::ExecutionPolicy::interpreter_only:pce::ExecutionPolicy::native_only);
   if(changed&&exit==pce::Exit::miss){
    require(cpu.pc==bad_pc&&cpu.guard_misses==1&&old_memory&&*old_memory==*bus->bytes&&bus->generation==old_generation&&cpu.cycles==old_cycles&&cpu.ticks==old_ticks,"changed saved status endpoint/guard effects");break;
   }
   require(exit==pce::Exit::executed,"unexpected refusal");capture.after(before,cpu);++retired;
  }
  if(changed){
   require(cpu.guard_misses==1&&cpu.interpreter_steps==0&&cpu.native_steps==retired,"changed stack guard counts");
   require(retired==31&&cpu.a==66&&cpu.x==0x55&&cpu.y==0x33&&cpu.sp==0xFC&&cpu.p==4,"changed stack restoration");
   for(unsigned i=0;i<8192;++i){const unsigned expected=i<3?0:i==0x1FC?0x14:main_ram[i];
    const auto actual=bus->peek(0x1F0000+i);require(actual&&*actual==expected,"changed full WRAM mismatch");}
  }else{
   if(matrix){require(cpu.pc==c.end&&cpu.a==c.a&&cpu.x==c.x&&cpu.y==c.y&&cpu.p==c.p&&cpu.sp==0&&cpu.cycles==c.cycles&&cpu.ticks==12*c.cycles&&cpu.mpr==std::array<std::uint8_t,8>{0,248,0,0,0,0,0,0},"matrix CPU/clocks mismatch");}
   else{require(cpu.pc==main_end&&cpu.a==2&&cpu.x==7&&cpu.y==128&&cpu.p==4&&cpu.sp==255&&cpu.cycles==main_cycles&&cpu.ticks==12*main_cycles&&cpu.mpr==std::array<std::uint8_t,8>{0,249,2,0,0,0,0,3},"main CPU/clocks mismatch");}
   require(cpu.native_steps==(reference?0U:steps)&&cpu.interpreter_steps==(reference?steps:0U)&&cpu.guard_misses==0,"tier counts");
   for(unsigned i=0;i<8192;++i){const unsigned expected=matrix?((i==0||i==0x100)?c.stored:0):main_ram[i];
    const auto actual=bus->peek(0x1F0000+i);require(actual&&*actual==expected,"full WRAM mismatch");}
  }
  native+=cpu.native_steps;interpreted+=cpu.interpreter_steps;guards+=cpu.guard_misses;
 }
 capture.finish();std::cout<<"{\"passed\":true,\"cases\":"<<(matrix?281:1)<<",\"native\":"<<native<<",\"interpreted\":"<<interpreted<<",\"guards\":"<<guards<<"}\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}

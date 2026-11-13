// Original mutable-data fixture. Each matrix case has a separate reset/preset.
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
static void require(bool v,const char* m){if(!v)throw std::runtime_error(m);}
static auto path(const char* s){return std::filesystem::path(std::u8string(reinterpret_cast<const char8_t*>(s)));}
int main(int argc,char** argv){try{
 require(argc==4,"usage: wram-probe card mode capture");const std::string mode=argv[2];
 const bool matrix=mode=="matrix"||mode=="matrix-reference",reference=mode=="reference"||mode=="matrix-reference";
 const bool pointer=mode=="changed-pointer",transfer=mode=="changed-transfer",changed=pointer||transfer;
 require(matrix||reference||changed||mode=="main","invalid mode");
 std::ifstream f(path(argv[1]),std::ios::binary);std::vector<std::uint8_t> image((std::istreambuf_iterator<char>(f)),{});
 require(image.size()==32768,"image size");
 pce::CodeCapture capture(path(argv[3]),8192);std::uint64_t native=0,interpreted=0,guards=0;
 for(unsigned n=0;n<(matrix?case_count:1U);++n){auto bus=std::make_unique<pce::Bus>();pce::Cpu cpu;
  bus->configure_hucard(pce::HuCardProfile::base,image);bus->power_on_cpu(cpu);const auto& c=cases[n];
  const std::array<std::uint8_t,8> mapped{0,248,251,3,0,0,0,static_cast<std::uint8_t>(c.bank)};
  if(matrix){cpu.mpr=mapped;cpu.pc=c.pc;cpu.p=4;}
  const unsigned steps=matrix?c.steps:changed?(pointer?pointer_steps:transfer_steps):main_steps;
  for(unsigned i=0;i<steps;++i){
   if(pointer&&cpu.pc==jump_pc&&cpu.mpr[7]==2)bus->write(cpu,0x2000,0x80);
   if(transfer&&cpu.pc==adc_pc)bus->write(cpu,0x2020,2);
   const auto before=capture.before(*bus,cpu);
   require(pce::step(*bus,cpu,100000,reference?pce::ExecutionPolicy::interpreter_only:pce::ExecutionPolicy::native_only)==pce::Exit::executed,"unexpected refusal");
   capture.after(before,cpu);
  }
  if(changed){
   require(cpu.pc==(pointer?0xE280:map_code)&&cpu.a==(pointer?0x42:3)&&cpu.x==0x20&&cpu.y==0&&cpu.sp==0&&cpu.p==4,"changed live data endpoint");
   const auto old_memory=std::make_unique<std::array<std::uint8_t,0x200000>>(*bus->bytes);
   const auto old_cycles=cpu.cycles,old_ticks=cpu.ticks;const auto generation=bus->generation;
   require(pce::step(*bus,cpu,100000,pce::ExecutionPolicy::native_only)==pce::Exit::miss,"omitted RAM-driven source accepted");
   require(*old_memory==*bus->bytes&&generation==bus->generation&&old_cycles==cpu.cycles&&old_ticks==cpu.ticks,"guard guest effects");
  }else{
   if(matrix){require(cpu.pc==c.end&&cpu.a==c.a&&cpu.x==c.x&&cpu.y==c.y&&cpu.p==c.p&&cpu.sp==0&&cpu.cycles==c.cycles&&cpu.ticks==12*c.cycles&&cpu.mpr==mapped,("matrix "+std::to_string(n)+" CPU/clocks mismatch, P="+std::to_string(cpu.p)+" cycles="+std::to_string(cpu.cycles)+" expected cycles="+std::to_string(c.cycles)).c_str());}
   else{require(cpu.pc==main_end&&cpu.a==0x42&&cpu.x==2&&cpu.y==0x40&&cpu.p==4&&cpu.sp==0&&cpu.cycles==main_cycles&&cpu.ticks==12*main_cycles&&cpu.mpr==std::array<std::uint8_t,8>{0,248,2,3,0,0,0,2},"main CPU/clocks mismatch");}
  }
  require(cpu.native_steps==(reference?0U:steps)&&cpu.interpreter_steps==(reference?steps:0U)&&cpu.guard_misses==(changed?1U:0U),"tier counts");
  for(unsigned i=0;i<8192;++i){unsigned expected=matrix?0:main_ram[i];
   if(matrix){for(const auto& w:writes[n])if(w.offset==i)expected=w.value;}
   if(changed){if(i>=4&&i<=6)expected=0;if(pointer&&i==0)expected=0x80;
    if(transfer){if(i==0x20)expected=3;if(i==0x30||i==0x31||i==0x100||i==0x1FF)expected=0;}}
   const auto actual=bus->peek(0x1F0000+i);require(actual&&*actual==expected,("case "+std::to_string(n)+" full WRAM mismatch at "+std::to_string(i)).c_str());
  }
  native+=cpu.native_steps;interpreted+=cpu.interpreter_steps;guards+=cpu.guard_misses;
 }
 capture.finish();std::cout<<"{\"passed\":true,\"cases\":"<<(matrix?case_count:1)<<",\"native\":"<<native<<",\"interpreted\":"<<interpreted<<",\"guards\":"<<guards<<"}\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}

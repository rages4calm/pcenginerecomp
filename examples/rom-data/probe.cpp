// Original authored ROM-data fixture. Presets/resets are explicit preconditions.
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
static std::filesystem::path path(const char* value){return std::filesystem::path(std::u8string(reinterpret_cast<const char8_t*>(value)));}
int main(int argc,char** argv){
 try{
  require(argc==4,"usage: data-probe card main|reference|matrix|matrix-reference|value-change|bank-change|source-change capture");
  const std::string mode=argv[2];const bool matrix=mode=="matrix" || mode=="matrix-reference";
  const bool reference=mode=="reference" || mode=="matrix-reference";
  const bool value_change=mode=="value-change",bank_change=mode=="bank-change",source_change=mode=="source-change";
  require(matrix || reference || value_change || bank_change || source_change || mode=="main","invalid mode");
  std::ifstream file(path(argv[1]),std::ios::binary);std::vector<std::uint8_t> image((std::istreambuf_iterator<char>(file)),{});
  require(image.size()==32768,"authored image size");
  if(value_change)image[0x42FF]=0x99;
  if(bank_change)image[0x100]=3;
  if(source_change)image[0x4201]=0xFE;
  pce::CodeCapture capture(path(argv[3]),512);std::uint64_t native=0,interpreted=0,guards=0;
  const unsigned count=matrix?64U:1U;
  for(unsigned case_index=0;case_index<count;++case_index){
   auto bus=std::make_unique<pce::Bus>();pce::Cpu cpu;
   bus->configure_hucard(pce::HuCardProfile::base,image);bus->power_on_cpu(cpu);
   const auto& c=cases[case_index];
   if(matrix){cpu.mpr={0,1,3,0,0,0,0,0};cpu.pc=c.pc;cpu.a=0x55;cpu.p=0x35;}
   const unsigned steps=matrix?4U:bank_change?4U:source_change?10U:17U;
   for(unsigned i=0;i<steps;++i){
    const auto before=capture.before(*bus,cpu);
    require(pce::step(*bus,cpu,10000,reference?pce::ExecutionPolicy::interpreter_only:pce::ExecutionPolicy::native_only)==pce::Exit::executed,"unexpected refusal");
    capture.after(before,cpu);
   }
   unsigned expected_value=value_change?0x99U:42U;
   if(matrix){
    const unsigned a=c.reg==0?c.value:0x55,x=c.reg==1?c.value:c.x,y=c.reg==2?c.value:c.y;
    const unsigned flags=0x15|(c.value==0?2:0)|(c.value&0x80);
    require(cpu.pc==c.end && cpu.a==a && cpu.x==x && cpu.y==y && cpu.sp==0 && cpu.p==flags &&
      cpu.mpr==std::array<std::uint8_t,8>{0,1,3,0,0,0,0,0} && cpu.cycles==c.cycles && cpu.ticks==12*c.cycles,"literal addressing case mismatch");
   }else if(bank_change || source_change){
    require(cpu.pc==(bank_change?0xE009:0xE200) && cpu.native_steps==steps && cpu.interpreter_steps==0,"literal guard boundary mismatch");
    if(bank_change)require(cpu.a==3 && cpu.mpr[2]==3 && cpu.cycles==17 && cpu.ticks==204,"bank value was baked");
    const auto clocks=cpu.ticks,cycles=cpu.cycles;
    const auto generation=bus->generation;
    const auto memory=std::make_unique<std::array<std::uint8_t,0x200000>>(*bus->bytes);
    require(pce::step(*bus,cpu,10000,pce::ExecutionPolicy::native_only)==pce::Exit::miss,"changed context/source accepted");
    require(cpu.ticks==clocks && cpu.cycles==cycles && cpu.native_steps==steps && cpu.interpreter_steps==0 &&
      cpu.guard_misses==1 && bus->generation==generation && *bus->bytes==*memory,"guard changed work/clocks/memory");
   }else{
    require(cpu.pc==0xE01A && cpu.a==expected_value && cpu.x==2 && cpu.y==3 && cpu.sp==0 && cpu.p==(value_change?0x84:4) &&
      cpu.mpr==std::array<std::uint8_t,8>{0,248,1,0,0,0,0,2} && cpu.cycles==87 && cpu.ticks==1044,"literal main route mismatch");
   }
   require(cpu.native_steps==(reference?0U:steps) && cpu.interpreter_steps==(reference?steps:0U) &&
     cpu.guard_misses==((bank_change || source_change)?1U:0U),"execution tier mismatch");
   for(unsigned i=0;i<8192;++i){
    unsigned expected=0;
    if(!matrix && !bank_change){
     if(i==0x100)expected=0xE0;if(i==0x1FF)expected=0x19;
     if(!source_change){if(i==0)expected=expected_value;if(i==1)expected=2;if(i==2)expected=3;}
    }
    auto actual=bus->peek(0x1F0000+i);require(actual && *actual==expected,"literal full WRAM mismatch");
   }
   native+=cpu.native_steps;interpreted+=cpu.interpreter_steps;guards+=cpu.guard_misses;
  }
  capture.finish();std::cout<<"{\"passed\":true,\"cases\":"<<count<<",\"native\":"<<native<<",\"interpreted\":"<<interpreted<<",\"guards\":"<<guards<<"}\n";
 }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}

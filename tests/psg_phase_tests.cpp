// Authored guest instruction timing. Expected PCM at master tick488 observes
// the pre-write DAC: scalar PSG writes occur at504 or later; block writes
// first reach port6 at492 (RAM source) or516 (VDC source).
// Device tests also preserve explicit immediate access and residual clock APIs.
#include "pce/runtime.hpp"
#include "pce/checkpoint.hpp"
#include "psg_phase_fixture.hpp"
#include <iostream>
#include <memory>
#include <string>
namespace {
unsigned checks=0,native_retirements=0,interpreted_retirements=0;
void require(bool ok,const char* why){++checks;if(!ok)throw std::runtime_error(why);}
struct Machine{pce::Bus bus;pce::Cpu cpu;};
std::unique_ptr<Machine> machine(const PhaseCase& c,unsigned speed=12){
 auto m=std::make_unique<Machine>();auto& b=m->bus;auto& s=m->cpu;
 b.kind[0]=pce::BankKind::rom;b.kind[248]=pce::BankKind::ram;b.enable_psg();b.enable_audio_output();
 if(c.size==7&&c.data[2]==0)b.enable_vdc();
 s.mpr=phase_mpr;s.pc=c.pc;s.a=31;s.x=s.y=1;s.p=pce::I|pce::C;s.clock_divisor=speed;
 for(unsigned i=0;i<c.size;++i)(*b.bytes)[b.physical(s,c.pc+i)]=c.data[i];
 for(unsigned i=0;i<4;++i)(*b.bytes)[(248<<13)+0x200+i]=31;
 (*b.bytes)[(248<<13)+0x20]=6;(*b.bytes)[(248<<13)+0x21]=8;
 (*b.bytes)[(248<<13)+0x22]=5;(*b.bytes)[(248<<13)+0x23]=8;
 b.write(s,0x0800,0);b.write(s,0x0801,255);b.write(s,0x0804,223);b.write(s,0x0805,255);b.write(s,0x0806,c.old_dda);
 // Configure devices at clock zero; tick488 is the instruction phase discriminator.
 b.pcm.drain();b.io_latch=31;
 s.ticks=c.size==7?252:444;s.cycles=s.ticks/speed;b.sync(s);
 return m;
}
void step(Machine& m,bool native){require((native?pce::generated_step(m.bus,m.cpu,UINT64_MAX):pce::interpret_step(m.bus,m.cpu,UINT64_MAX))==pce::Exit::executed,"authored PSG instruction did not execute");if(native)++native_retirements;else ++interpreted_retirements;}
void cases(){
 for(bool native:{false,true})for(const auto& c:phase_cases){
  auto m=machine(c);auto& b=m->bus;auto& s=m->cpu;const auto ticks=s.ticks,cycles=s.cycles;
  const auto before=pce::encode_checkpoint(b,s);auto copy=machine(c);pce::restore_checkpoint(copy->bus,copy->cpu,before);
  step(*m,native);step(*copy,native);
  require(s.ticks==ticks+c.cycles*12 && s.cycles==cycles+c.cycles,"PSG phase consumed base cycles twice or changed total");
  require(s.pc==c.pc+c.size && s.native_steps==unsigned(native)&&s.interpreter_steps==unsigned(!native),"PSG fixture retirement/source tier mismatch");
  require(b.psg.channels[0].dda==c.new_dda,"PSG instruction final DDA differs");
  require(pce::encode_checkpoint(b,s)==pce::encode_checkpoint(copy->bus,copy->cpu),"checkpoint-before PSG continuation differs");
  auto samples=b.pcm.drain();require(samples.size()==2,"PSG phase fixture exact first stereo sample count");
  if(samples[0]!=(c.old_dda?1761:-1761)||samples[1]!=samples[0])std::cerr<<c.name<<" native="<<native<<" sample="<<samples[0]<<" old="<<c.old_dda<<"\n";
  require(samples[0]==(c.old_dda?1761:-1761)&&samples[1]==samples[0],"PSG write happened before first PCM boundary");
  auto after=pce::encode_checkpoint(b,s);auto resumed=machine(c);pce::restore_checkpoint(resumed->bus,resumed->cpu,after);
  b.clock_cpu(s,100);resumed->bus.clock_cpu(resumed->cpu,100);
  require(pce::encode_checkpoint(b,s)==pce::encode_checkpoint(resumed->bus,resumed->cpu),"checkpoint-after PSG sample continuation differs");
 }
}
void helpers(){
 const auto& c=phase_cases[0];
 for(unsigned speed:{3U,12U}){
  auto m=machine(c,speed);auto& b=m->bus;auto& s=m->cpu;auto ticks=s.ticks;
  require(b.write_timed(s,0xa806,31,5)==0&&s.ticks==ticks+5*speed&&s.cycles==ticks/speed+5,"PSG MPR alias did not consume remaining base clocks");
  ticks=s.ticks;b.write(s,0x0806,0);require(s.ticks==ticks,"lowlevel immediate PSG access silently advanced CPU");
  require(b.write_timed(s,0x2200,55,5)==5&&s.ticks==ticks&&b.read(s,0x2200)==55,"RAM timing phase changed");
  b.enable_joypad();
  require(b.write_timed(s,0x1000,3,5)==5&&s.ticks==ticks,"non-PSG I/O consumed PSG base clocks");
  b.kind[255]=pce::BankKind::ram;
  require(b.write_timed(s,0x0806,31,5)==5&&s.ticks==ticks,"PSG logical address with RAM bank consumed clocks");
 }
 auto m=machine(c);auto& b=m->bus;auto& s=m->cpu;b.enable_interrupts();s.p=0;
 b.irq.timer_enabled=true;b.irq.timer_deadline=480;b.irq.timer_counter=0;b.irq.timer_reload=0;
 require(b.write_timed(s,0x0806,31,5)==0&&s.irq_sampled==4&&s.irq_entries==0&&s.pc==c.pc,"PSG preclock must sample IRQ without delivering it");
 (*b.bytes)[0x1ffa]=0;(*b.bytes)[0x1ffb]=0xe0;s.pc=c.pc+c.size;b.retire(s,0,true);
 require(s.irq_entries==1&&s.irq_vector==0xfffa&&s.pc==0xe000&&s.native_steps==1,"PSG preclock IRQ not delivered exactly at retirement");
 require((*b.bytes)[(248<<13)+0x1fe]==std::uint8_t(c.pc+c.size),"PSG IRQ stacked pre-retirement PC");
 // A timer edge inside each real block is sampled, but cannot interrupt the
 // transfer early. All3 bytes and the ordinary post-block stack finish first.
 for(bool native:{false,true})for(const auto& block:phase_cases)if(block.size==7){
  auto q=machine(block);q->bus.enable_interrupts();q->cpu.p=0;
  q->bus.irq.timer_enabled=true;q->bus.irq.timer_deadline=480;q->bus.irq.timer_reload=0;
  (*q->bus.bytes)[0x1ffa]=0;(*q->bus.bytes)[0x1ffb]=0xe0;step(*q,native);
  require(q->cpu.irq_entries==1&&q->cpu.block_bytes==3&&q->cpu.pc==0xe000&&q->cpu.cycles==21+block.cycles+8,"block PSG IRQ escaped before transfer completion");
  require((*q->bus.bytes)[(248<<13)+0x1fe]==std::uint8_t(block.pc+7),"block PSG IRQ stacked incomplete PC");
 }
}
}
int main(){try{cases();helpers();std::cout<<checks<<" PSG guest phase, scalar/RMW/5-block, mirror/MPR/IRQ/checkpoint checks; "<<phase_cases.size()<<" authored source identities, "<<native_retirements<<" native + "<<interpreted_retirements<<" interpreted guest retirements\n";}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}

#include "pce/rewind.hpp"
#include "pce/dev_instruction.hpp"
#include <iostream>
static void require(bool value){if(!value)throw pce::Fault("rewind/probe expectation failed");}
template<class F>void refuses(F f){try{f();}catch(const pce::Fault&){return;}throw pce::Fault("expected refusal");}
int main(){
    const std::string context(64,'a');
    for(unsigned size: {1u,7u,256u,8192u})for(unsigned geometry=0;geometry<6;++geometry){
        std::vector<std::uint8_t> a(size),b(size+geometry);
        for(unsigned i=0;i<a.size();++i)a[i]=static_cast<std::uint8_t>(i*37+geometry);
        for(unsigned i=0;i<b.size();++i)b[i]=i<a.size()?a[i]:0;
        for(unsigned i=geometry;i<b.size();i+=11)b[i]^=0x5a;
        const auto code=pce::RewindTimeline::delta(a,b);require(pce::RewindTimeline::reverse(b,code)==a);
        auto bad=code;bad.pop_back();refuses([&]{(void)pce::RewindTimeline::reverse(b,bad);});
        bad=code;bad.push_back(0);refuses([&]{(void)pce::RewindTimeline::reverse(b,bad);});
    }
    pce::RewindTimeline small(context,8192,3);std::vector<std::uint8_t> bytes(1024);
    for(unsigned i=0;i<8;++i){bytes[i]=static_cast<std::uint8_t>(i+1);small.push(bytes,context);require(small.bytes()<=8192);}
    require(small.available()==3);auto three=small.peek(3);require(three[4]==5 && three[5]==0);
    refuses([&]{small.push(bytes,std::string(64,'b'));});require(small.available()==3);
    pce::Bus bus;bus.kind[0x80]=pce::BankKind::ram;bus.kind[0xF8]=pce::BankKind::ram;pce::Cpu cpu;
    pce::RewindTimeline timeline(context,16*1024*1024,8);
    std::vector<std::vector<std::uint8_t>> expected;
    for(unsigned i=0;i<6;++i){cpu.a=std::uint8_t(i);cpu.ticks=i*900;cpu.interpreter_steps=i*7;(*bus.bytes)[0x100040+i]=std::uint8_t(i+17);expected.push_back(pce::encode_checkpoint(bus,cpu));timeline.capture(bus,cpu,context);}
    timeline.restore(bus,cpu,3,context);require(pce::encode_checkpoint(bus,cpu)==expected[2] && timeline.available()==2);
    timeline.capture(bus,cpu,context);require(timeline.available()==3);timeline.restore(bus,cpu,3,context);require(pce::encode_checkpoint(bus,cpu)==expected[0]);
    pce::DevLocation from{0x4000,{255,248,128,129,0,0,0,0},10,20};pce::DevInstructionWindow w;
    w.start(from,100,0x5000,from.mpr,4,3,90);auto at=from;at.pc=0x5000;w.update(at,100);require(w.active());
    ++at.interpreted;at.mpr[2]=129;w.update(at,103);require(w.active());at.mpr[2]=128;w.update(at,106);require(w.state==pce::DevInstructionWindow::State::reached);
    w.start(from,100,0x5000,from.mpr,4,3,90);at=from;at.native+=3;w.update(at,110);require(w.state==pce::DevInstructionWindow::State::instructions);
    w.start(from,100,0x5000,from.mpr,4,3,90);w.update(from,190);require(w.state==pce::DevInstructionWindow::State::ticks);
    std::cout<<"24 original variable-size delta geometries, malformed packets, bounded history, guest CPU/RAM rewind and instruction-window boundaries passed\n";
}

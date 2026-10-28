// Authored supervisor. Only mapped STA/LDA instructions access toolkit ports.
// The separate reference build uses unchanged original Gear device functions.
#define main previous_authored_gap_main
#include "cdda_gap_probe.cpp"
#undef main

unsigned end_frame(const GapAdapter& a) {
#ifdef PCE_CDDA_GAP_GEAR
    return *a.core->GetCDROMAudio()->GetState()->CURRENT_SAMPLE;
#else
    return a.bus->cd.audio.source_cursor.frame;
#endif
}
std::uint64_t end_delay(const GapAdapter& a) {
#ifdef PCE_CDDA_GAP_GEAR
    return std::max(0,*a.core->GetCDROMAudio()->GetState()->PLAYBACK_DELAY_CYCLES);
#else
    const auto d=a.bus->cd.audio.playback_deadline;return d>a.now()?d-a.now():0;
#endif
}
std::uint64_t end_next_edge(const GapAdapter& a) {
#ifdef PCE_CDDA_GAP_GEAR
    return a.now()+(21477273-(a.core->GetAudio()->*member(EndSampleClock{}))+44099)/44100;
#else
    return a.bus->cd.audio.sample_next_tick;
#endif
}
int end_left(const GapAdapter& a) {
#ifdef PCE_CDDA_GAP_GEAR
    return a.core->GetCDROMAudio()->GetLeftSample();
#else
    return a.bus->cd.audio.sample_raw[0];
#endif
}
int end_right(const GapAdapter& a) {
#ifdef PCE_CDDA_GAP_GEAR
    return a.core->GetCDROMAudio()->GetRightSample();
#else
    return a.bus->cd.audio.sample_raw[1];
#endif
}
unsigned end_latch(GapAdapter& a) {
    a.write(0x1805,0);
#ifdef PCE_CDDA_GAP_GEAR
    const auto low=a.core->GetCDROM()->ReadRegister(0x1805);++a.calls;a.advance(5*a.divisor);
    const auto high=a.core->GetCDROM()->ReadRegister(0x1806);++a.calls;a.advance(5*a.divisor);
#else
    a.execute(0xAD,0x1805);const auto low=a.cpu.a;
    a.execute(0xAD,0x1806);const auto high=a.cpu.a;
#endif
    return low|(high<<8);
}
void end_point(GapAdapter& a) {
    std::cout<<"{\"frame\":"<<end_frame(a)<<",\"left\":"<<end_left(a)<<",\"right\":"<<end_right(a)<<",\"next_edge\":"<<end_next_edge(a)<<",\"delay\":"<<end_delay(a)<<",\"raw\":";
    observe(std::cout,a);
#ifdef PCE_CDDA_GAP_GEAR
    std::cout<<",\"sector_deadline\":0,\"sector_fraction\":0";
#else
    std::cout<<",\"sector_deadline\":"<<a.bus->cd.audio.sector_deadline<<",\"sector_fraction\":"<<a.bus->cd.audio.sector_fraction;
#endif
    std::cout<<'}';
}
int main(int argc,char** argv) {try {
    require(argc==8,"cdda-end CASES ROM CUE TIER DIVISOR NEW_CAPTURE NEW_REPORT");
    const std::string tier=argv[4];
#ifdef PCE_CDDA_GAP_GEAR
    require(tier=="gear","Original Gear tier required");
#else
    require(tier=="native"||tier=="interpreter","Explicit execution tier required");
#endif
    const auto speed=std::stoul(argv[5]);require(speed==3||speed==12,"CPU divisor required");
    require(!std::filesystem::exists(argv[7]),"New report required");
    const auto rom=reset_probe::rom(argv[2]);GapAdapter a(rom,argv[3],tier,speed,argv[6]);
    std::ifstream plan(argv[1]);require(bool(plan),"Missing authored plan");
    std::string id,state;unsigned end,mode,offset,count=0;bool comma=false;
    std::cout<<'[';
    while(plan>>id>>state>>end>>mode>>offset) {
        a.reset();command(a,8,0,0);command(a,0xD8,0,10);
        if(state=="playing") {
            command(a,0xD9,3,609);const auto delay=end_delay(a);if(delay)a.advance(delay);
            while(end_frame(a)<100) {const auto edge=end_next_edge(a);require(edge>a.now(),"Future setup edge missing");a.advance(edge-a.now());}
        } else require(state=="paused","Unknown authored state");
        a.advance(offset);if(comma)std::cout<<',';comma=true;
        std::cout<<"{\"case\":\""<<id<<"\",\"before\":";end_point(a);
        start(a,0xD9,mode,end);
        if(mode==3) {const auto reply=drain(a);require(reply.first==0&&reply.second==0,"D9 completion differs");}
        std::cout<<",\"admitted\":";end_point(a);
        const auto delay=end_delay(a);if(delay)a.advance(delay);
        std::cout<<",\"ready\":";end_point(a);
        std::cout<<",\"edges\":[";
        for(unsigned i=0;i<1300;++i) {
            const auto edge=end_next_edge(a);require(edge>a.now(),"Future source edge missing");
            a.advance(edge-a.now()-1);const auto pre=a.logical();const auto pre_frame=end_frame(a);
            a.advance(1);const auto left=end_left(a),right=end_right(a);const auto frame=end_frame(a);const auto logical=a.logical();const auto phase=a.phase(),signals=a.signals();
            const auto latch=end_latch(a);
            if(i)std::cout<<',';
            // Every raw source edge retains its original absolute clock. The
            // final three mapped port opcodes finish before the following edge.
            std::cout<<'['<<edge<<','<<frame<<','<<left<<','<<right<<','<<logical[0]<<','<<logical[2]<<','<<phase<<','<<signals<<','<<latch<<','<<pre[0]<<','<<pre_frame<<']';
        }
        std::cout<<"],\"settled\":";end_point(a);std::cout<<'}';++count;
    }
    require(plan.eof(),"Malformed authored end-update plan");std::cout<<"]\n";a.finish();
    std::ofstream report(argv[7]);require(bool(report),"Execution report creation failed");
    report<<"{\"schema\":1,\"tier\":\""<<tier<<"\",\"divisor\":"<<speed<<",\"cases\":"<<count<<",\"port_calls\":"<<a.calls<<"}\n";
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}

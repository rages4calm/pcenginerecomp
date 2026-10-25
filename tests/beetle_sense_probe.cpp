// Authored adapter around the complete unchanged private upstream translation unit.
// No GPL source body is embedded in this public file or linked to the toolkit.
#include "sense_probe_support.hpp"
#include <memory>
#include "scsicd.cpp"
void CDIRQ(int){}
void StuffSubchannel(uint8_t,int){}
bool subq_check_checksum(const uint8_t*){return false;}
struct Adapter {
    std::unique_ptr<CDIF> medium;std::int32_t ticks=0;bool initialized=false;
    ~Adapter(){if(initialized)SCSICD_Close();}
    void reset(unsigned mode) {
        if(mode>4)throw std::runtime_error("authored media mode");
        if(initialized)SCSICD_Close();SCSICD_Init(1,nullptr,nullptr,153600,21477273);initialized=true;ticks=0;
        medium.reset();SCSICD_SetDisc(false,nullptr,true);
        if(mode){medium=std::make_unique<CDIF>();medium->disc_toc.first_track=medium->disc_toc.last_track=1;
            medium->disc_toc.tracks[1]={1,static_cast<uint8_t>(mode==2?0:4),0,true};medium->disc_toc.tracks[100]={1,0,20,true};
            medium->raw_ok=mode!=3;medium->validation_ok=mode!=4;
            SCSICD_SetDisc(true,nullptr,true);SCSICD_SetDisc(false,medium.get(),true);}
        SCSICD_Power(0);
    }
    void advance(unsigned n){if(n>10000000||ticks>2000000000-int(n))throw std::runtime_error("reference timestamp bound");ticks+=n;SCSICD_Run(ticks);}
    bool busy()const{return BSY_signal;}bool request()const{return REQ_signal;}bool input()const{return IO_signal;}
    bool control()const{return CD_signal;}bool message()const{return MSG_signal;}
    void select(){SCSICD_SetSEL(true);advance(1);SCSICD_SetSEL(false);advance(1);}
    void write_data(unsigned v){SCSICD_SetDB(v);}void ack(bool v){SCSICD_SetACK(v);advance(1);}
    unsigned read_data(bool automatic){const auto v=SCSICD_GetDB();if(automatic)ack(true);return v;}
    void finish_auto_ack(){advance(21);ack(false);advance(1);}
    void warm_reset(){SCSICD_SetRST(true);advance(1);SCSICD_SetRST(false);advance(1);}
    std::vector<std::uint64_t> pending()const{return {cd.key_pending,cd.asc_pending,cd.ascq_pending,cd.fru_pending};}
};
int main(int argc,char** argv) {
    try {
        if(argc!=2)throw std::runtime_error("usage: beetle-sense PLAN");std::ifstream plan(argv[1]);if(!plan)throw std::runtime_error("missing plan");
        Adapter a;std::string op;bool first=true;std::cout<<'[';
        while(plan>>op) {
            if(op=="r"){unsigned mode;if(!(plan>>mode))throw std::runtime_error("reset mode");a.reset(mode);}
            else if(!a.initialized)throw std::runtime_error("operation before reset");
            else if(op=="c"){unsigned automatic;const auto cdb=sense_probe::command(plan,automatic);sense_probe::start(a,cdb);sense_probe::record(first,cdb,automatic,sense_probe::drain(a,automatic));}
            else if(op=="p")reset_probe::record(first,"pending",a.pending());
            else if(op=="z")a.warm_reset();
            else if(op=="b"){sense_probe::start(a,{3,0,0,0,18,0});a.warm_reset();}
            else throw std::runtime_error("unknown operation");
        }
        std::cout<<"]\n";return 0;
    }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}
}

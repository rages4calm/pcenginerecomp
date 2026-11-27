#include "pce/disc_origin.hpp"
#include <iostream>
#include <stdexcept>

namespace {
void require(bool value,const char* message){if(!value)throw std::runtime_error(message);}
void origin_is(const pce::DiscOrigin& observer,std::uint32_t address,const char* expected) {
    require(observer.json(address,1).find(expected)!=std::string::npos,"disc origin byte differs");
}
}
int main() {
    try {
        pce::Bus bus;
        bus.enable_cd_transport();
        bus.enable_work_ram_mirrors();
        bus.kind[0x80]=pce::BankKind::ram;
        const std::uint8_t program[]{
            0xAD,0x01,0x18,0x8D,0x00,0x20, // DATA IN through A to RAM
            0xAD,0x00,0x20,0xAA,0x8E,0x01,0x20, // RAM through A/X to RAM
            0x29,0xFF,0x8D,0x02,0x20, // unchanged arithmetic destroys metadata
            0x73,0x00,0x20,0x00,0x22,0x01,0x00, // actual TII copy
            0xAD,0x01,0x18,0x8D,0x03,0x20, // repeated CD data peek
        };
        bus.load(0x100000,program,sizeof(program));
        pce::Cpu cpu;
        cpu.pc=0x4000;cpu.mpr={255,248,128,0,0,0,0,0};cpu.p=pce::I;
        bus.cd.scsi.read_active=true;bus.cd.scsi.phase=4;
        bus.cd.scsi.signals=0x48;bus.cd.scsi.response_size=2048;
        bus.cd.scsi.response_index=7;bus.cd.scsi.load_lba=4;bus.cd.scsi.data=0x42;
        pce::DiscOrigin observer;
        observer.attach(bus,cpu);
        const auto advance=[&] {
            require(pce::step(bus,cpu,100000,pce::ExecutionPolicy::interpreter_only)==pce::Exit::executed,
                    "authored origin instruction did not retire");
        };
        advance();advance();
        origin_is(observer,0x1F0000,"\"offsets\":[6150]");
        origin_is(observer,0x1F2000,"\"offsets\":[6150]");
        advance();advance();advance();
        origin_is(observer,0x1F0001,"\"offsets\":[6150]");
        advance();advance();
        require((*bus.bytes)[0x1F0002]==0x42,"authored same-value arithmetic differs");
        origin_is(observer,0x1F0002,"\"offsets\":[null]");
        advance();
        origin_is(observer,0x1F0200,"\"offsets\":[6150]");
        advance();advance();
        origin_is(observer,0x1F0003,"\"offsets\":[6150]");
        require(bus.cd.data_bytes_acked==0,"data peek unexpectedly acknowledged a byte");
        // Mixing raw interpreter execution must destroy register lineage even
        // when the intervening arithmetic computes the same byte.
        const std::uint8_t direct[]{0xAD,0x01,0x18,0x29,0xFF,0x8D,0x04,0x20};
        bus.load(0x100100,direct,sizeof(direct));
        cpu.pc=0x4100;
        advance();
        require(pce::interpret_step(bus,cpu,100000)==pce::Exit::executed,"direct interpreter operation failed");
        advance();
        origin_is(observer,0x1F0004,"\"offsets\":[null]");
        // IRQ entry pushes the high PC byte, chosen to equal the loaded A.
        // Those writes cannot inherit the preceding STA's register source.
        const std::uint8_t interrupted[]{0xAD,0x01,0x18,0x8D,0x05,0x20};
        const std::uint8_t handler[]{0x8D,0x06,0x20};
        const std::uint8_t vector[]{0x00,0x43};
        bus.load(0x100200,interrupted,sizeof(interrupted));
        bus.load(0x100300,handler,sizeof(handler));
        bus.load(0x101FF6,vector,sizeof(vector));
        cpu.pc=0x4200;cpu.mpr[7]=128;
        advance();
        bus.enable_interrupts();
        cpu.p=0;bus.irq.external=1;
        advance();
        require(cpu.irq_entries==1 && cpu.pc==0x4300,"authored IRQ entry failed");
        require((*bus.bytes)[0x1F01FF]==0x42,"IRQ high PC byte differs");
        origin_is(observer,0x1F0005,"\"offsets\":[6150]");
        origin_is(observer,0x1F01FF,"\"offsets\":[null]");
        advance();
        origin_is(observer,0x1F0006,"\"offsets\":[null]");
        // Same-value debug writes invalidate lineage, including mirror aliases.
        observer.invalidate(0x1F2000,1);
        origin_is(observer,0x1F0000,"\"offsets\":[null]");
        (*bus.bytes)[0x1F0001]=0;
        origin_is(observer,0x1F0001,"\"offsets\":[null]");
        // Loader writes must invalidate old tags even if the bytes are equal.
        const std::uint8_t value=0x42;
        bus.load(0x1F0200,&value,1);
        origin_is(observer,0x1F0200,"\"offsets\":[null]");
        observer.reset();
        origin_is(observer,0x1F0003,"\"offsets\":[null]");
        require(observer.json(0x1F0000,1).find("\"epoch\":2")!=std::string::npos,"reset did not start a new origin epoch");
        origin_is(observer,0x1FE001,"\"offsets\":[null]");
        bool refused=false;
        try{(void)observer.json(0x1F0000,257);}catch(const pce::Fault&){refused=true;}
        require(refused,"unbounded origin query accepted");
        std::cout<<"disc origin scalar, transfer, mirror, block, mutation and reset checks passed\n";
        return 0;
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}

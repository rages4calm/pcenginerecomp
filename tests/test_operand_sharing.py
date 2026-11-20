"""Exact admitted operands share one body; independent literal native cases."""
import copy,hashlib,json,os,shutil,subprocess,tempfile,unittest
from pathlib import Path
from pcerecomp.emitter import emit_capture,emit_declarations
from pcerecomp.native_catalog import load_native_catalog
from tests.test_capture import capture,observation
ROOT=Path(__file__).resolve().parents[1]
OPS=[('LDA',0xA9),('LDX',0xA2),('LDY',0xA0),('ORA',0x09),('AND',0x29),('EOR',0x49),('ADC',0x69),('SBC',0xE9),('CMP',0xC9),('CPX',0xE0),('CPY',0xC0)]
VALUES=(0,1,0x79,0x80,0xFF)
def source():return capture([observation(0x4000+i*4,(op,value)) for i,(_,op) in enumerate(OPS) for value in VALUES])
def expected(name,value,flags):
    # Literal CPU setup A37 X05 Y07, DP[X]=48. Independent ordinary integer
    # arithmetic produces each exported expected row; no runtime call here.
    a,x,y=0x37,5,7;p=flags;cost=2;dest=0x48
    def nz(v,p):return (p&~0x82)|(v&0x80)|(2 if v==0 else 0)
    if name.startswith('LD'):
        if name=='LDA':a=value
        elif name=='LDX':x=value
        else:y=value
        p=nz(value,p)
    elif name in ('CMP','CPX','CPY'):
        left={'CMP':a,'CPX':x,'CPY':y}[name];p=nz((left-value)&255,(p&~1)|int(left>=value))
    else:
        transfer=bool(flags&32) and name in ('ADC','AND','ORA','EOR');left=dest if transfer else a
        if transfer:cost+=3
        if name in ('AND','ORA','EOR'):result={'AND':left&value,'ORA':left|value,'EOR':left^value}[name]
        else:
            carry=flags&1;result=left+value+carry if name=='ADC' else left-value-(1-carry)
            if flags&8:
                cost+=1
                if name=='ADC':
                    low=(left&15)+(value&15)+carry
                    if low>9:low+=6
                    result=(left&240)+(value&240)+(16 if low>15 else 0)+(low&15)
                    if result>159:result+=96
                else:
                    low=(left&15)-(value&15)-(1-carry);borrow=low<0
                    if borrow:low-=6
                    result=(left&240)-(value&240)-(16 if borrow else 0)+(low&15)
                    if result<0:result-=96
            else:
                overflow=((~(left^value) if name=='ADC' else left^value)&(left^result)&128)!=0;p=(p&~64)|(64 if overflow else 0)
            p=(p&~1)|int(result>255 if name=='ADC' else result>=0)
        result&=255;p=nz(result,p)
        if transfer:dest=result
        else:a=result
    return a,x,y,p&~32,dest,cost
class OperandSharingTests(unittest.TestCase):
    def test_default_emission_is_identical_to_explicit_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);emit_capture(source(),root/'a');emit_capture(source(),root/'b',operand_sharing=False)
            self.assertEqual({p.name:p.read_bytes() for p in (root/'a').iterdir()},{p.name:p.read_bytes() for p in (root/'b').iterdir()})
    def test_all_layouts_preserve_catalogue_membership_and_reduce_bodies(self):
        for layout in ('balanced','stable','shared'):
            with self.subTest(layout=layout),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);cap=source();path=root/'capture.json';path.write_text(json.dumps(cap),encoding='utf-8');sha=hashlib.sha256(path.read_bytes()).hexdigest();old=emit_capture(cap,root/'old',sha,partition_layout=layout);new=emit_capture(cap,root/'new',sha,partition_layout=layout,operand_sharing=True)
                self.assertEqual(old['native_instructions_emitted'],new['native_instructions_emitted']);self.assertLess(new['translated_body_count'],old['translated_body_count']);self.assertEqual(new['translated_body_count'],len(OPS))
                catalog=load_native_catalog(root/'new/module.json',path);self.assertEqual(len(catalog.emitted),len(OPS)*len(VALUES))
                text=''.join(p.read_text(encoding='utf-8') for p in (root/'new').glob('*.cpp'));self.assertIn('switch(operand_key)',text);self.assertIn('operand=*operand_0',text)
    def test_unknown_capability_types_and_expressions_refuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            for flag in (1,'true',None):
                with self.assertRaises(ValueError):emit_capture(source(),Path(tmp)/'bad',operand_sharing=flag)
    def test_declared_rom_and_overlay_catalogues_admit_exact_typed_capability(self):
        from pcerecomp.declarations import FORMAT
        from pcerecomp.overlay_snapshot import capture_snapshot
        from pcerecomp.overlays import discover_overlay,compose_overlays
        from tests.test_overlays import ReportedRam,machine,ORIGIN
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);image=root/'original.pce';image.write_bytes(bytes.fromhex('A9 2A 80 FE')+bytes(8188))
            mapping=[255,248,0,0,0,0,0,0]
            roots=root/'roots.json';roots.write_text(json.dumps(dict(format=FORMAT,schema=1,kind='declared',execution_evidence=False,
                image=dict(sha256=hashlib.sha256(image.read_bytes()).hexdigest(),profile='base',header='none',encoding='linear'),
                roots=[dict(pc=0x4000,mpr=mapping,selector=0,rom_offsets=[0,1])])),encoding='utf-8')
            snapshot=capture_snapshot(ReportedRam(bytes.fromhex('A9 2A 80 FE')+bytes(28)),root/'snapshot',machine=machine(),origin=ORIGIN,regions=[(0x100000,32)])
            epoch=discover_overlay(snapshot.path,root/'epoch',code_ranges=[(0x100000,32)])
            library=compose_overlays([epoch.path],root/'library')
            for name,declarations,asset in (('rom',roots,image),('overlay',library.path,None)):
                for layout in ('balanced','stable','shared'):
                    with self.subTest(source=name,layout=layout):
                        output=root/(name+'-'+layout);manifest=emit_declarations(declarations,asset,output,partition_layout=layout,operand_sharing=True)
                        catalog=load_native_catalog(output/'module.json',declarations,image_path=asset)
                        self.assertEqual(len(catalog.emitted),manifest['native_instructions_emitted']);self.assertFalse(catalog.observed)
                        manifest['operand_sharing']['schema']=True;(output/'module.json').write_text(json.dumps(manifest),encoding='utf-8')
                        with self.assertRaises(ValueError):load_native_catalog(output/'module.json',declarations,image_path=asset)
    @unittest.skipUnless((shutil.which('clang++') or shutil.which('g++')) and shutil.which('cmake') and shutil.which('ninja'),'CMake/Ninja/C++ required')
    def test_compiled_immediates_match_literal_cpu_ram_t_decimal_cycles_and_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);emit_capture(source(),root/'module',operand_sharing=True)
            rows=[]
            for i,(name,op) in enumerate(OPS):
                for value in VALUES:
                    for flags in (0,1,4,12,36,45,255):rows.append([0x4000+i*4,op,value,flags,*expected(name,value,flags)])
            table=',\n'.join('{'+','.join(map(str,row))+'}' for row in rows)
            (root/'probe.cpp').write_text('''#include "pce/runtime.hpp"
#include <algorithm>
#include <iostream>
#include <stdexcept>
int main(){try{pce::Bus bus;bus.kind[0x80]=pce::BankKind::ram;bus.kind[0xF8]=pce::BankKind::ram;
unsigned rows[][10]={'''+table+'''};
for(auto& r:rows){std::fill(bus.bytes->begin()+0x1F0000,bus.bytes->begin()+0x1F2000,0);(*bus.bytes)[0x1F0005]=0x48;
pce::Cpu s;s.a=0x37;s.x=5;s.y=7;s.p=r[3];s.pc=r[0];(*bus.bytes)[0x100000+(r[0]&8191)]=r[1];(*bus.bytes)[0x100001+(r[0]&8191)]=r[2];
if(pce::generated_step(bus,s,100000)!=pce::Exit::executed || s.a!=r[4] || s.x!=r[5] || s.y!=r[6] || s.p!=r[7] || s.cycles!=r[9] || s.ticks!=r[9]*3 || s.pc!=r[0]+2 || s.native_steps!=1 || s.interpreter_steps)throw std::runtime_error("literal CPU/clock mismatch");
for(unsigned i=0;i<8192;++i)if((*bus.bytes)[0x1F0000+i]!=(i==5?r[8]:0))throw std::runtime_error("literal wholeWRAM mismatch");}
pce::Cpu s;s.pc=0x4000;(*bus.bytes)[0x100000]=0xA9;(*bus.bytes)[0x100001]=0x55;
if(pce::generated_step(bus,s,100000)!=pce::Exit::miss || s.pc!=0x4000 || s.native_steps || s.ticks)throw std::runtime_error("unadmitted operand executed");
std::cout<<"385 independently expected immediate/T/decimal/fullRAM/clock cases and unknown-source refusal passed\\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\\n';return 1;}}
''',encoding='utf-8')
            (root/'CMakeLists.txt').write_text(f'''cmake_minimum_required(VERSION 3.20)
project(Operands LANGUAGES CXX)
set(PCE_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(PCE_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
add_subdirectory("{ROOT.as_posix()}" tool)
pce_add_native_module(objects MODULE module/module.cpp MANIFEST module/module.json)
add_executable(operand-probe probe.cpp)
target_link_libraries(operand-probe PRIVATE pce-runtime ${{objects}})
''',encoding='utf-8')
            compiler=shutil.which('clang++') or shutil.which('g++')
            for command in (['cmake','-S',str(root),'-B',str(root/'build'),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+compiler],['cmake','--build',str(root/'build'),'--target','operand-probe','--parallel','2'],[str(root/'build'/('operand-probe.exe' if os.name=='nt' else 'operand-probe'))]):
                result=subprocess.run(command,capture_output=True,text=True,timeout=180);self.assertEqual(result.returncode,0,result.stdout+result.stderr)

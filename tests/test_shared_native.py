"""Compiled shared dispatch: live data mappings, sparse contexts and refusals."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from pcerecomp import project
from tests.test_shared_emission import emit, shared_rows

ROOT=Path(__file__).resolve().parent.parent
COMPILER=shutil.which('clang++') or shutil.which('g++')


@unittest.skipUnless(COMPILER and shutil.which('cmake') and shutil.which('ninja'),'CMake/Ninja/C++ required')
class SharedNativeTests(unittest.TestCase):
    def test_live_mpr_data_tam_sparse_contexts_variants_and_boundary_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);manifest,_=emit(root,shared_rows(),partition_size=1)
            (root/'probe.cpp').write_text(r'''#include "pce/runtime.hpp"
#include <iostream>
#include <limits>
#include <stdexcept>
int main() {
 try {
  pce::Bus bus;for(unsigned bank=0x80;bank<=0x83;++bank)bus.kind[bank]=pce::BankKind::ram;
  pce::Cpu s;s.clock_divisor=3;const auto deadline=std::numeric_limits<std::uint64_t>::max();
  unsigned checks=0;auto require=[&](bool condition){++checks;if(!condition)throw std::runtime_error("shared guard or literal state mismatch");};
  auto put=[&](unsigned address,std::initializer_list<unsigned char> bytes){for(auto b:bytes)(*bus.bytes)[address++]=b;};
  put(0x100000,{0xea,0xe8,0xc8});put(0x100080,{0xad,0,0x60});put(0x100020,{0xa9,1});
  put(0x100090,{0x43,8});put(0x1000c0,{0x53,8});put(0x101fff,{0xa9});
  (*bus.bytes)[0x102000]=11;(*bus.bytes)[0x104000]=22;
  auto reset=[&](unsigned bank,unsigned pc){s=pce::Cpu{};s.clock_divisor=3;s.mpr[3]=bank;s.pc=pc;};
  auto executed=[&](){require(pce::generated_step(bus,s,deadline)==pce::Exit::executed);require(s.native_steps>0 && s.interpreter_steps==0 && s.guard_misses==0);};
  auto refused=[&](pce::Exit expected=pce::Exit::miss){
   const auto before=s;const auto generation=bus.generation;
   const auto memory=std::make_unique<std::array<std::uint8_t,0x200000>>(*bus.bytes);
   require(pce::generated_step(bus,s,expected==pce::Exit::budget?s.ticks:deadline)==expected);
   require(s.pc==before.pc && s.a==before.a && s.x==before.x && s.y==before.y && s.sp==before.sp && s.p==before.p && s.mpr==before.mpr && s.mpr_latch==before.mpr_latch && s.cycles==before.cycles && s.ticks==before.ticks && s.clock_divisor==before.clock_divisor && s.native_steps==before.native_steps && s.interpreter_steps==before.interpreter_steps && s.guard_misses==before.guard_misses && bus.generation==generation && *bus.bytes==*memory);
  };
  // Context B's first helper is numerically later than its reused successors.
  reset(130,0x4000);executed();executed();executed();require(s.pc==0x4003 && s.x==1 && s.y==1 && s.native_steps==3 && s.cycles==6 && s.ticks==18);
  reset(129,0x4001);executed();executed();require(s.pc==0x4003 && s.native_steps==2 && s.cycles==4 && s.ticks==12);
  reset(129,0x4000);refused(); // Available source, but absent from this full context.
  // The same guarded helper must read the live data mapping, not its first owner.
  reset(129,0x4080);executed();require(s.a==11 && s.pc==0x4083 && s.cycles==5 && s.ticks==15);
  reset(130,0x4080);executed();require(s.a==22 && s.pc==0x4083 && s.cycles==5 && s.ticks==15);
  reset(129,0x4090);executed();require(s.a==129 && s.mpr_latch==129 && s.cycles==4);
  reset(130,0x4090);executed();require(s.a==130 && s.mpr_latch==130 && s.cycles==4);
  reset(129,0x40c0);s.a=131;executed();require(s.mpr[3]==131 && s.cycles==5);s.pc=0x4001;refused();
  // Exact operand variants are never unioned across contexts.
  reset(129,0x4020);executed();require(s.a==1);reset(130,0x4020);refused();
  (*bus.bytes)[0x100021]=2;reset(130,0x4020);executed();require(s.a==2);reset(129,0x4020);refused();
  // The operand fetch at a page boundary belongs to each complete mapping.
  (*bus.bytes)[0x102000]=0x23;(*bus.bytes)[0x104000]=0x23;
  reset(129,0x5fff);executed();require(s.a==0x23 && s.pc==0x6001);
  (*bus.bytes)[0x102000]=0x24;reset(129,0x5fff);refused();reset(130,0x5fff);executed();require(s.a==0x23);
  reset(130,0x4080);s.mpr[7]=1;refused();s.mpr[7]=0;bus.kind[0x80]=pce::BankKind::io;refused();bus.kind[0x80]=pce::BankKind::ram;
  (*bus.bytes)[0x100080]=0xea;refused();(*bus.bytes)[0x100080]=0xad;refused(pce::Exit::budget);
  std::cout<<"{\"passed\":true,\"checks\":"<<checks<<"}\n";
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
''',encoding='utf-8')
            (root/'CMakeLists.txt').write_text(f'''cmake_minimum_required(VERSION 3.20)
project(SharedProof LANGUAGES CXX)
set(PCE_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(PCE_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
add_subdirectory("{ROOT.as_posix()}" tool)
pce_add_native_module(native_objects MODULE module/module.cpp MANIFEST module/module.json)
add_executable(shared-probe probe.cpp)
target_link_libraries(shared-probe PRIVATE pce-runtime ${{native_objects}})
''',encoding='utf-8')
            command=['cmake','-S',str(root),'-B',str(root/'build'),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+COMPILER]
            configured=subprocess.run(command,capture_output=True,text=True,timeout=60)
            self.assertEqual(configured.returncode,0,configured.stdout+configured.stderr)
            compiled=subprocess.run(['cmake','--build',str(root/'build'),'--target','shared-probe','--parallel','2'],capture_output=True,text=True,timeout=180)
            self.assertEqual(compiled.returncode,0,compiled.stdout+compiled.stderr)
            ran=subprocess.run([str(root/'build'/('shared-probe.exe' if os.name=='nt' else 'shared-probe'))],capture_output=True,text=True,timeout=10)
            self.assertEqual(ran.returncode,0,ran.stdout+ran.stderr)
            self.assertTrue(json.loads(ran.stdout)['passed'])
            # CMake and Python package admission reject malformed opt-in metadata.
            path=root/'module/module.json'
            for changes in ({'unshared_partition_count':True},{'unshared_partition_count':-1},
                            {'partition_identity':'guessed'},{'partitioned':False},
                            {'pc_bucket_size':256},{'shared_part_count':True},{'native_span':{}}):
                changed=copy.deepcopy(manifest);changed.update(changes);path.write_text(json.dumps(changed),encoding='utf-8')
                with self.subTest(changes=changes),self.assertRaises(ValueError):project._module_manifest(path)
                rejected=subprocess.run(command,capture_output=True,text=True,timeout=30)
                self.assertNotEqual(rejected.returncode,0,rejected.stdout+rejected.stderr)


if __name__=='__main__':unittest.main()

"""Authored real CD loader sweeps, feedback and native requalification."""
import argparse,hashlib,importlib.util,json,sys,tomllib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
w=load('live_overlay_workflow',Path(__file__).resolve().parents[1]/'live-overlays/workflow.py');f=load('loader_fixture',Path(__file__).with_name('fixture.py'));w.f=f
original_sources=w.sources
def sources():
    return original_sources()|{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),Path(__file__).with_name('fixture.py'))}
w.sources=sources
from pcerecomp.loader_sweep import sweep,write
from pcerecomp.feedback import prepare_feedback
from pcerecomp import project,prepare
from pcerecomp.overlay_snapshot import load_snapshot

def create(out):
    value=w.create(out);write(out/'loader.json',f.loader_plan());write(out/'setup-profile.json',f.setup_profile());return value
def literal_calls(result,out):
    for index,row in enumerate(result['calls']):
        snap=load_snapshot(out/f'snapshot-{index:04d}');group=row['group'];expected=bytearray(f.expected_wram(2,0,released=True,finished=True));expected[0x27]=group
        expected[0x1FC:0x200]=bytes.fromhex('04 E7 FF 3E')
        regions=dict(snap.regions)
        if regions[0x100000]!=f.expected_cd(group) or regions[0x1F0000]!=bytes(expected):raise ValueError('Independent literal complete loader RAM differs')
        cpu=row['after']['host']['cpu']
        if any(cpu[k]!=v for k,v in dict(a=0,x=0,y=0,sp=255,p=7).items()):raise ValueError('Literal returned loader CPU differs')
def qualify(out,generator,cmake_args):
    base=w.qualify(out,generator,cmake_args);descriptor=out/'native/project.toml';build=out/'native-build';checkpoints=out/'native-0/checkpoints'
    discovery=sweep(descriptor,build,checkpoints,'final.pcec',out/'loader.json',out/'loader-reference');literal_calls(discovery,out/'loader-reference')
    recipe=tomllib.loads((out/'native.toml').read_text(encoding='utf-8'));recipe['module']['path']=str(out/'loader-reference/library/library.json');recipe['module']['history_path']=str(out/'observed/history.json');recipe['module']['operand_sharing']=True
    recipe['bios']['path']=str(out/'firmware.bin');recipe['disc']['path']=str(out/'disc.iso');(out/'sweep-native.toml').write_text(prepare._toml(recipe),encoding='utf-8',newline='\n')
    captures=[out/'loader-reference'/name/'capture.jsonl' for name in discovery['sessions']]
    feedback=prepare_feedback(out/'sweep-native.toml',captures,out/'feedback');project.build(out/'feedback/consumer/project.toml',out/'feedback-build',generator=generator,cmake_args=cmake_args)
    routes=[]
    for variant in (0,1):
        reference=w.session(out,f'feedback-reference-{variant}',out/'feedback/consumer/project.toml',out/'feedback-build',reference=True,variant=variant)
        native=w.session(out,f'feedback-native-{variant}',out/'feedback/consumer/project.toml',out/'feedback-build',reference=False,variant=variant,checkpoint='loader-native.pcec' if variant==0 else None)
        for a,b in zip(reference['stages'],native['stages']):
            if not w.exact(a['memory'],b['memory']) or not w.exact(w._projection(a['status']),w._projection(b['status'])):raise ValueError('Feedback native/reference state differs')
        routes.append(native['work'])
    native_sweep=sweep(out/'feedback/consumer/project.toml',out/'feedback-build',out/'feedback-native-0/checkpoints','loader-native.pcec',out/'loader.json',out/'loader-native',reference=False);literal_calls(native_sweep,out/'loader-native')
    for row in native_sweep['calls']:
        window=row['after']['instruction_window']
        if window['interpreter_steps'] or not window['native_steps']:raise ValueError('Native loader window fell back')
    for i,(a,b) in enumerate(zip(discovery['calls'],native_sweep['calls'])):
        first=load_snapshot(out/'loader-reference'/f'snapshot-{i:04d}');second=load_snapshot(out/'loader-native'/f'snapshot-{i:04d}')
        if first.regions!=second.regions or a['after']['host']['cpu']!=b['after']['host']['cpu']:raise ValueError('Actual reference/native loader state differs')
    value=dict(passed=True,tool=w.identity(),sources=sources(),initial=base,feedback=feedback,routes=routes,reference=dict(epochs=discovery['epochs'],identities=discovery['identities']),
        native=dict(epochs=native_sweep['epochs'],identities=native_sweep['identities'],work=[row['after']['instruction_window'] for row in native_sweep['calls']]),
        scope='Two authored real CD sectors; independent and cumulative actual guest loader calls; explicit CPU/stack assistance, literal fullRAM/CPU, source-library feedback, guarded shared-immediate emission and zero-fallback native routes/probes. Original producer receipts preserved. Not retail campaign or hardware/device-clock proof.')
    write(out/'loader-qualification.json',value);return value
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=('create','qualify'));p.add_argument('output',type=Path);p.add_argument('--generator');p.add_argument('--cmake-arg',action='append',default=[]);a=p.parse_args();out=a.output.resolve()
    result=create(out) if a.command=='create' else qualify(out,a.generator,a.cmake_arg);print(json.dumps(dict(passed=result.get('passed',False),tool=result['tool']),indent=2))
if __name__=='__main__':main()

"""Carry genuine discovery captures into a new independently pinned consumer.

Inspired by RondoRecomp's misses-to-seeds iteration. This extends the existing
history interface, never creates fake observations or replaces earlier files.
"""
from pathlib import Path
import hashlib
from . import prepare
from .history import compose_history
from .snapshots import SnapshotStore
from .loader_sweep import write

def prepare_feedback(recipe,captures,output,*,history_version=2,capacity=1048576):
    source,raw,spec=prepare._recipe(recipe);base=source.parent;output=Path(output).absolute()
    if output.exists() or output.is_symlink() or not output.parent.is_dir():raise ValueError('Feedback requires a new output directory')
    if type(captures) not in (tuple,list) or not captures:raise ValueError('Feedback requires genuine capture files')
    store=SnapshotStore();store.bind(source,expected_sha256=hashlib.sha256(raw).hexdigest())
    module=spec['module'];kind=module['kind'];module_path=(base/module['path']).resolve()
    protected=([module_path if module_path.is_dir() else module_path.parent] if kind in ('history','discovery') else
               [module_path.parent/'epochs'] if kind=='overlay' else [module_path.parent/'declared-sources'] if kind=='declared' else [])
    if any(output.is_relative_to(p) for p in protected):raise ValueError('Feedback cannot modify its original compiler-input namespace')
    for name,table in spec.items():
        if name not in ('module','sdk') and type(table) is dict and 'path' in table:table['path']=str((base/table['path']).resolve())
    options=dict(history_version=history_version,capacity=capacity)
    if kind=='capture':options['baseline_inputs']=[module_path]
    elif kind=='profile':options['baseline_profile']=module_path
    elif kind=='history':options['baseline_history']=module_path
    elif module.get('history_path'):options['baseline_history']=(base/module['history_path']).resolve()
    output.mkdir();history=compose_history(captures,output/'history',**options)
    if kind in ('declared','discovery','overlay'):
        module['path']=str(module_path);module['history_path']=str(history.index_path)
    else:
        module['kind']='history';module['path']=str(history.index_path);module.pop('history_path',None)
    module.update(history_version=history_version,capacity=capacity)
    (output/'prepare.toml').write_text(prepare._toml(spec),encoding='utf-8',newline='\n')
    result=prepare.prepare_project(output/'prepare.toml',output/'consumer');store.revalidate();history.revalidate()
    receipt=dict(format='pce-discovery-feedback-1',schema=1,passed=True,compiled=False,executed=False,execution_evidence=False,
        recipe_sha256=hashlib.sha256(raw).hexdigest(),history_sha256=history.index_sha256,preparation=result,
        scope='Genuine new captures and retained original history admitted into a fresh consumer. Declared static roots stay separate. Build and actual native qualification remain required; no original package/capture is rewritten.')
    write(output/'feedback.json',receipt);return receipt

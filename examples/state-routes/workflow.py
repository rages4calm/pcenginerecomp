"""Compare dense and sparse checkpoint routes on the authored widescreen card.

Uses only SDL dummy/software drivers. No GPU, owner media or saves are needed.
Build examples/widescreen first, then supply its binary and generated card.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from examples.widescreen.workflow import command, guest_state, require, session
from pcerecomp.project import sha256, source_identity
from scripts.dev_route import run_plan


def qualify(binary, card, output):
    binary, card, output = binary.resolve(strict=True), card.resolve(strict=True), output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    controllers = ('scripts/dev_client.py', 'scripts/dev_route.py', 'scripts/dev_journal.py',
                   'examples/state-routes/workflow.py', 'examples/widescreen/workflow.py')
    bindings = dict(tool=source_identity(ROOT), binary_sha256=sha256(binary), card_sha256=sha256(card),
                    controller_sources={name: sha256(ROOT/name) for name in controllers})
    context = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    environment = dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_RENDER_DRIVER='software', SDL_AUDIODRIVER='dummy')
    base = command(binary, card, 'guest', 'off', verify=False) + [
        '--hidden', 'on', '--unthrottled', 'on', '--dev-port', '0', '--dev-start-paused', 'on',
        '--checkpoint-dir', str(output), '--checkpoint-context', context]
    report = dict(schema=1, passed=False, bindings=bindings, routes={},
        scope='Authored same-build TCP route comparison; not retail gameplay or cross-build checkpoint migration')
    def save_report():
        (output/'receipt.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    try:
        with session(base, output, 'seed', environment) as client:
            client.advance(4)
            report['seed'] = client.call('save_checkpoint', name='seed.pcec')
            imported = report['seed']['checkpoint']
        for name, pulse, saves in (('dense', 100, 12), ('sparse', 1200, 1)):
            steps = []
            for index in range(saves):
                steps += [dict(op='pulse', port=0, mask=32, frames=pulse),
                          dict(op='checkpoint', name=f'{name}-{index:02}.pcec')]
            plan = dict(schema=2, max_frames=1200, max_seconds=90, steps=steps)
            row = dict(plan=plan, profile_scope='Route plus final guest observations; excludes session quit and connection setup')
            report['routes'][name] = row
            with session(base+['--checkpoint-load', 'seed.pcec'], output, name, environment, profile=True) as client:
                try:
                    row['route'] = run_plan(client, plan)
                    require(row['route']['ok'], str(row['route'].get('error')))
                    row['state'] = guest_state(client)
                finally:
                    row['request_profile'] = client.profile_report()
            row['end_checkpoint_sha256'] = sha256(output/f'{name}-{saves-1:02}.pcec')
            require(row['end_checkpoint_sha256'] == row['route']['checkpoints'][-1]['response']['checkpoint']['sha256'],
                    'Saved checkpoint differs from server acknowledgement')
            require(row['state']['interpreted'] == 0, 'Unexpected interpreter fallback')
            row['newly_retired'] = dict(native=row['state']['native']-imported['native_steps'],
                                       interpreted=row['state']['interpreted']-imported['interpreter_steps'])
            require(row['newly_retired']['native'] > 0 and row['newly_retired']['interpreted'] == 0,
                    'Expected positive newly retired native work with zero fallback')
            save_report()
        dense, sparse = report['routes']['dense'], report['routes']['sparse']
        require(dense['state'] == sparse['state'], 'Dense and sparse guest observations differ')
        require(dense['end_checkpoint_sha256'] == sparse['end_checkpoint_sha256'],
                'Dense and sparse complete encoded checkpoints differ')
        report['passed'] = True
        report['checkpoint_saves'] = dict(dense=12, sparse=1)
        report['elapsed_seconds'] = {name: row['route']['elapsed_seconds'] for name, row in report['routes'].items()}
        report['speedup_observed'] = dense['route']['elapsed_seconds']/sparse['route']['elapsed_seconds']
    except Exception as error:
        report['error'] = dict(type=type(error).__name__, message=str(error))
        raise
    finally:
        save_report()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--card', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    result = qualify(args.binary, args.card, args.out)
    print(json.dumps({key: result[key] for key in ('passed', 'checkpoint_saves', 'elapsed_seconds', 'speedup_observed')}, indent=2))


if __name__ == '__main__':
    main()

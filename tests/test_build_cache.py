"""Authored package/cache integrity and actual cross-process lock checks."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from pcerecomp import build_cache
from pcerecomp.build_cache import BuildCache, MAX_FILES, MAX_MANIFEST_BYTES, contract_identity


CONTRACT = dict(tool='a'*64, abi=26, compiler=dict(sha256='b'*64),
                module=['c'*64], desktop=False)
ROOT = Path(__file__).resolve().parent.parent


def package(parent, name='package'):
    folder=parent/name;folder.mkdir()
    (folder/'pce-consumer.exe').write_bytes(b'MZ-authored-binary\0\xff')
    (folder/'support.dll').write_bytes(b'MZ-authored-library\x01')
    return folder


class BuildCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.base=Path(self.temporary.name)
        self.root=self.base/'cache';self.root.mkdir()
        self.package=package(self.base)

    def tearDown(self):
        self.temporary.cleanup()

    def seed(self):
        with BuildCache(self.root,CONTRACT) as cache:
            manifest=cache.publish(self.package)
            return cache.entry,manifest

    def test_miss_publish_restore_and_immutable_existing_entry(self):
        destination=self.base/'restored'
        with BuildCache(self.root,CONTRACT) as cache:
            self.assertIsNone(cache.restore(destination))
            self.assertFalse(destination.exists())
            manifest=cache.publish(self.package)
            original=(cache.entry/'manifest.json').read_bytes()
            self.assertEqual(cache.publish(self.package),manifest)
            self.assertEqual((cache.entry/'manifest.json').read_bytes(),original)
            self.assertEqual(cache.restore(destination),manifest)
            self.assertEqual({p.name for p in destination.iterdir()},
                             {'pce-consumer.exe','support.dll'})
            self.assertEqual(manifest['files'],[
                dict(name=p.name,bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                     executable=bool(p.stat().st_mode&0o111))
                for p in sorted(self.package.iterdir())])
        self.assertEqual((destination/'pce-consumer.exe').read_bytes(),
                         (self.package/'pce-consumer.exe').read_bytes())

    def test_contract_key_is_canonical_and_snapshot_is_independent(self):
        given=copy.deepcopy(CONTRACT)
        a=BuildCache(self.root,given)
        reversed_contract=dict(reversed(list(CONTRACT.items())))
        self.assertEqual(a.key,BuildCache(self.root,reversed_contract).key)
        self.assertRegex(a.key,r'^[0-9a-f]{64}$')
        given['compiler']['sha256']='d'*64
        self.assertNotEqual(a.key,BuildCache(self.root,given).key)
        with a:
            self.assertEqual(a.contract,CONTRACT)

    def test_compiled_input_identity_pins_complete_canonical_json(self):
        full = dict(tool=dict(sha256='a'*64),
                    graph=dict(units=[dict(source='part.cpp', sha256='b'*64,
                                          headers=[dict(file='runtime.hpp', sha256='c'*64)])]),
                    options=dict(compiler='clang++', flags=['-O3', '-std=c++20']))
        # An independent canonical serialization, not the cache's own helper.
        raw = json.dumps(full, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False).encode('utf-8')
        expected = dict(schema=1, producer='pce-compiled-input-sha256-v1',
                        sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        self.assertEqual(contract_identity(full), expected)
        ordered = dict(reversed(list(full.items())))
        ordered['options'] = dict(reversed(list(full['options'].items())))
        self.assertEqual(contract_identity(ordered), expected)
        for change in (
                lambda value: value['graph']['units'][0]['headers'][0].update(sha256='d'*64),
                lambda value: value['options']['flags'].append('-fno-rtti'),
                lambda value: value['tool'].update(sha256='e'*64),
                lambda value: value['graph']['units'][0].update(source='other.cpp')):
            changed = copy.deepcopy(full)
            change(changed)
            identity = contract_identity(changed)
            self.assertNotEqual(identity['sha256'], expected['sha256'])
            self.assertNotEqual(BuildCache(self.root,identity).key, BuildCache(self.root,expected).key)

    def test_compiled_input_identity_counts_utf8_bytes_and_returns_independent_value(self):
        full = {'path': 'C:/工具/🎮/runtime.hpp'}
        raw = '{"path":"C:/工具/🎮/runtime.hpp"}'.encode('utf-8')
        identity = contract_identity(full)
        self.assertEqual(identity['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(identity['bytes'], len(raw))
        self.assertGreater(identity['bytes'], len(raw.decode('utf-8')))
        full['path'] = 'changed'
        self.assertEqual(identity['sha256'], hashlib.sha256(raw).hexdigest())

    def test_compiled_input_identity_requires_strict_bounded_json(self):
        for value in ([], None, True, {'bad': float('nan')}, {'bad': float('inf')},
                      {'bad': (1,2)}, {1: 'bad'}, {'bad': b'bytes'}, {'bad': '\ud800'}):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                contract_identity(value)
        nested = {}; child = nested
        for _ in range(66):
            child['next'] = {}; child = child['next']
        with self.assertRaises(ValueError):
            contract_identity(nested)
        self.assertEqual(build_cache.MAX_COMPILED_INPUT_BYTES, 64*1024*1024)
        # Exercise the exact byte boundary without allocating a 64 MiB fixture.
        raw = b'{"value":"abc"}'
        with patch.object(build_cache, 'MAX_COMPILED_INPUT_BYTES', len(raw)):
            self.assertEqual(contract_identity({'value': 'abc'})['bytes'], len(raw))
            with self.assertRaisesRegex(ValueError, 'exceeds bound'):
                contract_identity({'value': 'abcd'})
        with patch.object(build_cache, 'MAX_COMPILED_INPUT_BYTES', 12):
            with self.assertRaisesRegex(ValueError, 'exceeds bound'):
                contract_identity({'path': '🎮🎮'})

    def test_large_audited_input_uses_compact_cache_contract_without_raising_cache_bounds(self):
        full = dict(graph=[dict(source=f'part_{i:04d}.cpp', sha256='a'*64,
                                headers=[dict(path=f'header_{j:03d}.hpp', sha256='b'*64)
                                         for j in range(5)])
                           for i in range(835)],
                    options=dict(compiler='clang++', flags=['-O3', '-std=c++20']))
        raw = json.dumps(full, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
        self.assertGreater(len(raw), build_cache.MAX_CONTRACT_BYTES)
        with self.assertRaisesRegex(ValueError, 'contract exceeds bound'):
            BuildCache(self.root,full)
        compact = contract_identity(full)
        self.assertEqual(compact['bytes'], len(raw))
        self.assertEqual(compact['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertLess(len(json.dumps(compact).encode()), 256)
        with BuildCache(self.root,compact) as cache:
            manifest = cache.publish(self.package)
            self.assertEqual(manifest['contract'], compact)
            self.assertLess((cache.entry/'manifest.json').stat().st_size, MAX_MANIFEST_BYTES)
            self.assertEqual(cache.restore(self.base/'large-restored'), manifest)
        self.assertEqual((self.base/'large-restored/pce-consumer.exe').read_bytes(),
                         (self.package/'pce-consumer.exe').read_bytes())
        changed = copy.deepcopy(full)
        changed['graph'][-1]['headers'][-1]['sha256'] = 'd'*64
        with BuildCache(self.root,contract_identity(changed)) as cache:
            self.assertIsNone(cache.restore(self.base/'changed-contract'))
        self.assertFalse((self.base/'changed-contract').exists())
        self.assertEqual(build_cache.MAX_CONTRACT_BYTES, 256*1024)
        self.assertEqual(MAX_MANIFEST_BYTES, 1024*1024)

    def test_unrelated_key_is_a_miss_and_does_not_touch_existing_entry(self):
        entry,_=self.seed();before=(entry/'manifest.json').read_bytes()
        changed=copy.deepcopy(CONTRACT);changed['abi']=CONTRACT['abi']+1
        with BuildCache(self.root,changed) as cache:
            self.assertIsNone(cache.restore(self.base/'new'))
        self.assertEqual((entry/'manifest.json').read_bytes(),before)

    def test_corrupt_payload_is_not_silently_rebuilt_or_restored(self):
        entry,_=self.seed();(entry/'support.dll').write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            with BuildCache(self.root,CONTRACT):pass
        self.assertFalse((self.base/'new').exists())
        self.assertEqual((entry/'support.dll').read_bytes(),b'corrupt')

    def test_missing_extra_and_partial_entries_are_errors(self):
        for mode in ('missing-manifest','missing-payload','extra-payload','directory'):
            root=self.base/mode;root.mkdir()
            with BuildCache(root,CONTRACT) as cache:cache.publish(self.package);entry=cache.entry
            if mode=='missing-manifest':(entry/'manifest.json').unlink()
            elif mode=='missing-payload':(entry/'support.dll').unlink()
            elif mode=='extra-payload':(entry/'extra.dll').write_bytes(b'MZ-extra')
            else:(entry/'extra.dll').mkdir()
            with self.subTest(mode=mode),self.assertRaises((ValueError,OSError)):
                with BuildCache(root,CONTRACT):pass

    def test_unknown_duplicate_nan_and_manifest_types_are_rejected(self):
        mutations=[lambda m:m.update(execution_evidence=True),
                   lambda m:m.update(schema=True),lambda m:m.update(key='0'*64),
                   lambda m:m.update(contract={'not':'this contract'}),
                   lambda m:m['files'][0].update(bytes=True),
                   lambda m:m['files'][0].update(executable=1),
                   lambda m:m['files'][0].update(sha256='A'*64),
                   lambda m:m['files'][0].update(extra='private'),
                   lambda m:m.update(files=[])]
        for index,mutate in enumerate(mutations):
            root=self.base/('type'+str(index));root.mkdir()
            with BuildCache(root,CONTRACT) as cache:m=cache.publish(self.package);path=cache.entry/'manifest.json'
            mutate(m);path.write_text(json.dumps(m))
            with self.subTest(index=index),self.assertRaises(ValueError):
                with BuildCache(root,CONTRACT):pass
        entry,_=self.seed();path=entry/'manifest.json';raw=path.read_bytes()
        for bad in (raw.replace(b'"schema":1',b'"schema":1,"schema":1'),
                    raw.replace(b'"schema":1',b'"schema":NaN'),b'[]',b'\xff'):
            path.write_bytes(bad)
            with self.assertRaises(ValueError):
                with BuildCache(self.root,CONTRACT):pass

    def test_unsafe_manifest_names_and_case_collisions_are_rejected(self):
        for index,name in enumerate(('../outside.exe','/outside.dll','C:outside.exe',
                                     'a/b.dll','a\\b.dll','con.exe','foo.dll.',
                                     'receipt.json','source.cpp','save.bram')):
            root=self.base/('name'+str(index));root.mkdir()
            with BuildCache(root,CONTRACT) as cache:m=cache.publish(self.package);path=cache.entry/'manifest.json'
            m['files'][0]['name']=name;path.write_text(json.dumps(m))
            with self.subTest(name=name),self.assertRaises(ValueError):
                with BuildCache(root,CONTRACT):pass
        entry,m=self.seed();m['files'].append(dict(m['files'][0]));
        (entry/'manifest.json').write_text(json.dumps(m))
        with self.assertRaises(ValueError):
            with BuildCache(self.root,CONTRACT):pass

    def test_source_media_save_and_receipt_files_cannot_be_published(self):
        for name in ('module.cpp','module.hpp','project.toml','receipt.json',
                     'game.chd','syscard.pce','slot.sav','backup.bram','capture.wav'):
            folder=self.base/('bad-'+name);folder.mkdir();(folder/name).write_bytes(b'private')
            with self.subTest(name=name),BuildCache(self.root,CONTRACT) as cache,self.assertRaises(ValueError):
                cache.publish(folder)
        self.assertFalse(any(p.is_dir() for p in self.root.iterdir()))

    def test_extensionless_text_is_not_mistaken_for_an_executable(self):
        folder=self.base/'text';folder.mkdir();(folder/'README').write_text('authored explanatory text')
        with BuildCache(self.root,CONTRACT) as cache,self.assertRaises(ValueError):cache.publish(folder)

    def test_empty_package_empty_artifact_and_file_count_bounds(self):
        empty=self.base/'empty';empty.mkdir()
        with BuildCache(self.root,CONTRACT) as cache:
            with self.assertRaises(ValueError):cache.publish(empty)
            (empty/'empty.exe').touch()
            with self.assertRaises(ValueError):cache.publish(empty)
        many=self.base/'many';many.mkdir()
        for index in range(MAX_FILES+1):(many/(str(index)+'.dll')).write_bytes(b'MZ')
        with BuildCache(self.root,CONTRACT) as cache,self.assertRaises(ValueError):cache.publish(many)
        entry,_=self.seed();(entry/'manifest.json').write_bytes(b' '* (MAX_MANIFEST_BYTES+1))
        with self.assertRaises(ValueError):
            with BuildCache(self.root,CONTRACT):pass

    def test_contract_requires_strict_bounded_json(self):
        for value in ([],None,{'bad':float('nan')},{'bad':float('inf')},
                      {'bad':(1,2)},{1:'bad'},{'bad':b'bytes'}, {'bad':'\ud800'}):
            with self.subTest(value=repr(value)),self.assertRaises(ValueError):BuildCache(self.root,value)
        value={};child=value
        for _ in range(66):child['next']={};child=child['next']
        with self.assertRaises(ValueError):BuildCache(self.root,value)
        with self.assertRaises(ValueError):BuildCache(self.root,{'large':'x'*(256*1024)})

    def test_existing_destination_is_never_touched(self):
        self.seed();destination=self.base/'owner';destination.mkdir()
        sentinel=destination/'sentinel';sentinel.write_bytes(b'owner')
        with BuildCache(self.root,CONTRACT) as cache,self.assertRaises(ValueError):cache.restore(destination)
        self.assertEqual(sentinel.read_bytes(),b'owner')

    def test_entry_changes_during_held_session_are_rejected(self):
        entry,_=self.seed()
        with BuildCache(self.root,CONTRACT) as cache:
            path=entry/'manifest.json';value=path.read_bytes();path.write_bytes(value+b' ')
            with self.assertRaises(ValueError):cache.restore(self.base/'new')
        self.assertFalse((self.base/'new').exists())

    def test_existing_entry_is_not_overwritten_by_different_package(self):
        entry,_=self.seed();original=(entry/'pce-consumer.exe').read_bytes()
        (self.package/'pce-consumer.exe').write_bytes(b'MZ-different')
        with BuildCache(self.root,CONTRACT) as cache,self.assertRaises(ValueError):cache.publish(self.package)
        self.assertEqual((entry/'pce-consumer.exe').read_bytes(),original)

    def test_partial_source_mutation_during_publish_is_rejected_and_cleaned(self):
        original=build_cache._file;changed=False
        def mutate(path,destination=None,owned=None):
            nonlocal changed
            result=original(path,destination,owned)
            if destination is not None and not changed:
                changed=True;(self.package/'support.dll').write_bytes(b'MZ-raced-source')
            return result
        with BuildCache(self.root,CONTRACT) as cache,patch.object(build_cache,'_file',side_effect=mutate):
            with self.assertRaises(ValueError):cache.publish(self.package)
        self.assertFalse(any(p.is_dir() for p in self.root.iterdir()))

    def test_cache_mutation_during_restore_never_publishes_partial_destination(self):
        entry,_=self.seed();original=build_cache._file;changed=False
        def mutate(path,destination=None,owned=None):
            nonlocal changed
            result=original(path,destination,owned)
            if destination is not None and not changed:
                changed=True;(entry/'support.dll').write_bytes(b'MZ-raced-cache')
            return result
        with BuildCache(self.root,CONTRACT) as cache,patch.object(build_cache,'_file',side_effect=mutate):
            with self.assertRaises(ValueError):cache.restore(self.base/'new')
        self.assertFalse((self.base/'new').exists())
        self.assertFalse(list(self.base.glob('.new.cache-*')))

    def test_destination_race_refuses_without_overwriting_owner_content(self):
        self.seed();original=build_cache._rename_new;destination=self.base/'new'
        def collide(source,target):
            target.mkdir();(target/'owner').write_bytes(b'keep')
            return original(source,target)
        with BuildCache(self.root,CONTRACT) as cache,patch.object(build_cache,'_rename_new',side_effect=collide):
            with self.assertRaises(OSError):cache.restore(destination)
        self.assertEqual((destination/'owner').read_bytes(),b'keep')

    def test_interrupted_publication_is_not_silently_removed_or_rebuilt(self):
        cache=BuildCache(self.root,CONTRACT);partial=self.root/('.'+cache.key+'.publish-interrupted');partial.mkdir()
        (partial/'partial.exe').write_bytes(b'partial')
        with self.assertRaises(ValueError):
            with cache:pass
        self.assertEqual((partial/'partial.exe').read_bytes(),b'partial')

    def test_methods_require_context_and_session_cannot_be_reused(self):
        cache=BuildCache(self.root,CONTRACT)
        with self.assertRaises(ValueError):cache.publish(self.package)
        with self.assertRaises(ValueError):cache.restore(self.base/'new')
        with cache:pass
        with self.assertRaises(ValueError):cache.__enter__()

    def test_root_parent_and_artifacts_refuse_symlinks(self):
        outside=self.base/'outside';outside.mkdir()
        link=self.base/'linked-cache'
        try:link.symlink_to(self.root,target_is_directory=True)
        except OSError as error:self.skipTest('Symlink creation unavailable: '+str(error))
        with self.assertRaises(ValueError):
            with BuildCache(link,CONTRACT):pass
        victim=outside/'owner.exe';victim.write_bytes(b'owner')
        (self.package/'support.dll').unlink();(self.package/'support.dll').symlink_to(victim)
        with BuildCache(self.root,CONTRACT) as cache,self.assertRaises(ValueError):cache.publish(self.package)
        self.assertEqual(victim.read_bytes(),b'owner')

    def test_hardlinked_artifact_is_refused(self):
        target=self.base/'owner.dll';target.write_bytes(b'owner')
        (self.package/'support.dll').unlink()
        try:os.link(target,self.package/'support.dll')
        except OSError as error:self.skipTest('Hardlinks unavailable: '+str(error))
        with BuildCache(self.root,CONTRACT) as cache,self.assertRaises(ValueError):cache.publish(self.package)
        self.assertEqual(target.read_bytes(),b'owner')

    def test_process_lock_contention_and_release_on_process_exit(self):
        script=('import sys,json\nfrom pathlib import Path\nfrom pcerecomp.build_cache import BuildCache\n'
                'with BuildCache(Path(sys.argv[1]),json.loads(sys.argv[2])):\n'
                ' print("LOCKED",flush=True)\n sys.stdin.readline()\n')
        child=subprocess.Popen([sys.executable,'-u','-c',script,str(self.root),json.dumps(CONTRACT)],
            cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(),'LOCKED')
            with self.assertRaises(ValueError):
                with BuildCache(self.root,CONTRACT):pass
            child.terminate();child.wait(timeout=5)
            with BuildCache(self.root,CONTRACT) as cache:self.assertIsNone(cache.restore(self.base/'new'))
        finally:
            if child.poll() is None:child.kill();child.wait(timeout=5)
            child.stdin.close();child.stdout.close();child.stderr.close()

    def test_platform_executable_name_preserves_executable_mode(self):
        folder=self.base/'platform';folder.mkdir()
        binary=folder/('pce-consumer.exe' if os.name=='nt' else 'pce-consumer')
        binary.write_bytes(b'MZ-authored' if os.name=='nt' else b'\x7fELF-authored');binary.chmod(0o755)
        with BuildCache(self.root,CONTRACT) as cache:
            cache.publish(folder);cache.restore(self.base/'platform-restored')
        self.assertTrue((self.base/'platform-restored'/binary.name).stat().st_mode&0o111)


if __name__=='__main__':unittest.main()

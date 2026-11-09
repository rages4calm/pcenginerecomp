"""Authored content-addressed history transport and provenance refusals."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pcerecomp import history, observations
from pcerecomp.abi import ABI

MPR = [255, 248, 128, 129, 130, 131, 132, 0]


def row(pc=0x4000, data=(0xA9, 42), *, mpr=None, native=0, interpreted=1):
    mapping = list(MPR if mpr is None else mpr)
    physical = [(mapping[((pc+i)&65535)>>13]<<13)|((pc+i)&8191) for i in range(len(data))]
    return dict(pc=pc, data=list(data), mpr=mapping, physical=physical,
                native_hits=native, interpreted_hits=interpreted)


def capture(rows=None, *, abi=18, origin=None, policy=None):
    entries = [row()] if rows is None else rows
    result = dict(schema=1, runtime_abi=abi, capacity=65536, complete=True,
                  dropped_instructions=0, unreadable_instructions=0,
                  retired_instructions=sum(x['native_hits']+x['interpreted_hits'] for x in entries),
                  observations=entries)
    if origin is not None:
        result['checkpoint_origin'] = origin
    if policy is not None:
        result['execution_policy'] = policy
    return result


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.serial = 0

    def write(self, value=None, *, raw=None):
        self.serial += 1
        path = self.root/('capture-'+str(self.serial)+'.json')
        path.write_bytes(json.dumps(capture() if value is None else value).encode('utf-8') if raw is None else raw)
        return path

    def make(self, values=None, name='history', **options):
        return history.compose_history([self.write()] if values is None else values,
                                       self.root/name, **options)

    def rewrite(self, admitted, mutate):
        value = admitted.index
        mutate(value)
        admitted.index_path.write_bytes(observations._canonical(value)+b'\n')

    def test_exact_original_bytes_portable_graph_and_legacy_membership(self):
        origin = dict(sha256='a'*64, ticks=10, frame=2, native_steps=3, interpreter_steps=4)
        first = self.write(capture([row(native=2, interpreted=3)]))
        second = self.write(capture([row(0x4100,(0xA2,7),interpreted=8)],abi=26,origin=origin))
        admitted = self.make([second,first])
        legacy = observations.compose_observation_profile([first,second])
        self.assertEqual(admitted.instructions, observations.validate_observation_profile(legacy))
        self.assertEqual(admitted.input_metadata, observations.observation_profile_provenance(legacy))
        self.assertEqual(admitted.index['historical_totals'],dict(native_hits=2,interpreted_hits=11,retired_instructions=13))
        self.assertNotIn('runtime_abi',admitted.index)
        self.assertNotIn('checkpoint_origin',admitted.index)
        self.assertIs(admitted.index['execution_evidence'],False)
        self.assertEqual({x['runtime_abi'] for x in admitted.input_metadata},{18,26})
        self.assertEqual(next(x for x in admitted.input_metadata if x['runtime_abi']==26)['checkpoint_origin'],origin)
        for path in (first,second):
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual((admitted.index_path.parent/'captures'/(digest+'.json')).read_bytes(),path.read_bytes())
        self.assertEqual(admitted.artifact_bindings['history.json']['sha256'],admitted.index_sha256)
        self.assertEqual(history.load_history(admitted.index_path.parent).index_sha256,admitted.index_sha256)
        admitted.revalidate()

    def test_order_duplicate_arguments_and_exact_serializations(self):
        a=self.write();b=self.write(capture([row(data=(0xA9,43))]));alias=self.write(raw=a.read_bytes())
        one=self.make([a,b],name='one');two=self.make([b,alias,a,b],name='two')
        self.assertEqual(one.index_sha256,two.index_sha256)
        self.assertEqual(set(one.artifact_bindings),set(two.artifact_bindings))
        different=self.write(raw=(json.dumps(capture(),indent=2)+'\n').encode())
        three=self.make([a,different],name='three')
        self.assertEqual(len(three.index['inputs']),2)
        self.assertEqual(three.index['selection_counts']['selected_contributions'],2)
        self.assertEqual(three.index['historical_totals']['retired_instructions'],2)

    def test_additive_selection_retains_zero_novelty_and_lowest_sha_owner(self):
        a=self.write(capture([row(native=2,interpreted=0)]));b=self.write(capture([row(interpreted=3)],abi=26))
        first=self.make([a,b],name='baseline')
        overlap=self.write(capture([row(native=100,interpreted=0)]))
        x=self.write(capture([row(0x4100,(0xA9,44),native=7,interpreted=0)]))
        y=self.write(capture([row(0x4100,(0xA9,44),interpreted=9)]))
        second=self.make([y,overlap,x],name='added',baseline_history=first.index_path)
        self.assertEqual(len(second.index['inputs']),5)
        self.assertEqual(second.index['selection_stages'][0],first.index['selection_stages'][0])
        self.assertEqual(second.index['selection_counts'],dict(original_contributions=5,selected_contributions=3,omitted_contributions=2))
        self.assertEqual(second.index['historical_totals'],dict(native_hits=109,interpreted_hits=12,retired_instructions=121))
        shard=second.index_path.parent/'catalogue'/(second.index['catalogue'][0]['sha256']+'.jsonl')
        entries=[json.loads(line) for line in shard.read_bytes().splitlines()]
        self.assertEqual(len(entries[0]['contributions']),2)
        self.assertEqual(entries[1]['contributions'][0]['input_sha256'],min(hashlib.sha256(p.read_bytes()).hexdigest()for p in(x,y)))
        third=self.make([],name='converted',baseline_history=second.index_path)
        self.assertEqual(third.index_sha256,second.index_sha256)

    def test_legacy_v1_and_v2_baseline_conversion_preserves_all_originals(self):
        a=self.write();b=self.write(capture([row(0x4100,(0xA2,1))],abi=26))
        profile=observations.compose_observation_profile([a]);p=self.root/'v1.json';p.write_bytes(observations.serialize_observation_profile(profile))
        added=observations.compose_additive_observation_profile([b],baseline_profile=p)
        q=self.root/'v2.json';q.write_bytes(observations.serialize_observation_profile(added))
        for index,path in enumerate((p,q)):
            admitted=self.make([],name='from-'+str(index),baseline_profile=path)
            legacy=json.loads(path.read_bytes())
            self.assertEqual(admitted.instructions,observations.validate_observation_profile(legacy))
            self.assertEqual(admitted.input_metadata,observations.observation_profile_provenance(legacy))
            self.assertEqual(admitted.index['selection_stages'],legacy.get('selection_stages',[[x['sha256'] for x in legacy['inputs']]]))

    def test_reference_policy_and_origins_remain_per_input(self):
        policy=dict(schema=1,reference_enabled=True,selected=True,configured_tier='native',effective_policy='interpreter',effective_native_span=0)
        old=self.write(capture(abi=18));new=self.write(capture([row(0x4100,(0xEA,),interpreted=4)],abi=ABI,policy=policy))
        admitted=self.make([old,new]);metadata=next(x for x in admitted.input_metadata if x['runtime_abi']==ABI)
        self.assertEqual(metadata['execution_policy'],policy)
        self.assertNotIn('execution_policy',admitted.index)
        self.assertNotIn('execution_policy',next(x for x in admitted.input_metadata if x['runtime_abi']==18))

    def test_revalidate_checks_content_even_with_original_timestamps(self):
        admitted=self.make();pin=next(v for k,v in admitted.artifact_bindings.items()if k.startswith('captures/'))
        path=pin['path'];before=path.stat();raw=path.read_bytes();path.write_bytes(raw.replace(b'42',b'43'));os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
        with self.assertRaisesRegex(ValueError,'SHA256'):admitted.revalidate()
        with self.assertRaises(ValueError):history.load_history(admitted.index_path)

    def test_original_source_changes_do_not_rewrite_the_copied_history(self):
        path=self.write();raw=path.read_bytes();admitted=self.make([path]);path.write_text('changed',encoding='utf-8')
        admitted.revalidate();self.assertEqual(next(x['path'] for k,x in admitted.artifact_bindings.items()if k.startswith('captures/')).read_bytes(),raw)

    def test_cached_catalogue_tamper_cannot_be_blessed_by_new_hashes(self):
        admitted=self.make();index=admitted.index;ref=index['catalogue'][0];old=admitted.index_path.parent/'catalogue'/(ref['sha256']+'.jsonl')
        value=json.loads(old.read_bytes());value['native_hits']=99;raw=observations._canonical(value)+b'\n';digest=hashlib.sha256(raw).hexdigest();new=old.with_name(digest+'.jsonl');old.rename(new);new.write_bytes(raw)
        index['catalogue'][0]=dict(sha256=digest,size_bytes=len(raw),identity_count=1);index['catalogue_sha256']=digest;admitted.index_path.write_bytes(observations._canonical(index)+b'\n')
        with self.assertRaisesRegex(ValueError,'catalogue rows'):history.load_history(admitted.index_path)

    def test_unknown_fields_bad_types_and_cached_totals_refuse(self):
        for changes in ({'schema':True},{'execution_evidence':0},{'capacity':True},{'extra':1},
                        {'selection_policy':'guessed'}, {'historical_totals':{'native_hits':999}}):
            with self.subTest(changes=changes):
                admitted=self.make(name='bad-'+str(self.serial));self.rewrite(admitted,lambda value:value.update(changes))
                with self.assertRaises(ValueError):history.load_history(admitted.index_path)

    def test_stages_require_exact_disjoint_canonical_original_membership(self):
        for stages in ([],[[]],[['0'*64]],[['bad']]):
            with self.subTest(stages=stages):
                admitted=self.make(name='stages-'+str(self.serial));self.rewrite(admitted,lambda value:value.update(selection_stages=stages))
                with self.assertRaises(ValueError):history.load_history(admitted.index_path)
        a=self.write();b=self.write(capture([row(0x4100,(0xA2,1))]));admitted=self.make([a,b],name='dups');digests=[x['sha256']for x in admitted.index['inputs']]
        self.rewrite(admitted,lambda value:value.update(selection_stages=[[digests[0]],[digests[0],digests[1]]]))
        with self.assertRaises(ValueError):history.load_history(admitted.index_path)

    def test_missing_extra_traversal_and_duplicate_references_refuse(self):
        admitted=self.make(name='missing');pin=next(v for k,v in admitted.artifact_bindings.items()if k.startswith('captures/'));pin['path'].unlink()
        with self.assertRaises(ValueError):history.load_history(admitted.index_path)
        admitted=self.make(name='extra');(admitted.index_path.parent/'captures'/'unlisted.json').write_bytes(b'{}')
        with self.assertRaises(ValueError):admitted.revalidate()
        for change in (lambda x:x['inputs'][0].update(sha256='../outside'),lambda x:x['inputs'][0].update(path='../outside'),lambda x:x['inputs'].append(copy.deepcopy(x['inputs'][0]))):
            admitted=self.make(name='reference-'+str(self.serial));self.rewrite(admitted,change)
            with self.assertRaises(ValueError):history.load_history(admitted.index_path)

    def test_links_nonregular_files_and_linked_parents_refuse(self):
        source=self.write();link=self.root/'source-link.json';link.symlink_to(source)
        with self.assertRaises(ValueError):self.make([link],name='input-link')
        admitted=self.make(name='hard');blob=next(v['path']for k,v in admitted.artifact_bindings.items()if k.startswith('captures/'));os.link(blob,self.root/'hard-alias.json')
        with self.assertRaises(ValueError):history.load_history(admitted.index_path)
        admitted=self.make(name='parent');alias=self.root/'parent-link';alias.symlink_to(admitted.index_path.parent,target_is_directory=True)
        with self.assertRaises(ValueError):history.load_history(alias/'history.json')

    def test_truncated_or_noncanonical_index_and_catalogue_refuse(self):
        for raw in (b'{',b'{}\n',b'\xef\xbb\xbf{}\n'):
            admitted=self.make(name='json-'+str(self.serial));admitted.index_path.write_bytes(raw)
            with self.assertRaises(ValueError):history.load_history(admitted.index_path)
        admitted=self.make(name='pretty');admitted.index_path.write_text(json.dumps(admitted.index,indent=2),encoding='utf-8')
        with self.assertRaises(ValueError):history.load_history(admitted.index_path)

    def test_mutable_public_views_do_not_change_admitted_facts(self):
        admitted=self.make();digest=admitted.index_sha256
        admitted.index['inputs'].clear();admitted.input_metadata.clear();admitted.instructions.clear();admitted.artifact_bindings.clear()
        self.assertEqual(admitted.index_sha256,digest);self.assertEqual(len(admitted.instructions),1);admitted.revalidate()

    def test_counter_overflow_capacity_and_incomplete_raw_refuse_before_output(self):
        huge=self.write(capture([row(native=(1<<64)-1,interpreted=0)]));one=self.write(capture([row(native=1,interpreted=0)]))
        with self.assertRaises(ValueError):self.make([huge,one],name='overflow')
        self.assertFalse((self.root/'overflow').exists())
        first=self.write();second=self.write(capture([row(0x4100,(0xA2,1))]))
        with self.assertRaises(ValueError):self.make([first,second],name='capacity',capacity=1)
        self.assertFalse((self.root/'capacity').exists())
        incomplete=capture();incomplete.update(complete=False,dropped_instructions=1,retired_instructions=2)
        with self.assertRaises(ValueError):self.make([self.write(incomplete)],name='incomplete')
        self.assertFalse((self.root/'incomplete').exists())

    def test_new_output_only_and_baseline_descendant_is_never_created(self):
        admitted=self.make();before={name:pin['path'].read_bytes()for name,pin in admitted.artifact_bindings.items()}
        with self.assertRaises(ValueError):history.compose_history([],admitted.index_path.parent,baseline_history=admitted.index_path)
        with self.assertRaises(ValueError):history.compose_history([],admitted.index_path.parent/'nested',baseline_history=admitted.index_path)
        self.assertFalse((admitted.index_path.parent/'nested').exists())
        self.assertEqual({name:pin['path'].read_bytes()for name,pin in admitted.artifact_bindings.items()},before)

    def test_index_is_published_last_and_partial_graph_cannot_be_loaded(self):
        real=history._write_new
        def fail_index(path,raw):
            if path.name=='history.json':raise OSError('authored interrupted publication')
            return real(path,raw)
        with patch.object(history,'_write_new',side_effect=fail_index):
            with self.assertRaises(OSError):self.make(name='partial')
        self.assertFalse((self.root/'partial'/'history.json').exists())
        with self.assertRaises(ValueError):history.load_history(self.root/'partial')

    def test_sharding_is_deterministic_and_every_derived_row_is_checked(self):
        values=[row(0x4000+i,(0xEA,),interpreted=1)for i in range(12)]
        source=self.write(capture(values));
        with patch.object(history,'MAX_SHARD_IDENTITIES',3):admitted=self.make([source],name='shards')
        self.assertEqual([x['identity_count']for x in admitted.index['catalogue']],[3,3,3,3])
        admitted.revalidate();loaded=history.load_history(admitted.index_path);self.assertEqual(len(loaded.instructions),12)
        digest=hashlib.sha256(b''.join((admitted.index_path.parent/'catalogue'/(x['sha256']+'.jsonl')).read_bytes()for x in admitted.index['catalogue'])).hexdigest()
        self.assertEqual(digest,admitted.index['catalogue_sha256'])

    def test_transport_independent_ctime_does_not_replace_content_checks(self):
        source=self.write();real=history.os.fstat
        class DescriptorStat:
            def __init__(self,value):self.value=value
            def __getattr__(self,name):
                return self.value.st_ctime_ns+1234567 if name=='st_ctime_ns' else getattr(self.value,name)
        with patch.object(history.os,'fstat',side_effect=lambda fd:DescriptorStat(real(fd))):
            admitted=self.make([source],name='ctime')
        admitted.revalidate()

    def test_legacy_limits_are_unchanged_while_transport_is_independent(self):
        source=self.write()
        with patch.object(observations,'MAX_TOTAL_INPUT_BYTES',1),patch.object(observations,'MAX_PROFILE_BYTES',1):
            with self.assertRaises(ValueError):observations.compose_observation_profile([source])
            admitted=self.make([source],name='external')
        admitted.revalidate()
        self.assertEqual(observations.MAX_TOTAL_INPUT_BYTES,64*1024*1024)
        self.assertEqual(observations.MAX_PROFILE_BYTES,128*1024*1024)

    def test_empty_catalogue_and_bounded_input_iterables(self):
        source=self.write(capture([]));admitted=self.make([source],name='empty')
        self.assertEqual(admitted.instructions,[])
        self.assertEqual(admitted.index['catalogue'],[])
        self.assertEqual(admitted.index['catalogue_sha256'],hashlib.sha256(b'').hexdigest())
        from itertools import repeat
        with self.assertRaises(ValueError):self.make(repeat(source),name='infinite')
        self.assertFalse((self.root/'infinite').exists())

    def test_encoding_and_transport_bounds_refuse_explicitly(self):
        value=json.dumps(capture())
        for number,raw in enumerate((value.encode('utf-16'),value.encode('utf-16-le'),value.encode('utf-16-be'),value.encode('utf-32-le'),b'\xef\xbb\xbf'+value.encode())):
            source=self.write(raw=raw)
            with self.assertRaisesRegex(ValueError,'UTF-8'):self.make([source],name='encoding-'+str(number))
        source=self.write()
        with patch.object(history,'MAX_RAW_BYTES',1):
            with self.assertRaises(ValueError):self.make([source],name='raw-bound')
        self.assertFalse((self.root/'raw-bound').exists())
        admitted=self.make([source],name='index-bound')
        with patch.object(history,'MAX_INDEX_BYTES',1):
            with self.assertRaises(ValueError):history.load_history(admitted.index_path)
        with patch.object(history,'MAX_SHARD_BYTES',1):
            with self.assertRaises(ValueError):history.load_history(admitted.index_path)

    def test_changed_original_during_copy_never_publishes_index(self):
        source=self.write();real=history._write_new
        def change_original(path,raw):
            result=real(path,raw)
            if path.parent.name=='captures':source.write_bytes(b'changed')
            return result
        with patch.object(history,'_write_new',side_effect=change_original):
            with self.assertRaises(ValueError):self.make([source],name='changed-source')
        self.assertFalse((self.root/'changed-source'/'history.json').exists())

    def test_reference_and_shard_bound_types_are_strict(self):
        mutations=(lambda x:x['inputs'][0].update(size_bytes=True),
                   lambda x:x['catalogue'][0].update(identity_count=True),
                   lambda x:x['catalogue'].append(copy.deepcopy(x['catalogue'][0])),
                   lambda x:x.update(catalogue_sha256='0'*64),
                   lambda x:x.update(selection_counts=dict(original_contributions=True,selected_contributions=1,omitted_contributions=0)))
        for mutation in mutations:
            admitted=self.make(name='strict-'+str(self.serial));self.rewrite(admitted,mutation)
            with self.assertRaises(ValueError):history.load_history(admitted.index_path)


if __name__=='__main__':unittest.main()

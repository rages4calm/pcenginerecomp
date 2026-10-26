"""Synthetic stall-journal admission controls; no engine-correctness claim."""
import copy
import hashlib
import unittest

from scripts.irq_stall_reference import (
    KERNEL_FIELDS, kernel_shape, qualify_block_spans, qualify_comparison, qualify_spans,
)


def kernel(**values):
    result = {field: 0 for field in KERNEL_FIELDS}
    result.update(divider=4, burst=1, bg_start=1365, read_pending=1)
    result.update(values)
    return result


def span(before, requested, context, extra, clocked, pending, irr, finish_irr,
         read=1, finish_read=1):
    start = kernel(cpu_extra=extra, cpu_clocked=clocked, cpu_pending=pending,
                   irr=irr, read_pending=read, hpos=before)
    end = dict(start, irr=finish_irr, read_pending=finish_read,
               hpos=before+requested)
    return dict(before=before, requested=requested, after=before+requested,
                context=context, extra_before=extra, clocked_before=clocked,
                pending_before=pending, p_before=0, mask_before=0,
                source_before=start, source_after=end,
                pending_after_inside_callback=pending,
                after_phase='before-cpu-resample' if context == 'inline' else 'no-cpu-resample')


class IrqStallReferenceChecks(unittest.TestCase):
    def fixture(self):
        # Fast fixed memory wait and genuine dynamic waits both last3ticks.
        # The original extra-counter increments distinguish them.
        clocks = [span(0, 3, 'inline', 0, 0, 0, 0, 0),
                  span(3, 3, 'inline', 3, 3, 0, 0, 1),
                  span(6, 3, 'inline', 6, 6, 1, 1, 3, finish_read=0),
                  span(9, 6, 'wrapper', 6, 9, 3, 3, 3, read=0, finish_read=0)]
        return dict(clock_detail='full-kernel', clocks=clocks,
                    entry=dict(ticks=0, clock_divisor=3), state=dict(ticks=15),
                    internal_clocked_ticks=9, extra_ticks=6)

    def reject(self, mutation, message=None):
        row = self.fixture(); mutation(row)
        if message:
            with self.assertRaisesRegex(ValueError, message): qualify_spans(row)
        else:
            with self.assertRaises(ValueError): qualify_spans(row)

    def test_fixed_fast_wait_is_not_counted_as_dynamic(self):
        result = qualify_spans(self.fixture(), dict(extra_ticks=6, internal_clocked_ticks=9, fixed_wait_count=1))
        self.assertEqual(result['fixed_indices'], [0])
        self.assertEqual(result['dynamic_indices'], [1, 2])
        self.assertEqual(result['wrapper'], [6])
        self.assertEqual([edge['source'] for edge in result['source_edges']], ['irq2', 'irq1'])

    def test_complete_typed_kernel_is_required(self):
        value = kernel(); kernel_shape(value)
        for mutation in (lambda k: k.pop('vram_bus'),
                         lambda k: k.update(unclaimed=0),
                         lambda k: k.update(cpu_p=True),
                         lambda k: k.update(cpu_mask=False),
                         lambda k: k.update(cpu_p=256),
                         lambda k: k.update(read_pending=2),
                         lambda k: k.update(divider=1),
                         lambda k: k.update(hpos=2**31)):
            changed = copy.deepcopy(value); mutation(changed)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): kernel_shape(changed)

    def test_cpu_irq_bit_fields_are_bounded_to_three_bits(self):
        for field in ('cpu_mask', 'irr', 'cpu_pending'):
            kernel_shape(kernel(**{field: 7}))
            for value in (-1, 8, 255, True):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    kernel_shape(kernel(**{field: value}))

    def test_missing_clock_or_kernel_fields_are_refused(self):
        for mutation in (lambda r: r.update(clocks=[]),
                         lambda r: r['clocks'][1].pop('source_before'),
                         lambda r: r['clocks'][1]['source_after'].pop('dma_pending'),
                         lambda r: r['clocks'][1].update(unclaimed=0)):
            with self.subTest(mutation=mutation): self.reject(mutation)

    def test_partition_scalar_and_full_kernel_must_agree(self):
        for field in ('cpu_extra', 'cpu_clocked', 'cpu_pending', 'cpu_p', 'cpu_mask'):
            with self.subTest(field=field):
                self.reject(lambda r, f=field: r['clocks'][1]['source_before'].__setitem__(f, 1))

    def test_dynamic_extra_increment_and_actual_three_tick_clock_are_required(self):
        self.reject(lambda r: r['clocks'][1].update(extra_before=2))
        self.reject(lambda r: r['clocks'][1].update(requested=4, after=7))
        self.reject(lambda r: r.update(extra_ticks=3))
        self.reject(lambda r: r.update(internal_clocked_ticks=6))

    def test_coherent_extra_counter_tamper_cannot_reclassify_a_span(self):
        def mutation(row):
            value = row['clocks'][1]
            value.update(extra_before=0)
            value['source_before']['cpu_extra'] = value['source_after']['cpu_extra'] = 0
        self.reject(mutation)

    def test_dynamic_wait_requires_a_real_pending_queue(self):
        def mutation(row):
            for name in ('source_before', 'source_after'):
                row['clocks'][1][name].update(read_pending=0, write_pending=0)
        self.reject(mutation)

    def test_device_callback_exit_cannot_claim_cpu_resampling(self):
        self.reject(lambda r: r['clocks'][1].update(pending_after_inside_callback=1))
        self.reject(lambda r: r['clocks'][1]['source_after'].update(cpu_pending=1))
        self.reject(lambda r: r['clocks'][1]['source_after'].update(cpu_clocked=6))
        self.reject(lambda r: r['clocks'][1]['source_after'].update(cpu_extra=6))

    def test_next_dynamic_callback_witnesses_actual_irq_sample(self):
        def mutation(row):
            value = row['clocks'][2]
            value.update(pending_before=0, pending_after_inside_callback=0)
            value['source_before']['cpu_pending'] = value['source_after']['cpu_pending'] = 0
        self.reject(mutation, 'sampling')

    def test_cpu_I_and_irq_mask_gate_the_next_sample(self):
        for status, mask, expected in ((4, 0, 0), (0, 1, 0), (0, 0, 1)):
            row = self.fixture()
            for index in (0, 1, 2):
                value = row['clocks'][index]
                value.update(p_before=status, mask_before=mask)
                for name in ('source_before', 'source_after'):
                    value[name].update(cpu_p=status, cpu_mask=mask)
            value = row['clocks'][2]
            value.update(pending_before=expected, pending_after_inside_callback=expected)
            value['source_before']['cpu_pending'] = value['source_after']['cpu_pending'] = expected
            self.assertEqual(qualify_spans(row)['dynamic_indices'], [1, 2])

    def test_consecutive_dynamic_kernels_cannot_jump_without_clocks(self):
        self.reject(lambda r: r['clocks'][2]['source_before'].update(dma_pending=7))

    def test_first_dynamic_may_follow_port_queueing_after_fixed_clock(self):
        row = self.fixture()
        # A port access can queue work after the fixed clock returns. This
        # differs from adjacent iterations of one WaitForVramAccess loop.
        row['clocks'][0]['source_after']['read_pending'] = 0
        self.assertEqual(qualify_spans(row)['dynamic_indices'], [1, 2])

    def test_genuine_pending_write_queue_also_qualifies_as_a_wait(self):
        row = self.fixture()
        for value in row['clocks']:
            for name in ('source_before', 'source_after'):
                value[name]['write_pending'] = value[name]['read_pending']
                value[name]['read_pending'] = 0
        self.assertEqual(qualify_spans(row)['dynamic_indices'], [1, 2])

    def test_fixed_wait_requires_cpu_divisor_even_if_clock_chain_is_coherent(self):
        row = self.fixture(); row['entry']['clock_divisor'] = 12
        with self.assertRaises(ValueError): qualify_spans(row)

    def test_wrapper_is_last_and_does_not_resample_cpu(self):
        self.reject(lambda r: r['clocks'][3].update(after_phase='before-cpu-resample'))
        self.reject(lambda r: r['clocks'][3].update(context='inline'))
        self.reject(lambda r: r['clocks'][0].update(context='wrapper', after_phase='no-cpu-resample'))
        self.reject(lambda r: r['clocks'][3].update(clocked_before=6))
        self.reject(lambda r: r['clocks'][3].update(extra_before=3))

    def test_return_and_final_snapshots_bind_the_actual_wrapper_and_counters(self):
        row = self.fixture()
        row['kernel_at_return'] = copy.deepcopy(row['clocks'][-1]['source_before'])
        row['kernel_final'] = copy.deepcopy(row['clocks'][-1]['source_after'])
        self.assertEqual(qualify_spans(row)['wrapper'], [6])
        for name, field, value in (('kernel_at_return', 'cpu_clocked', 0),
                                   ('kernel_at_return', 'cpu_extra', 0),
                                   ('kernel_at_return', 'cpu_pending', 0),
                                   ('kernel_final', 'hpos', 14),
                                   ('kernel_final', 'read_pending', 1)):
            changed = copy.deepcopy(row); changed[name][field] = value
            with self.subTest(name=name, field=field), self.assertRaises(ValueError):
                qualify_spans(changed)
        changed = copy.deepcopy(row)
        changed['clocks'].pop(); changed['state']['ticks'] = 9
        with self.assertRaisesRegex(ValueError, 'wrapper drain'): qualify_spans(changed)
        changed = copy.deepcopy(row); changed['clock_detail'] = 'partition-only'
        for value in changed['clocks']:
            for field in ('source_before', 'source_after', 'pending_after_inside_callback', 'after_phase'):
                value.pop(field)
        with self.assertRaisesRegex(ValueError, 'wrapper drain'): qualify_spans(changed)

    def test_clocks_close_exactly_and_source_times_are_retained(self):
        self.reject(lambda r: r['clocks'][2].update(before=7))
        self.reject(lambda r: r['clocks'][2].update(after=10))
        self.reject(lambda r: r.update(state=dict(ticks=16)))
        row = self.fixture(); before = copy.deepcopy(row)
        qualify_spans(row)
        self.assertEqual(row, before)

    def test_declared_independent_wait_literals_are_exact(self):
        for field, value in (('extra_ticks', 3), ('internal_clocked_ticks', 6), ('fixed_wait_count', 2)):
            wanted = dict(extra_ticks=6, internal_clocked_ticks=9, fixed_wait_count=1)
            wanted[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): qualify_spans(self.fixture(), wanted)

    def test_exact_partition_pins_prefix_stall_suffix_and_wrapper_positions(self):
        wanted = dict(extra_ticks=6, internal_clocked_ticks=9, fixed_wait_count=1,
                      clock_partition=dict(prefix=[3], stall_count=2, suffix=[], drain=6))
        self.assertEqual(qualify_spans(self.fixture(), wanted)['dynamic_indices'], [1, 2])
        # Identical three-tick durations and totals cannot relabel the fixed
        # prefix as a dynamic wait or move it after the dynamic run.
        for change in (dict(prefix=[], suffix=[3]), dict(stall_count=1, suffix=[3]),
                       dict(drain=5), dict(prefix=[6]), dict(unclaimed=0),
                       dict(stall_count=True), dict(drain=False)):
            changed = copy.deepcopy(wanted); changed['clock_partition'].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                qualify_spans(self.fixture(), changed)

    def test_partition_fixed_clock_lists_require_integer_items(self):
        wanted = dict(extra_ticks=6, internal_clocked_ticks=9, fixed_wait_count=1,
                      clock_partition=dict(prefix=[3.0], stall_count=2, suffix=[], drain=6))
        with self.assertRaises(ValueError): qualify_spans(self.fixture(), wanted)

    def test_partition_only_domain_cannot_smuggle_full_kernel_fields(self):
        self.reject(lambda r: r.update(clock_detail='partition-only'))
        row = self.fixture(); row['clock_detail'] = 'partition-only'
        for value in row['clocks']:
            for field in ('source_before', 'source_after', 'pending_after_inside_callback', 'after_phase'):
                value.pop(field)
        result = qualify_spans(row)
        self.assertEqual(result['dynamic_indices'], [1, 2])
        self.assertEqual(result['source_edges'], [])

    def comparison_fixture(self, *, differs=False):
        state = dict(pc=0xE000, a=0, x=0, y=0, sp=255, p=0, mpr=[0]*8,
                     mpr_latch=0, physical_pc=0, clock_divisor=3, ticks=0,
                     wram_sha256=hashlib.sha256(bytes(8192)).hexdigest())
        initial = dict(state=copy.deepcopy(state), irq_count=0, irq_vector=None)
        rows = [dict(state=dict(state, pc=0xE001, physical_pc=1, ticks=6), irq_count=0, irq_vector=None),
                dict(state=dict(state, pc=0xE002, physical_pc=2, ticks=12), irq_count=0, irq_vector=None)]
        case = dict(queued_accesses=True,
                    kernel_runtime=dict(absolute_primer_ticks=1000),
                    kernel_gear=dict(absolute_primer_ticks=982),
                    expected_initial_runtime=copy.deepcopy(initial),
                    expected_initial_gear=copy.deepcopy(initial),
                    expected_runtime=copy.deepcopy(rows), expected_gear=copy.deepcopy(rows))
        difference = None
        if differs:
            case['expected_gear'][1]['state']['ticks'] = 15
            difference = dict(ordinal=2, field='state.ticks', expected=1012, actual=997,
                              expected_elapsed=12, actual_elapsed=15)
        comparison = dict(compatible=True, profile='architectural-elapsed-v1',
                          view='retirement-boundary', equal=not differs,
                          first_difference=difference, matched_records=1 if differs else 2)
        return case, comparison

    def test_elapsed_comparison_preserves_independent_raw_eighteen_tick_origins(self):
        for differs in (False, True):
            case, comparison = self.comparison_fixture(differs=differs)
            qualify_comparison(case, comparison)
        case, comparison = self.comparison_fixture(differs=True)
        self.assertEqual(comparison['first_difference']['actual'], 982+15)
        self.assertEqual(comparison['first_difference']['expected'], 1000+12)
        changed = copy.deepcopy(comparison)
        changed['first_difference']['actual'] += 18
        with self.assertRaises(ValueError): qualify_comparison(case, changed)

    def test_comparison_requires_exact_first_difference_and_matching_prefix_count(self):
        case, comparison = self.comparison_fixture(differs=True)
        for field, value in (('ordinal', 1), ('field', 'state.pc'), ('expected', 1013),
                             ('actual', 998), ('expected_elapsed', 13), ('actual_elapsed', 16)):
            changed = copy.deepcopy(comparison); changed['first_difference'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): qualify_comparison(case, changed)
        for change in (dict(equal=True), dict(first_difference=None), dict(matched_records=0),
                       dict(matched_records=2), dict(compatible=False), dict(profile='exact'),
                       dict(view='raw-event-exact')):
            changed = dict(comparison, **change)
            with self.subTest(change=change), self.assertRaises(ValueError): qualify_comparison(case, changed)
        with self.assertRaises(ValueError): qualify_comparison(dict(case, queued_accesses=False), comparison)

    def test_comparison_matched_records_cannot_be_a_boolean(self):
        case, comparison = self.comparison_fixture(differs=True)
        comparison['matched_records'] = True
        with self.assertRaises(ValueError): qualify_comparison(case, comparison)

    def test_first_difference_numeric_fields_cannot_be_floats(self):
        case, comparison = self.comparison_fixture(differs=True)
        for field in ('ordinal', 'expected', 'actual', 'expected_elapsed', 'actual_elapsed'):
            changed = copy.deepcopy(comparison)
            changed['first_difference'][field] = float(changed['first_difference'][field])
            with self.subTest(field=field), self.assertRaises(ValueError):
                qualify_comparison(case, changed)

    def test_equal_result_cannot_hide_a_different_irq_decision(self):
        case, comparison = self.comparison_fixture()
        case['expected_gear'][0]['irq_count'] = 1
        case['expected_gear'][0]['irq_vector'] = 0xFFF8
        with self.assertRaises(ValueError): qualify_comparison(case, comparison)

    def block_fixture(self, divisor=12):
        cursor = 18
        clocks = []
        for requested in (14*divisor, 6*divisor, 6*divisor, 3*divisor):
            clocks.append(dict(before=cursor, requested=requested, after=cursor+requested,
                               context='wrapper', extra_before=0, clocked_before=0,
                               pending_before=0, p_before=4, mask_before=3))
            cursor += requested
        values = [0]*39; values[21] = 3
        return dict(clock_detail='partition-only', original_calls=4,
                    entry=dict(ticks=18, clock_divisor=divisor, p=0x24),
                    state=dict(ticks=cursor), entry_values=values,
                    internal_clocked_ticks=0, extra_ticks=0,
                    returned_ticks=29*divisor, clocks=clocks)

    def test_two_word_tii_preserves_all_original_calls_at_both_speeds(self):
        for divisor in (12, 3):
            row = self.block_fixture(divisor); before = copy.deepcopy(row)
            qualify_block_spans(row, 2)
            self.assertEqual(row, before)
            self.assertEqual(row['returned_ticks'], (17+6*2)*divisor)
            self.assertEqual(len(row['clocks']), 2+2)

    def test_tii_wrapper_counters_cannot_be_forged(self):
        for field in ('extra_before', 'clocked_before', 'pending_before'):
            row = self.block_fixture(); row['clocks'][1][field] = 123
            with self.subTest(field=field), self.assertRaises(ValueError): qualify_block_spans(row, 2)
        for field in ('extra_ticks', 'internal_clocked_ticks'):
            row = self.block_fixture(); row[field] = 1
            with self.subTest(field=field), self.assertRaises(ValueError): qualify_block_spans(row, 2)

    def test_coherent_tii_callback_collapse_and_reordering_are_rejected(self):
        for durations in ((168, 144, 36), (168, 144, 18, 18), (36, 72, 72, 168)):
            row = self.block_fixture(); cursor = row['entry']['ticks']; clocks = []
            for requested in durations:
                value = dict(row['clocks'][0], before=cursor, requested=requested, after=cursor+requested)
                clocks.append(value); cursor += requested
            row['clocks'] = clocks
            self.assertEqual(cursor, row['state']['ticks'])
            with self.subTest(durations=durations), self.assertRaises(ValueError): qualify_block_spans(row, 2)

    def test_tii_phase_fields_types_and_exact_duration_are_required(self):
        for mutation in (lambda r: r.update(clock_detail='full-kernel'),
                         lambda r: r.update(original_calls=3),
                         lambda r: r.update(returned_ticks=r['returned_ticks']+1),
                         lambda r: r['state'].update(ticks=r['state']['ticks']+1),
                         lambda r: r['clocks'][0].update(context='inline'),
                         lambda r: r['clocks'][0].update(requested=168.0),
                         lambda r: r['clocks'][0].update(before=True),
                         lambda r: r['clocks'][0].update(unclaimed=0),
                         lambda r: r['clocks'][0].update(p_before=0x24),
                         lambda r: r['clocks'][0].update(mask_before=0)):
            row = self.block_fixture(); mutation(row)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): qualify_block_spans(row, 2)
        for length in (0, -1, 65537, True):
            with self.subTest(length=length), self.assertRaises(ValueError): qualify_block_spans(self.block_fixture(), length)


if __name__ == '__main__': unittest.main()

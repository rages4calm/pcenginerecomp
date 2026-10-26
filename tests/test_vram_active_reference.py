"""Authored active-display evidence-admission tests, without emulator inputs.

Literal examples come from the pinned source's documented arbitration rules.
They are synthetic observations, not guest-reached phase or hardware claims.
"""
import copy
import unittest

from scripts.vram_active_reference import (
    KERNEL_FIELDS, MODEL_FIELDS, kernel_shape, qualify_dynamic_queue,
    qualify_candidates, qualify_display_phase, qualify_mmio_stages,
    qualify_model_kernel, qualify_spans, slot_decision,
)


def kernel(**changes):
    result = {name: 0 for name in KERNEL_FIELDS}
    result.update(divider=4, hpos=132, vpos=20, vstate=1, hstate=1,
                  bg_start=128, bg_end=1216, latched_cr=128)
    result.update(changes)
    return result


def queue_span(before=None, after=None, **changes):
    before = kernel(read_pending=1, vram_delay=3, marr=65535) if before is None else before
    after = dict(before, read_pending=0, vram_delay=0, marr=0, hpos=135) if after is None else after
    result = dict(before=1000, after=1003, context='inline', requested=3,
                  source_before=before, source_after=after)
    result.update(changes)
    return result


class ActiveDisplaySlots(unittest.TestCase):
    def decision(self, **values):
        return slot_decision(kernel(**values))

    def test_BG_relative_even_slot_can_be_absolute_odd_dot(self):
        # At132, absolute dot33 is odd, but the BG-relative dot is0.
        result = self.decision(hpos=132)
        self.assertEqual((result['relative_dot'], result['eligible']), (0, True))
        self.assertEqual(result['reason'], 'background')
        self.assertFalse(self.decision(hpos=136)['eligible'])

    def test_each_BG_mode_has_its_literal_eight_dot_schedule(self):
        expected = {
            0: (True, False, True, False, True, False, True, False),
            1: (False, False, True, True, False, False, False, False),
            2: (False, False, True, True, False, False, False, False),
            3: (False,)*8,
        }
        for divider in (2, 3, 4):
            start = 32*divider
            for mode, grants in expected.items():
                for dot, grant in enumerate(grants):
                    with self.subTest(divider=divider, mode=mode, dot=dot):
                        result = self.decision(divider=divider, bg_start=start,
                            bg_end=start+272*divider, hpos=start+(dot+1)*divider,
                            latched_mwr=mode)
                        self.assertEqual(result['eligible'], grant)
                        self.assertEqual(result['relative_dot'], dot)

    def test_BG_first_fetch_dot_is_not_an_available_slot(self):
        for mode in range(4):
            with self.subTest(mode=mode):
                result = self.decision(hpos=128, latched_mwr=mode)
                self.assertEqual(result['relative_dot'], -1)
                self.assertFalse(result['eligible'])

    def test_sprite_only_display_retains_BG_fetch_arbitration(self):
        # Stable CR40 enables sprites and keeps burst disabled, even with BG off.
        for control in (64, 128, 192):
            with self.subTest(control=control):
                result = self.decision(latched_cr=control, latched_mwr=3)
                self.assertTrue(result['fetching'])
                self.assertFalse(result['eligible'])
                self.assertEqual(result['reason'], 'background')

    def test_BG_fetch_window_is_half_open(self):
        for clock, fetching in ((127, False), (128, True), (1215, True), (1216, False)):
            with self.subTest(clock=clock):
                self.assertEqual(self.decision(hpos=clock)['fetching'], fetching)

    def test_BG_fetch_has_physical_line_boundaries(self):
        for line, expected in ((13, False), (14, True), (255, True), (256, False)):
            with self.subTest(line=line):
                result = self.decision(vpos=line)
                self.assertEqual(result['fetching'], expected)
                self.assertEqual(result['eligible'], expected)

    def test_outside_vertical_display_uses_absolute_parity(self):
        for state in (0, 2, 3):
            with self.subTest(state=state):
                self.assertFalse(self.decision(vstate=state, hpos=132)['eligible'])
                self.assertTrue(self.decision(vstate=state, hpos=136)['eligible'])

    def test_burst_ignores_BG_slots_and_uses_absolute_parity(self):
        self.assertFalse(self.decision(burst=1, hpos=132)['eligible'])
        self.assertTrue(self.decision(burst=1, hpos=136, latched_mwr=3)['eligible'])
        self.assertFalse(self.decision(burst=1)['fetching'])

    def test_sprite_modes_have_four_four_eight_sixteen_dot_cost(self):
        for mode, cost in enumerate((4, 4, 8, 16)):
            for count in (1, 2, 16):
                # Choose an early fetch end so even the largest budget fits.
                end = 128
                boundary = end+count*cost*4
                with self.subTest(mode=mode, count=count):
                    before = self.decision(hpos=boundary-8, bg_start=0, bg_end=end,
                        latched_cr=64, latched_mwr=mode<<2, sprite_count=count)
                    after = self.decision(hpos=boundary, bg_start=0, bg_end=end,
                        latched_cr=64, latched_mwr=mode<<2, sprite_count=count)
                    self.assertFalse(before['eligible'])
                    self.assertTrue(after['eligible'])
                    self.assertEqual(after['sprite_cost'], cost)
                    self.assertEqual(after['sprite_elapsed_dots'], count*cost)

    def test_wide_sprite_uses_two_cells_not_one_entry(self):
        common = dict(hpos=1232, latched_cr=64)
        self.assertTrue(self.decision(**common, sprite_count=1)['eligible'])
        self.assertFalse(self.decision(**common, sprite_count=2)['eligible'])
        self.assertTrue(self.decision(hpos=1248, latched_cr=64, sprite_count=2)['eligible'])

    def test_disabled_or_zero_count_sprites_use_idle_parity(self):
        for control, count in ((128, 16), (64, 0)):
            with self.subTest(control=control, count=count):
                result = self.decision(hpos=1224, latched_cr=control, sprite_count=count)
                self.assertTrue(result['eligible'])
                self.assertEqual(result['reason'], 'idle-parity')

    def test_sprite_budget_requires_even_absolute_dot_after_it_expires(self):
        self.assertTrue(self.decision(hpos=1232, latched_cr=64, sprite_count=1)['eligible'])
        self.assertFalse(self.decision(hpos=1236, latched_cr=64, sprite_count=1)['eligible'])

    def test_strict_fetch_end_equality_has_pinned_profile_discontinuity(self):
        common = dict(latched_cr=64, latched_mwr=12, sprite_count=16)
        exact = self.decision(hpos=1216, **common)
        following = self.decision(hpos=1217, **common)
        self.assertEqual(exact['sprite_elapsed_dots'], 341)
        self.assertTrue(exact['eligible'])
        self.assertEqual(following['sprite_elapsed_dots'], 0)
        self.assertFalse(following['eligible'])

    def test_sprite_budget_wraps_before_BG_window(self):
        result = self.decision(hpos=64, latched_cr=64, latched_mwr=12, sprite_count=16)
        self.assertEqual(result['sprite_elapsed_dots'], 53)
        self.assertFalse(result['eligible'])

    def test_HSW_exclusion_looks_three_master_ticks_ahead(self):
        common = dict(divider=2, vstate=0, hstate=3)
        self.assertFalse(self.decision(hpos=12, **common)['eligible'])
        result = self.decision(hpos=13, **common)
        self.assertTrue(result['eligible'])
        self.assertEqual(result['hsync_since'], 16)

    def test_HSW_uses_actual_nonzero_sync_origin(self):
        common = dict(vstate=0, hstate=3, hsync_start=100)
        self.assertFalse(self.decision(hpos=128, **common)['eligible'])
        result = self.decision(hpos=129, **common)
        self.assertTrue(result['eligible'])
        self.assertEqual(result['hsync_since'], 32)

    def test_HSW_elapsed_wraps_at_1365(self):
        common = dict(divider=2, vstate=0, hstate=3, hsync_start=1350)
        self.assertFalse(self.decision(hpos=1360, **common)['eligible'])
        result = self.decision(hpos=0, **common)
        self.assertTrue(result['eligible'])
        self.assertEqual(result['hsync_since'], 18)

    def test_DMA_and_SAT_override_all_other_slot_availability(self):
        for field in ('dma_pending', 'sat_pending'):
            with self.subTest(field=field):
                result = self.decision(**{field: 1})
                self.assertFalse(result['eligible'])
                self.assertEqual(result['reason'], 'dma')

    def test_cached_allow_is_only_a_retained_last_decision(self):
        for clock in (132, 136, 1216, 1217):
            with self.subTest(clock=clock):
                self.assertEqual(self.decision(hpos=clock, cached_allow=0),
                                 self.decision(hpos=clock, cached_allow=1))


class ActiveQueueAdmission(unittest.TestCase):
    def test_delay_reaches_zero_then_read_completes_in_same_span(self):
        result = qualify_dynamic_queue(queue_span())
        self.assertTrue(result['ready'])
        self.assertEqual(result['grant'], 'read')

    def test_positive_delay_prevents_an_otherwise_available_grant(self):
        before = kernel(read_pending=1, vram_delay=6, marr=7)
        after = dict(before, vram_delay=3, hpos=135)
        result = qualify_dynamic_queue(queue_span(before, after))
        self.assertFalse(result['ready'])
        self.assertIsNone(result['grant'])
        bad = dict(after, read_pending=0, marr=8)
        with self.assertRaises(ValueError): qualify_dynamic_queue(queue_span(before, bad))

    def test_ready_queue_remains_pending_in_blocked_BG_slot(self):
        before = kernel(hpos=136, read_pending=1, vram_delay=3, marr=7)
        after = dict(before, vram_delay=0, hpos=139)
        result = qualify_dynamic_queue(queue_span(before, after))
        self.assertTrue(result['ready'])
        self.assertIsNone(result['grant'])
        with self.assertRaises(ValueError):
            qualify_dynamic_queue(queue_span(before, dict(after, read_pending=0, marr=8)))

    def test_read_has_priority_over_simultaneously_pending_write(self):
        before = kernel(read_pending=1, write_pending=1, vram_delay=0, marr=7, mawr=11)
        after = dict(before, read_pending=0, marr=8, hpos=135)
        self.assertEqual(qualify_dynamic_queue(queue_span(before, after))['grant'], 'read')
        for bad in (dict(after, write_pending=0, mawr=12),
                    dict(after, read_pending=1, write_pending=0, marr=7, mawr=12)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                qualify_dynamic_queue(queue_span(before, bad))

    def test_dual_queue_retains_the_write_after_isolated_end_boundary_read(self):
        for count in (1, 4, 16):
            common = dict(latched_cr=64, latched_mwr=15, sprite_count=count,
                          read_pending=1, write_pending=1, vram_delay=0, marr=7, mawr=11)
            waiting = kernel(hpos=1213, **common)
            at_end = dict(waiting, hpos=1216)
            read_done = dict(at_end, hpos=1219, read_pending=0, marr=8)
            still_waiting = dict(read_done, hpos=1222)
            with self.subTest(count=count):
                self.assertIsNone(qualify_dynamic_queue(queue_span(waiting, at_end))['grant'])
                self.assertEqual(qualify_dynamic_queue(queue_span(at_end, read_done))['grant'], 'read')
                self.assertIsNone(qualify_dynamic_queue(queue_span(read_done, still_waiting))['grant'])
                with self.assertRaises(ValueError):
                    qualify_dynamic_queue(queue_span(read_done, dict(still_waiting, write_pending=0, mawr=12)))

    def test_each_declared_CR_increment_wraps_the_read_pointer(self):
        for increment, expected in ((1, 0), (32, 31), (64, 63), (128, 127)):
            before = kernel(read_pending=1, vram_delay=0, marr=65535, mawr=321)
            after = dict(before, read_pending=0, marr=expected, hpos=135)
            with self.subTest(increment=increment):
                self.assertEqual(qualify_dynamic_queue(queue_span(before, after), increment)['grant'], 'read')

    def test_write_only_queue_advances_only_MAWR(self):
        for increment, expected in ((1, 0), (32, 31), (64, 63), (128, 127)):
            before = kernel(write_pending=1, vram_delay=0, mawr=65535, marr=321)
            after = dict(before, write_pending=0, mawr=expected, hpos=135)
            with self.subTest(increment=increment):
                self.assertEqual(qualify_dynamic_queue(queue_span(before, after), increment)['grant'], 'write')
                with self.assertRaises(ValueError):
                    qualify_dynamic_queue(queue_span(before, dict(after, marr=322)), increment)

    def test_queue_cannot_disappear_without_pointer_advance(self):
        span = queue_span()
        span['source_after']['marr'] = 65535
        with self.assertRaises(ValueError): qualify_dynamic_queue(span)

    def test_no_pending_request_is_not_a_dynamic_queue_decision(self):
        span = queue_span(kernel(read_pending=0), kernel(read_pending=0))
        with self.assertRaises(ValueError): qualify_dynamic_queue(span)

    def test_this_declared_span_domain_requires_zero_carry(self):
        for side in ('source_before','source_after'):
            span = queue_span(); span[side]['vram_carry'] = 1
            with self.subTest(side=side), self.assertRaises(ValueError): qualify_dynamic_queue(span)

    def test_typed_three_tick_inline_clock_and_exact_timestamp_extent(self):
        for changes in (dict(context='wrapper'), dict(requested=2), dict(requested=3.0),
                        dict(before=True), dict(after=1003.0), dict(before=-1, after=2),
                        dict(after=1004), dict(before=2**64-2, after=2**64+1)):
            span = queue_span(); span.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                qualify_dynamic_queue(span)

    def test_only_exact_integer_CR_increment_choices_are_supported(self):
        for increment in (True, False, 1.0, -1, 0, 2, 65537):
            with self.subTest(increment=increment), self.assertRaises(ValueError):
                qualify_dynamic_queue(queue_span(), increment)

    def test_complete_typed_raw_kernel_is_required(self):
        value = kernel(); kernel_shape(value)
        for change in (lambda k: k.pop('cached_allow'), lambda k: k.update(unclaimed=0),
                       lambda k: k.update(cached_allow=True), lambda k: k.update(cached_allow=2),
                       lambda k: k.update(sprite_count=-1), lambda k: k.update(sprite_count=17),
                       lambda k: k.update(sat_pending=1025), lambda k: k.update(sat_pending=False),
                       lambda k: k.update(read_pending=True), lambda k: k.update(marr=65536),
                       lambda k: k.update(latched_mwr=256), lambda k: k.update(latched_cr=65536)):
            bad = copy.deepcopy(value); change(bad)
            with self.subTest(change=change), self.assertRaises(ValueError): kernel_shape(bad)

    def test_cached_allow_cannot_make_an_unavailable_queue_grant_valid(self):
        before = kernel(hpos=136, read_pending=1, vram_delay=0, cached_allow=1)
        after = dict(before, read_pending=0, marr=1, hpos=139)
        with self.assertRaises(ValueError): qualify_dynamic_queue(queue_span(before, after))


def modeled(raw, ticks):
    # Deliberate independent field list: do not derive expected names or aliases
    # from MODEL_MAP, whose association is one of the contracts being tested.
    names = ('divider dma_pending read_pending write_pending vram_delay vram_carry '
             'marr read_buffer vdc_status cd_enabled cd_active scsi_signals scsi_phase '
             'scsi_data response_index mawr vwr vpos hstate vstate bg_start bg_end '
             'hsync_start burst latched_cr latched_mwr sprite_count sat_pending').split()
    return dict({name: raw[name] for name in names}, ticks=ticks,
                hclock=raw['hpos'], irq_requests=raw['irr'])


def observed_clock(start, end, before, after, *, dynamic=False, wrapper=False):
    return dict(before=start, after=end, requested=end-start,
        context='wrapper' if wrapper else 'inline',
        extra_before=before['cpu_extra'], clocked_before=before['cpu_clocked'],
        pending_before=before['cpu_pending'], p_before=before['cpu_p'],
        mask_before=before['cpu_mask'], source_before=before, source_after=after,
        pending_after_inside_callback=after['cpu_pending'],
        after_phase='no-cpu-resample' if wrapper else 'before-cpu-resample')


def high_port_INC_fixture():
    """Hand-counted2MHz-VCE example, CPU fixed waits3ticks, no IRQ sources.

    First prefetch: fixed delay6->3, then h3/h6 deny and h9 grants.
    High read at12 returns56 and queues15tick prefetch: five waits grant
    at24, replacing5678 with9ABC. The later high write must still use57.
    """
    raw = kernel(divider=2, burst=1, hpos=0, vstate=0, hstate=0,
                 read_pending=1, vram_delay=6, read_buffer=0x1234,
                 vdc_status=64, vwr=0x00EF, cpu_p=4)
    initial = copy.deepcopy(raw)
    clocks = []
    fixed_before = copy.deepcopy(raw)
    raw.update(hpos=3, vram_delay=3)
    clocks.append(observed_clock(0, 3, fixed_before, copy.deepcopy(raw)))
    for index in range(3):
        t = 3+3*index
        raw.update(cpu_extra=3*(index+1), cpu_clocked=t)
        before = copy.deepcopy(raw)
        raw.update(hpos=t+3, vram_delay=0)
        if index == 2:
            raw.update(read_pending=0, marr=1, read_buffer=0x5678, vdc_status=0)
        clocks.append(observed_clock(t, t+3, before, copy.deepcopy(raw)))
    read_before = copy.deepcopy(raw)
    raw.update(read_pending=1, vram_delay=15, vdc_status=64)
    read_after = copy.deepcopy(raw)
    for index, remaining in enumerate((12, 9, 6, 3, 0)):
        t = 12+3*index
        raw.update(cpu_extra=12+3*index, cpu_clocked=t)
        before = copy.deepcopy(raw)
        raw.update(hpos=t+3, vram_delay=remaining)
        if index == 4:
            raw.update(read_pending=0, marr=2, read_buffer=0x9ABC, vdc_status=0)
        clocks.append(observed_clock(t, t+3, before, copy.deepcopy(raw)))
    write_before = copy.deepcopy(raw)
    raw.update(vwr=0x57EF, write_pending=1, vram_delay=12, vdc_status=64)
    write_after = copy.deepcopy(raw)
    raw.update(cpu_clocked=27)
    before = copy.deepcopy(raw)
    raw.update(hpos=30, vram_delay=9)
    clocks.append(observed_clock(27, 30, before, copy.deepcopy(raw)))
    raw.update(cpu_clocked=30)
    before = copy.deepcopy(raw)
    raw.update(hpos=51, write_pending=0, vram_delay=0, mawr=1, vdc_status=0)
    clocks.append(observed_clock(30, 51, before, copy.deepcopy(raw), wrapper=True))
    row = dict(clock_detail='full-kernel', clocks=clocks,
        entry=dict(ticks=0, clock_divisor=3, a=0), state=dict(ticks=51),
        extra_ticks=24, internal_clocked_ticks=30, kernel_entry=initial,
        kernel_at_return=copy.deepcopy(clocks[-1]['source_before']),
        kernel_final=copy.deepcopy(clocks[-1]['source_after']))
    wanted = dict(extra_ticks=24, internal_clocked_ticks=30, fixed_wait_count=2,
        clock_partition=dict(prefix=[3], wait_runs=[3, 5], suffix=[3], drain=21),
        mmio_stages=[dict(kind='read-high', span_index=4, value=0x56,
                         before=modeled(read_before,12), after=modeled(read_after,12)),
                     dict(kind='write-high', span_index=9, value=0x57,
                         before=modeled(write_before,27), after=modeled(write_after,27))])
    return row, wanted, [0xEE, 3, 0]


def ordinary_port_fixture(write, high):
    """No initial queue: literal mapped fixed cycle plus15tick wrapper drain."""
    raw = kernel(divider=2, burst=1, hpos=0, vstate=0, hstate=0,
                 read_buffer=0x1234, vwr=0xBEEF, cpu_p=4)
    initial = copy.deepcopy(raw)
    value = 0x42 if write else 0x12 if high else 0x34
    if write:
        raw['vwr'] = 0x42EF if high else 0xBE42
        if high:raw.update(write_pending=1, vram_delay=12, vdc_status=64)
        port_before,port_after = initial,copy.deepcopy(raw)
        stage_time = 0
    before = copy.deepcopy(raw)
    raw['hpos'] = 3
    if write and high:raw['vram_delay'] = 9
    clocks = [observed_clock(0,3,before,copy.deepcopy(raw))]
    if not write:
        port_before = copy.deepcopy(raw)
        if high:raw.update(read_pending=1,vram_delay=15,vdc_status=64)
        port_after = copy.deepcopy(raw)
        stage_time = 3
    raw['cpu_clocked'] = 3
    before = copy.deepcopy(raw)
    raw['hpos'] = 18
    if write and high:raw.update(write_pending=0,vram_delay=0,mawr=1,vdc_status=0)
    if not write and high:raw['vram_delay'] = 0  # At h15 the blank dot7 is unavailable.
    clocks.append(observed_clock(3,18,before,copy.deepcopy(raw),wrapper=True))
    kind = ('write-'if write else'read-')+('high'if high else'low')
    row = dict(clock_detail='full-kernel',clocks=clocks,
        entry=dict(ticks=0,clock_divisor=3,a=0x42),state=dict(ticks=18),
        extra_ticks=0,internal_clocked_ticks=3,kernel_entry=initial,
        kernel_at_return=copy.deepcopy(clocks[-1]['source_before']),
        kernel_final=copy.deepcopy(clocks[-1]['source_after']))
    wanted = dict(extra_ticks=0,internal_clocked_ticks=3,fixed_wait_count=1,
        clock_partition=dict(prefix=[]if write else[3],wait_runs=[0],
                             suffix=[3]if write else[],drain=15),
        mmio_stages=[dict(kind=kind,span_index=0 if write else 1,value=value,
            before=modeled(port_before,stage_time),after=modeled(port_after,stage_time))])
    return row,wanted,[0x8D if write else 0xAD,3 if high else 2,0]


class ActiveClockAndPortAdmission(unittest.TestCase):
    def reject(self, change, *, clocks=True, ports=False):
        row, wanted, data = high_port_INC_fixture()
        change(row, wanted, data)
        with self.assertRaises(ValueError):
            if clocks: qualify_spans(row, wanted, data)
            if ports: qualify_mmio_stages(row, wanted, data)

    def test_independent_model_names_and_clock_request_aliases(self):
        raw = kernel(hpos=129, irr=3)
        wanted = modeled(raw,1000)
        self.assertEqual(set(wanted), MODEL_FIELDS)
        self.assertEqual((wanted['hclock'],wanted['irq_requests']),(129,3))
        qualify_model_kernel(raw,wanted,1000)
        for field in wanted:
            changed = copy.deepcopy(wanted); changed[field] += 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                qualify_model_kernel(raw,changed,1000)

    def test_model_requires_every_key_exact_types_and_bound_timestamp(self):
        raw = kernel(); wanted = modeled(raw,1000)
        for change in (lambda m: m.pop('vwr'), lambda m: m.update(unclaimed=0),
                       lambda m: m.update(ticks=True), lambda m: m.update(hclock=132.0),
                       lambda m: m.update(irq_requests=False), lambda m: m.update(ticks=999)):
            changed = copy.deepcopy(wanted); change(changed)
            with self.subTest(change=change), self.assertRaises(ValueError):
                qualify_model_kernel(raw,changed,1000)

    def test_high_INC_has_two_actual_wait_runs_and_two_port_effects(self):
        row,wanted,data = high_port_INC_fixture()
        result = qualify_spans(row,wanted,data)
        self.assertEqual(result['dynamic_indices'],list(range(1,9)))
        self.assertEqual(result['fixed_indices'],[0,9])
        self.assertEqual(result['port_barriers'],[4])
        self.assertEqual(result['wrapper'],[21])
        self.assertEqual(qualify_mmio_stages(row,wanted,data),2)

    def test_ordinary_low_high_read_and_write_have_exact_zero_clock_effects(self):
        for write in (False,True):
            for high in (False,True):
                with self.subTest(write=write,high=high):
                    row,wanted,data = ordinary_port_fixture(write,high)
                    self.assertEqual(qualify_spans(row,wanted,data)['dynamic_indices'],[])
                    self.assertEqual(qualify_mmio_stages(row,wanted,data),1)

    def test_low_read_does_not_requeue_or_change_data_latch(self):
        for change in (dict(read_pending=1,vram_delay=15,vdc_status=64),dict(vwr=0xBE34)):
            row,wanted,data = ordinary_port_fixture(False,False)
            row['clocks'][1]['source_before'].update(change)
            wanted['mmio_stages'][0]['after'] = modeled(row['clocks'][1]['source_before'],3)
            with self.subTest(change=change),self.assertRaises(ValueError):
                qualify_mmio_stages(row,wanted,data)

    def test_low_write_preserves_high_latch_without_queueing_a_write(self):
        for change in (dict(vwr=0x0042),dict(write_pending=1,vram_delay=12,vdc_status=64)):
            row,wanted,data = ordinary_port_fixture(True,False)
            row['clocks'][0]['source_before'].update(change)
            wanted['mmio_stages'][0]['after'] = modeled(row['clocks'][0]['source_before'],0)
            with self.subTest(change=change),self.assertRaises(ValueError):
                qualify_mmio_stages(row,wanted,data)

    def test_fixed_fast_wait_is_a_queue_denial_not_a_dynamic_wait(self):
        row,wanted,data = high_port_INC_fixture()
        result = qualify_spans(row,wanted,data)
        first = result['queue_decisions'][0]
        self.assertEqual((first['span'],first['clock_kind'],first['ready'],first['grant']),
                         (0,'fixed',False,None))

    def test_partition_requires_typed_counts_and_exact_keys(self):
        for change in (lambda p: p.update(wait_runs=[True,5]),
                       lambda p: p.update(wait_runs=[3,5.0]),
                       lambda p: p.update(wait_runs=[3,-1]),
                       lambda p: p.update(wait_runs=[3,200001]),
                       lambda p: p.update(wait_runs=[1,2,5]),
                       lambda p: p.update(prefix=[True]),
                       lambda p: p.update(suffix=[0]),
                       lambda p: p.update(drain=False),
                       lambda p: p.update(unclaimed=0)):
            with self.subTest(change=change):
                self.reject(lambda r,w,d:change(w['clock_partition']))

    def test_two_wait_barrier_is_not_allowed_for_another_opcode(self):
        for opcode in ([0xEE,2,0],[0xAD,3,0],[0x8D,3,0],[0xEA]):
            with self.subTest(opcode=opcode):
                self.reject(lambda r,w,d:d.__setitem__(slice(None),opcode))

    def test_dynamic_kernel_chain_cannot_break_outside_the_high_read_barrier(self):
        self.reject(lambda r,w,d:r['clocks'][2]['source_before'].update(read_buffer=7))
        self.reject(lambda r,w,d:r['clocks'][5]['source_before'].update(vwr=7))

    def test_barrier_alone_does_not_authorize_a_fabricated_port_transition(self):
        # Clock validation permits this exact zero-clock boundary, but the
        # mandatory port qualifier must bind and reject the invented latch.
        row,wanted,data = high_port_INC_fixture()
        row['clocks'][4]['source_before']['vwr'] = 0xBEEF
        with self.assertRaises(ValueError): qualify_mmio_stages(row,wanted,data)

    def test_fixed_dynamic_extra_counters_and_partitions_are_independent(self):
        for change in (lambda r:r.update(extra_ticks=21),
                       lambda r:r.update(internal_clocked_ticks=27),
                       lambda r:r['clocks'][1].update(extra_before=0),
                       lambda r:r['clocks'][1].update(requested=4,after=7)):
            with self.subTest(change=change):self.reject(lambda r,w,d:change(r))

    def test_wanted_execution_counts_cannot_use_bool_or_float_equivalence(self):
        for field,value in (('extra_ticks',False),('internal_clocked_ticks',3.0),
                            ('fixed_wait_count',True)):
            row,wanted,data = ordinary_port_fixture(False,False)
            wanted[field] = value
            with self.subTest(field=field),self.assertRaises(ValueError):
                qualify_spans(row,wanted,data)

    def test_raw_callback_raster_phase_cannot_detach_from_absolute_clock(self):
        for side,clock in (('source_before',1),('source_after',4)):
            row,wanted,data = high_port_INC_fixture()
            row['clocks'][0][side]['hpos'] = clock
            with self.subTest(side=side),self.assertRaises(ValueError):
                qualify_spans(row,wanted,data)

    def test_no_memory_opcode_has_zero_wait_groups_and_only_its_wrapper_clock(self):
        for data,drain in (([0xEA],6),([0x80,0xFE],12)):
            before = kernel(divider=2,burst=1,hpos=0,cpu_p=4)
            after = dict(before,hpos=drain)
            row = dict(clock_detail='full-kernel',
                clocks=[observed_clock(0,drain,before,after,wrapper=True)],
                entry=dict(ticks=0,clock_divisor=3,a=0),state=dict(ticks=drain),
                extra_ticks=0,internal_clocked_ticks=0,kernel_entry=before,
                kernel_at_return=before,kernel_final=after)
            wanted = dict(extra_ticks=0,internal_clocked_ticks=0,fixed_wait_count=0,
                clock_partition=dict(prefix=[],wait_runs=[],suffix=[],drain=drain),mmio_stages=[])
            with self.subTest(data=data):
                self.assertEqual(qualify_spans(row,wanted,data)['dynamic_indices'],[])
                self.assertEqual(qualify_mmio_stages(row,wanted,data),0)
                with self.assertRaises(ValueError):qualify_spans(row,wanted,[0xAD,3,0])

    def test_wrapper_and_return_snapshots_must_bind_the_actual_clocks(self):
        for change in (lambda r:r['kernel_at_return'].update(cpu_clocked=0),
                       lambda r:r['kernel_final'].update(marr=9),
                       lambda r:r['clocks'][-1].update(context='inline'),
                       lambda r:r['clocks'][-1].update(after=52),
                       lambda r:r['state'].update(ticks=52)):
            with self.subTest(change=change):self.reject(lambda r,w,d:change(r))

    def test_missing_or_changed_full_kernels_are_rejected(self):
        for change in (lambda r:r['clocks'][1]['source_before'].pop('cached_allow'),
                       lambda r:r['clocks'][1]['source_after'].update(unclaimed=0),
                       lambda r:r['clocks'][1]['source_before'].update(vwr=True)):
            with self.subTest(change=change):self.reject(lambda r,w,d:change(r))

    def test_stage_names_count_indices_and_types_are_exact(self):
        for change in (lambda s:s.pop(), lambda s:s[0].update(kind='read-low'),
                       lambda s:s[0].update(span_index=3),
                       lambda s:s[0].update(span_index=True),
                       lambda s:s[1].update(span_index=10),
                       lambda s:s[0].update(value=True),
                       lambda s:s[0].update(unclaimed=0)):
            with self.subTest(change=change):
                self.reject(lambda r,w,d:change(w['mmio_stages']),clocks=False,ports=True)

    def test_stage_clock_is_the_same_actual_boundary_not_an_invented_tick(self):
        self.reject(lambda r,w,d:w['mmio_stages'][0]['before'].update(ticks=13),clocks=False,ports=True)
        self.reject(lambda r,w,d:r['clocks'][4].update(before=13),clocks=False,ports=True)

    def test_read_high_cannot_use_the_buffer_after_its_second_prefetch(self):
        row,wanted,data = high_port_INC_fixture()
        self.assertEqual(row['clocks'][8]['source_after']['read_buffer'],0x9ABC)
        self.assertEqual(qualify_mmio_stages(row,wanted,data),2)
        wanted['mmio_stages'][0]['value'] = 0x9A
        with self.assertRaises(ValueError):qualify_mmio_stages(row,wanted,data)

    def test_high_INC_write_uses_incremented_old_byte_not_later_buffer(self):
        self.reject(lambda r,w,d:w['mmio_stages'][1].update(value=0x9B),clocks=False,ports=True)

    def test_MMIO_high_read_must_requeue_with_the_literal_latency(self):
        for change in (dict(read_pending=0),dict(vram_delay=12),dict(vdc_status=0)):
            row,wanted,data = high_port_INC_fixture()
            row['clocks'][4]['source_before'].update(change)
            wanted['mmio_stages'][0]['after'] = modeled(row['clocks'][4]['source_before'],12)
            with self.subTest(change=change),self.assertRaises(ValueError):
                qualify_mmio_stages(row,wanted,data)

    def test_MMIO_high_write_preserves_low_latch_and_queues_write(self):
        for change in (dict(vwr=0x5700),dict(write_pending=0),dict(vram_delay=15)):
            row,wanted,data = high_port_INC_fixture()
            row['clocks'][9]['source_before'].update(change)
            wanted['mmio_stages'][1]['after'] = modeled(row['clocks'][9]['source_before'],27)
            with self.subTest(change=change),self.assertRaises(ValueError):
                qualify_mmio_stages(row,wanted,data)

    def test_MMIO_write_cannot_bypass_the_second_pending_read(self):
        row,wanted,data = high_port_INC_fixture()
        row['clocks'][8]['source_after']['read_pending'] = 1
        wanted['mmio_stages'][1]['before'] = modeled(row['clocks'][8]['source_after'],27)
        with self.assertRaises(ValueError):qualify_mmio_stages(row,wanted,data)


def candidate_record(tick, *, allowed, context='dynamic', kind='read',
                     read=1, write=0, reason='background'):
    return dict(ticks=tick, visible_ticks=tick+3, context=context, kind=kind,
                hclock=tick%1365, delay_before=0, read_pending=read,
                write_pending=write, allowed=allowed,
                reason='grant' if allowed else reason)


def observed_candidate(record, *, marr=7, mawr=11, buffer=0xA65C, vwr=0x0F3E):
    return dict(before=record['ticks'], after=record['visible_ticks'], ready=True,
        grant=record['kind'] if record['allowed'] else None,
        clock_kind=record['context'], attempt_kind=record['kind'],
        hclock=record['hclock'], delay_before=record['delay_before'],
        read_pending=record['read_pending'], write_pending=record['write_pending'],
        eligible=record['allowed'], reason='background' if not record['allowed'] else 'background',
        marr=marr, mawr=mawr, read_buffer=buffer, vwr=vwr)


def candidate_fixture(*, boundary=False):
    base = 64*1365
    if boundary:
        # HSR0202/HDR7F1D,VCE4 =>240dot HDW and fetch end1152.
        records = [candidate_record(base+1149,allowed=False,read=1,write=1),
                   candidate_record(base+1152,allowed=True,read=1,write=1),
                   candidate_record(base+1155,allowed=False,kind='write',read=0,
                                    write=1,reason='sprite')]
    else:
        records = [candidate_record(base+129,allowed=False),
                   candidate_record(base+132,allowed=True)]
    decisions = [observed_candidate(record) for record in records]
    if boundary:decisions[-1]['reason'] = 'sprite'
    grants = [dict(record,marr=7,mawr=11,read_buffer=0xA65C,vwr=0x0F3E)
              for record in records if record['allowed']]
    case = dict(family='boundary' if boundary else 'bg',speed=3,divider=4,
        cr=64 if boundary else 128,mwr=15 if boundary else 0,cells=4 if boundary else 0,
        expected_gear=[dict(extra_ticks=3*len(records))],
        kernel_gear=dict(candidates=records,grants=grants,
            absolute_primer_ticks=base+828 if boundary else base+120,
            positive_wait=True,arbitration_denials=2 if boundary else 1,
            coverage='arbitration-denied',boundary_candidates=copy.deepcopy(records) if boundary else[]))
    return case,decisions


class SteadyDisplayPhaseAdmission(unittest.TestCase):
    def test_absolute_clock_derives_each_horizontal_state_at_all_VCE_rates(self):
        # Literal HSW/HDS/HDW ends from the programmed240dot display width.
        for divider,start,display,end in ((2,48,96,576),(3,96,168,888),(4,96,192,1152)):
            case = dict(divider=divider,cr=64,mwr=8,cells=4)
            for h,state in ((0,3),(start-1,3),(start,0),(display-1,0),
                            (display,1),(end-1,1),(end,2),(1364,2)):
                raw = kernel(divider=divider,hpos=h,vpos=64,hstate=state,vstate=1,
                    bg_start=display-16*divider,bg_end=end,hsync_start=0,
                    burst=0,latched_cr=64,latched_mwr=8,sprite_count=4)
                with self.subTest(divider=divider,h=h):
                    qualify_display_phase(raw,case,64*1365+h)

    def test_interior_phase_and_latches_cannot_jump_between_retirements(self):
        case = dict(divider=4,cr=64,mwr=8,cells=4)
        raw = kernel(hpos=306,vpos=64,hstate=1,bg_start=128,bg_end=1152,
                     latched_cr=64,latched_mwr=8,sprite_count=4)
        qualify_display_phase(raw,case,64*1365+306)
        for change in (dict(hpos=307),dict(vpos=65),dict(divider=3),dict(hstate=2),
                       dict(vstate=0),dict(bg_start=132),dict(bg_end=1216),
                       dict(hsync_start=4),dict(burst=1),dict(latched_cr=128),
                       dict(latched_mwr=4),dict(sprite_count=1),dict(sat_pending=1),
                       dict(dma_pending=1)):
            with self.subTest(change=change),self.assertRaises(ValueError):
                qualify_display_phase(dict(raw,**change),case,64*1365+306)

    def test_steady_domain_boundaries_are_explicit(self):
        case = dict(divider=4,cr=128,mwr=0,cells=0)
        for line,accepted in ((31,False),(32,True),(79,True),(80,False)):
            raw = kernel(hpos=306,vpos=line,hstate=1,bg_end=1152)
            with self.subTest(line=line):
                if accepted:qualify_display_phase(raw,case,line*1365+306)
                else:
                    with self.assertRaises(ValueError):qualify_display_phase(raw,case,line*1365+306)

    def test_raw_phase_and_absolute_clock_types_are_strict(self):
        case = dict(divider=4,cr=128,mwr=0,cells=0)
        raw = kernel(hpos=306,vpos=64,hstate=1,bg_end=1152)
        for ticks in (True,-1,64*1365+306.0):
            with self.subTest(ticks=ticks),self.assertRaises(ValueError):
                qualify_display_phase(raw,case,ticks)
        for change in (dict(hstate=True),dict(sprite_count=False),dict(latched_mwr=0.0)):
            with self.subTest(change=change),self.assertRaises(ValueError):
                qualify_display_phase(dict(raw,**change),case,64*1365+306)


class ReadyCandidateLedgerAdmission(unittest.TestCase):
    def reject(self,change):
        case,decisions = candidate_fixture()
        change(case,decisions)
        with self.assertRaises(ValueError):qualify_candidates(case,decisions)

    def test_every_actual_ready_attempt_and_granted_data_matches(self):
        case,decisions = candidate_fixture()
        result = qualify_candidates(case,decisions)
        self.assertEqual(result['observable_ready_candidates'],2)
        self.assertEqual(result['independent_ready_candidates'],2)
        self.assertEqual(result['expected_coverage'],'arbitration-denied')

    def test_missing_duplicate_or_extra_actual_ready_attempt_is_refused(self):
        for change in (lambda d:d.pop(),lambda d:d.append(copy.deepcopy(d[0])),
                       lambda d:d[0].update(before=d[0]['before']-3),
                       lambda d:d[0].update(ready=False)):
            with self.subTest(change=change):self.reject(lambda c,d:change(d))

    def test_actual_candidate_clock_kind_queue_phase_and_decision_are_bound(self):
        for change in (dict(after=0),dict(clock_kind='fixed'),dict(hclock=130),
                       dict(delay_before=3),dict(read_pending=0,write_pending=1),
                       dict(attempt_kind='write'),dict(eligible=True),dict(reason='sprite')):
            with self.subTest(change=change):
                self.reject(lambda c,d:d[0].update(change))

    def test_every_granted_register_and_data_word_is_checked(self):
        for field in ('marr','mawr','read_buffer','vwr'):
            with self.subTest(field=field):
                self.reject(lambda c,d:d[1].__setitem__(field,d[1][field]^1))
        self.reject(lambda c,d:c['kernel_gear']['grants'].clear())
        self.reject(lambda c,d:c['kernel_gear']['grants'].append(copy.deepcopy(c['kernel_gear']['grants'][0])))

    def test_actual_grant_kind_cannot_disagree_with_the_pending_attempt(self):
        self.reject(lambda c,d:d[1].update(grant='write'))

    def test_declared_grant_cannot_exist_without_a_matching_candidate(self):
        def orphan(case,decisions):
            record = candidate_record(64*1365+144,allowed=True)
            case['kernel_gear']['grants'].append(dict(record,marr=99,mawr=88,read_buffer=0,vwr=1))
        self.reject(orphan)

    def test_unobserved_slow_fixed_candidate_still_requires_a_known_reason(self):
        case,decisions = candidate_fixture()
        case['speed'] = 12
        case['kernel_gear']['candidates'][0].update(context='fixed',reason='invented')
        with self.assertRaises(ValueError):qualify_candidates(case,decisions[1:])

    def test_independent_candidate_keys_types_and_phase_are_strict(self):
        for change in (lambda e:e.pop('kind'),lambda e:e.update(unclaimed=0),
                       lambda e:e.update(ticks=True),lambda e:e.update(visible_ticks=0),
                       lambda e:e.update(hclock=130),lambda e:e.update(delay_before=4),
                       lambda e:e.update(read_pending=True),lambda e:e.update(allowed=1),
                       lambda e:e.update(context='unobserved'),lambda e:e.update(reason=False)):
            with self.subTest(change=change):
                self.reject(lambda c,d:change(c['kernel_gear']['candidates'][0]))

    def test_independent_candidate_times_must_be_unique(self):
        self.reject(lambda c,d:c['kernel_gear']['candidates'].append(copy.deepcopy(c['kernel_gear']['candidates'][0])))

    def test_fast_fixed_three_tick_attempt_is_observable_but_slow_fixed_is_not(self):
        case,decisions = candidate_fixture()
        case['kernel_gear']['candidates'][0]['context'] = 'fixed'
        decisions[0]['clock_kind'] = 'fixed'
        self.assertEqual(qualify_candidates(case,decisions)['observable_ready_candidates'],2)
        case['speed'] = 12
        self.assertEqual(qualify_candidates(case,decisions[1:])['observable_ready_candidates'],1)
        with self.assertRaises(ValueError):qualify_candidates(case,decisions)

    def test_zero_and_latency_only_coverage_are_not_arbitration_claims(self):
        for extra,coverage in ((0,'zero-wait'),(3,'latency-only')):
            case,decisions = candidate_fixture()
            case['expected_gear'] = [dict(extra_ticks=extra)]
            case['kernel_gear'].update(candidates=[],grants=[],positive_wait=bool(extra),
                arbitration_denials=0,coverage=coverage)
            with self.subTest(coverage=coverage):
                self.assertEqual(qualify_candidates(case,[])['expected_coverage'],coverage)
                case['kernel_gear']['coverage'] = 'arbitration-denied'
                with self.assertRaises(ValueError):qualify_candidates(case,[])

    def test_coverage_counts_and_positive_wait_flag_are_checked(self):
        for change in (dict(arbitration_denials=0),dict(arbitration_denials=True),
                       dict(positive_wait=False),dict(positive_wait=1),dict(coverage='latency-only')):
            with self.subTest(change=change):
                self.reject(lambda c,d:c['kernel_gear'].update(change))

    def test_endpoint_triple_requires_actual_read_priority_then_write_denial(self):
        case,decisions = candidate_fixture(boundary=True)
        result = qualify_candidates(case,decisions)
        self.assertEqual(result['boundary_triple'],case['kernel_gear']['boundary_candidates'])
        self.assertEqual([e['hclock'] for e in result['boundary_triple']],[1149,1152,1155])
        self.assertEqual([e['kind'] for e in result['boundary_triple']],['read','read','write'])
        for index,change in ((0,dict(ready=False)),(1,dict(eligible=False,grant=None)),
                             (2,dict(attempt_kind='read',read_pending=1)),
                             (2,dict(before=decisions[2]['before']+3))):
            changed = copy.deepcopy(decisions); changed[index].update(change)
            with self.subTest(index=index,change=change),self.assertRaises(ValueError):
                qualify_candidates(case,changed)

    def test_endpoint_descriptor_cannot_relabel_other_family_or_clock(self):
        case,decisions = candidate_fixture(boundary=True)
        bad = copy.deepcopy(case); bad['family'] = 'bg'
        with self.assertRaises(ValueError):qualify_candidates(bad,decisions)
        bad = copy.deepcopy(case); bad['kernel_gear']['boundary_candidates'][1]['ticks'] += 1
        with self.assertRaises(ValueError):qualify_candidates(bad,decisions)


if __name__ == '__main__':
    unittest.main()

"""Independent arithmetic expectations for the narrow blank VDC diagnostic."""
import unittest

from scripts.vdc_phase import (PROFILE, HSW_PROFILE, predict_blank_dma_read_wait,
                               predict_periodic_hsw_dma_read_wait)


def facts(**changes):
    # Starting at horizontal tick200, thirty ticks contain15 VCE2 dots.
    # A127-word DMA therefore has508-15=493 dots left at target entry.
    result = dict(profile=PROFILE, access='high', cpu_divisor=3, vce_divider=2,
                  dma_words=127, launch_tick=0, launch_hclock=200,
                  target_tick=30, target_hclock=230, pending_dma_dots=493,
                  transfer_delay=0, queue_carry=0, read_pending=True,
                  write_pending=False, satb_pending_dots=0, display_control=0,
                  burst=True, sprite_count=0, selected_register=2,
                  hsw_excluded=True)
    result.update(changes)
    return result


class BlankVdcPhaseTests(unittest.TestCase):
    def test_cpu_prefix_and_whole_block_do_not_change_grant_phase(self):
        # Final DMA dot is at1016. The first eligible fast callback starts1017;
        # horizontal1217 is even dot608. Queue clears at callback end1020.
        for access, divisor, prefix, wait in (('high', 3, 3, 987),
                                              ('tai2', 3, 48, 942),
                                              ('high', 12, 12, 978),
                                              ('tai2', 12, 192, 798)):
            with self.subTest(access=access, divisor=divisor):
                result = predict_blank_dma_read_wait(**facts(access=access, cpu_divisor=divisor))
                self.assertEqual(result['predicted_completion_tick'], 1016)
                self.assertEqual(result['predicted_grant_start_tick'], 1017)
                self.assertEqual(result['predicted_grant_hclock'], 1217)
                self.assertEqual(result['prefix_ticks'], prefix)
                self.assertEqual(result['predicted_wait_ticks'], wait)

    def test_line_tail_and_vce_speed_are_distinct_from_cpu_speed(self):
        # VCE4 has341 dots per1365-tick line: one tail tick is not a dot.
        # The final ordinal558 is line1 dot217, at1365+868, minus origin200.
        result = predict_blank_dma_read_wait(**facts(vce_divider=4, pending_dma_dots=501))
        self.assertEqual(result['predicted_completion_tick'], 2033)
        self.assertEqual(result['predicted_grant_start_tick'], 2037)
        self.assertEqual(result['predicted_wait_ticks'], 2007)
        # At VCE3, ordinal574 is line1 dot119:1365+357-origin200=1522.
        result = predict_blank_dma_read_wait(**facts(vce_divider=3, pending_dma_dots=498))
        self.assertEqual(result['predicted_completion_tick'], 1522)
        self.assertEqual(result['predicted_grant_start_tick'], 1527)
        self.assertEqual(result['predicted_wait_ticks'], 1497)

    def test_three_tick_callback_checks_before_advancing_raster(self):
        # Four dots complete at8. The callback starting6 cannot grant on the
        # completion that it clocks; eligibility is checked again at9.
        result = predict_blank_dma_read_wait(**facts(dma_words=1, target_tick=0,
                                                    target_hclock=200, pending_dma_dots=4))
        self.assertEqual(result['predicted_completion_tick'], 8)
        self.assertEqual(result['predicted_grant_start_tick'], 9)
        self.assertEqual(result['predicted_wait_ticks'], 9)

    def test_queue_delay_is_an_independent_barrier_and_may_finish_in_prefix(self):
        for carry in (0, 1, 2):
            options = facts(dma_words=1, target_tick=0, target_hclock=200,
                            pending_dma_dots=4, transfer_delay=15, queue_carry=carry)
            result = predict_blank_dma_read_wait(**options)
            self.assertEqual(result['queue_delay_first_eligible_tick'], 12)
            self.assertEqual(result['predicted_grant_start_tick'], 12)
            self.assertEqual(result['predicted_wait_ticks'], 12)
            self.assertEqual(result['queue_carry_at_target'], carry)
            self.assertEqual(result['queue_carry_after_grant'], 0)
            result = predict_blank_dma_read_wait(**dict(options, access='tai2'))
            self.assertEqual(result['predicted_wait_ticks'], 0)

    def test_phase_facts_explain_six_tick_difference_without_clock_alignment(self):
        # Same source/count and114-tick setup, different observed line phase.
        # 1365 is odd, so crossing its tail changes the final even-dot lattice.
        gear = predict_blank_dma_read_wait(**facts(dma_words=4096,
            launch_hclock=678, target_tick=114, target_hclock=792, pending_dma_dots=16327))
        tool = predict_blank_dma_read_wait(**facts(dma_words=4096,
            launch_hclock=696, target_tick=114, target_hclock=810, pending_dma_dots=16327))
        self.assertEqual(gear['predicted_wait_ticks'], 32685)
        self.assertEqual(tool['predicted_wait_ticks'], 32679)
        self.assertEqual(tool['predicted_wait_ticks'] - gear['predicted_wait_ticks'], -6)

    def test_phase_and_one_remaining_dot_explain_three_tick_difference(self):
        gear = predict_blank_dma_read_wait(**facts(dma_words=4096, cpu_divisor=12, vce_divider=4,
            launch_hclock=1176, target_tick=456, target_hclock=267, pending_dma_dots=16271))
        tool = predict_blank_dma_read_wait(**facts(dma_words=4096, cpu_divisor=12, vce_divider=4,
            launch_hclock=396, target_tick=456, target_hclock=852, pending_dma_dots=16270))
        self.assertEqual(gear['predicted_wait_ticks'], 65121)
        self.assertEqual(tool['predicted_wait_ticks'], 65124)
        self.assertEqual(tool['predicted_wait_ticks'] - gear['predicted_wait_ticks'], 3)

    def test_absolute_time_translation_preserves_the_observed_phase_prediction(self):
        old = predict_blank_dma_read_wait(**facts())
        moved = predict_blank_dma_read_wait(**facts(launch_tick=100003, target_tick=100033))
        self.assertEqual(moved['predicted_wait_ticks'], old['predicted_wait_ticks'])
        for key in ('predicted_completion_tick', 'predicted_grant_start_tick', 'queue_delay_first_eligible_tick'):
            self.assertEqual(moved[key], old[key] + 100003)
        self.assertEqual(moved['search_bound_callbacks'], 455)
        self.assertLessEqual(moved['examined_callbacks'], 455)

    def test_observed_countdown_and_phase_are_required_not_inferred_from_wait(self):
        for change in (dict(pending_dma_dots=492), dict(target_hclock=231),
                       dict(target_tick=29), dict(launch_tick=31)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                predict_blank_dma_read_wait(**facts(**change))

    def test_unsupported_hsw_and_device_interference_are_refused(self):
        # Two words from hclock1340 at VCE4 finish at next-line tick8. Early
        # position alone is not HSW: accept when its gate is actually excluded.
        options = facts(dma_words=2, vce_divider=4, launch_hclock=1340,
                        target_tick=0, target_hclock=1340, pending_dma_dots=8)
        result = predict_blank_dma_read_wait(**options)
        self.assertEqual(result['predicted_completion_tick'], 33)
        self.assertEqual(result['predicted_grant_start_tick'], 33)
        self.assertEqual(result['predicted_grant_hclock'], 8)
        self.assertEqual(result['predicted_wait_ticks'], 33)
        with self.assertRaisesRegex(ValueError, 'hsw_excluded'):
            predict_blank_dma_read_wait(**dict(options, hsw_excluded=False))
        for change in (dict(profile='active-vram'), dict(access='write'),
                       dict(read_pending=False), dict(write_pending=True),
                       dict(satb_pending_dots=1), dict(display_control=128),
                       dict(burst=False), dict(sprite_count=1), dict(selected_register=1),
                       dict(hsw_excluded=False)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                predict_blank_dma_read_wait(**facts(**change))

    def test_strict_integer_bool_range_and_partial_tail_refusals(self):
        for change in (dict(cpu_divisor=True), dict(vce_divider=2.0),
                       dict(cpu_divisor=6), dict(vce_divider=5), dict(dma_words=0),
                       dict(dma_words=65537), dict(launch_hclock=1365),
                       dict(queue_carry=3), dict(transfer_delay=1),
                       dict(transfer_delay=18), dict(read_pending=1), dict(burst=1),
                       dict(hsw_excluded=1)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                predict_blank_dma_read_wait(**facts(**change))

    def test_clock_overflow_is_explicit(self):
        offset = (1 << 64) - 100
        with self.assertRaisesRegex(ValueError, 'overflows'):
            predict_blank_dma_read_wait(**facts(launch_tick=offset, target_tick=offset + 30))


def periodic_facts(**changes):
    result = facts()
    result.pop('hsw_excluded')
    result['profile'] = HSW_PROFILE
    result.update(changes)
    divider = result['vce_divider']
    initial = 32 if divider == 3 else 24
    # Authored snapshot construction from the declared source geometry. Grant
    # expectations below are separate literal dot/threshold calculations.
    for prefix in ('launch', 'target'):
        dot = result[prefix + '_hclock'] // divider
        state = 3 if dot < initial else 0
        result.setdefault(prefix + '_hstate', state)
        result.setdefault(prefix + '_hremaining', initial - dot if state == 3 else initial + 1024 - dot)
        result.setdefault(prefix + '_hsync_start', 0)
        result.setdefault(prefix + '_latched_hsr', 0x7F1F)
        result.setdefault(prefix + '_latched_hdr', 0x7F7F)
    return result


class PeriodicHswVdcPhaseTests(unittest.TestCase):
    def test_each_vce_threshold_keeps_hsw_and_odd_dot_blockers_distinct(self):
        for divider, grant, clocks, gates, odd in (
                (2, 21, [9, 12, 15, 18, 21], [True, True, False, False, False],
                 [False, False, True, True, False]),
                (3, 24, [12, 15, 18, 21, 24], [True, True, True, False, False],
                 [False, True, False, True, False]),
                (4, 33, [18, 21, 24, 27, 30, 33], [True, True, True, True, False, False],
                 [False, True, False, False, True, False])):
            with self.subTest(divider=divider):
                result = predict_periodic_hsw_dma_read_wait(**periodic_facts(
                    dma_words=1, vce_divider=divider, launch_hclock=0,
                    target_tick=0, target_hclock=0, pending_dma_dots=4))
                self.assertEqual(result['predicted_completion_tick'], 4 * divider)
                self.assertEqual(result['predicted_grant_start_tick'], grant)
                self.assertEqual(result['predicted_wait_ticks'], grant)
                self.assertEqual([c['hclock'] for c in result['candidates']], clocks)
                self.assertEqual([c['hsw_blocked'] for c in result['candidates']], gates)
                self.assertEqual([c['parity_blocked'] for c in result['candidates']], odd)
                self.assertEqual([c['granted'] for c in result['candidates']], [False] * (len(clocks) - 1) + [True])

    def test_equality_opens_guard_but_does_not_make_an_odd_dot_available(self):
        result = predict_periodic_hsw_dma_read_wait(**periodic_facts(
            dma_words=1, vce_divider=3, launch_hclock=0,
            target_tick=0, target_hclock=0, pending_dma_dots=4))
        boundary = next(c for c in result['candidates'] if c['hclock'] == 21)
        self.assertEqual(boundary['future_hclock'], 24)
        self.assertEqual(boundary['since_hsync'], 8 * 3)
        self.assertFalse(boundary['hsw_blocked'])
        self.assertTrue(boundary['parity_blocked'])
        self.assertFalse(boundary['granted'])
        self.assertEqual(result['predicted_grant_hclock'], 24)

    def test_pre_callback_hds_can_grant_when_future_clock_wraps_into_new_hsw(self):
        for divider, launch, completion, grant in ((3, 1350, 12, 12), (4, 1344, 16, 18)):
            with self.subTest(divider=divider):
                result = predict_periodic_hsw_dma_read_wait(**periodic_facts(
                    dma_words=1, vce_divider=divider, launch_hclock=launch,
                    target_tick=0, target_hclock=launch, pending_dma_dots=4))
                final = result['candidates'][-1]
                self.assertEqual(result['predicted_completion_tick'], completion)
                self.assertEqual(result['predicted_grant_start_tick'], grant)
                self.assertEqual(final['hclock'], 1362)
                self.assertEqual(final['future_hclock'], 0)
                self.assertEqual(final['hstate'], 0)
                self.assertFalse(final['hsw_blocked'])
                self.assertTrue(final['granted'])

    def test_line_crossing_restarts_hsw_without_resetting_dma_dot_ordinal(self):
        # Eight VCE4 dots from h1340 end at next-line h8. HSW then delays
        # the even-dot grant until h32; time57 is h32 after the line tail.
        result = predict_periodic_hsw_dma_read_wait(**periodic_facts(
            dma_words=2, vce_divider=4, launch_hclock=1340,
            target_tick=0, target_hclock=1340, pending_dma_dots=8))
        self.assertEqual(result['predicted_completion_tick'], 33)
        self.assertEqual(result['predicted_grant_start_tick'], 57)
        self.assertEqual(result['predicted_grant_hclock'], 32)
        self.assertEqual(result['predicted_wait_ticks'], 57)
        self.assertEqual(result['candidates'][0]['hclock'], 8)
        self.assertEqual(result['candidates'][0]['hstate'], 3)
        self.assertTrue(result['candidates'][0]['hsw_blocked'])

    def test_true_hsw_control_predicts_scalar_and_tai_waits_without_false_premise(self):
        for access, wait in (('high', 1074), ('tai2', 894)):
            result = predict_periodic_hsw_dma_read_wait(**periodic_facts(
                access=access, cpu_divisor=12, vce_divider=3, dma_words=127,
                launch_tick=1215, launch_hclock=1215, target_tick=1671,
                target_hclock=306, pending_dma_dots=356))
            self.assertEqual(result['predicted_completion_tick'], 2739)
            self.assertEqual(result['predicted_grant_start_tick'], 2754)
            self.assertEqual(result['predicted_wait_ticks'], wait)
            self.assertEqual([c['hclock'] for c in result['candidates']], [9, 12, 15, 18, 21, 24])
            self.assertEqual(result['profile'], HSW_PROFILE)

    def test_delay_carry_and_cpu_prefix_can_resolve_before_dynamic_wait(self):
        for carry in (0, 1, 2):
            options = periodic_facts(dma_words=1, vce_divider=2,
                launch_hclock=200, target_tick=0, target_hclock=200,
                pending_dma_dots=4, transfer_delay=15, queue_carry=carry)
            scalar = predict_periodic_hsw_dma_read_wait(**options)
            block = predict_periodic_hsw_dma_read_wait(**dict(options, access='tai2'))
            slow = predict_periodic_hsw_dma_read_wait(**dict(options, cpu_divisor=12))
            self.assertEqual(scalar['queue_delay_first_eligible_tick'], 12)
            self.assertEqual(scalar['predicted_grant_start_tick'], 12)
            self.assertEqual(scalar['predicted_wait_ticks'], 12)
            self.assertEqual(block['predicted_wait_ticks'], 0)
            self.assertEqual(slow['predicted_wait_ticks'], 3)
            self.assertEqual(scalar['queue_carry_at_target'], carry)
            self.assertEqual(scalar['queue_carry_after_grant'], 0)

    def test_no_hsw_legacy_reference_is_unchanged_where_its_premise_holds(self):
        legacy = predict_blank_dma_read_wait(**facts())
        extended = predict_periodic_hsw_dma_read_wait(**periodic_facts())
        for field in legacy.keys() - {'profile'}:
            self.assertEqual(extended[field], legacy[field], field)
        self.assertFalse(any(c['hsw_blocked'] for c in extended['candidates']))
        self.assertNotEqual(legacy['profile'], extended['profile'])

    def test_geometry_is_observed_from_both_latches_and_state_countdowns(self):
        for field, value in (('launch_latched_hsr', 0x001F), ('target_latched_hsr', 0),
                             ('launch_latched_hdr', 0), ('target_latched_hdr', 0),
                             ('launch_hstate', 3), ('target_hstate', 1),
                             ('launch_hremaining', 1), ('target_hremaining', 1),
                             ('launch_hsync_start', 1), ('target_hsync_start', 1364)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                predict_periodic_hsw_dma_read_wait(**periodic_facts(**{field: value}))

    def test_strict_types_profile_interference_phase_and_overflow_refusals(self):
        good = periodic_facts()
        for change in (dict(profile=PROFILE), dict(cpu_divisor=True), dict(vce_divider=3.0),
                       dict(queue_carry=3), dict(transfer_delay=1), dict(read_pending=1),
                       dict(burst=False), dict(satb_pending_dots=1), dict(display_control=128),
                       dict(launch_hstate=False), dict(target_hremaining=True),
                       dict(pending_dma_dots=492), dict(target_hclock=231)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                predict_periodic_hsw_dma_read_wait(**dict(good, **change))
        offset = (1 << 64) - 100
        with self.assertRaisesRegex(ValueError, 'overflows'):
            predict_periodic_hsw_dma_read_wait(**dict(good, launch_tick=offset, target_tick=offset + 30))


if __name__ == '__main__':
    unittest.main()

"""Pure arithmetic for the declared blank-even-no-HSW VDC read profile.

This diagnostic consumes observed facts; it neither drives a guest nor sets a
device clock. It is not a general VDC scheduler or a hardware timing oracle.
The caller must bind source PC, all eight MPRs and fetched bytes separately.
"""
from math import gcd

PROFILE = 'blank-even-no-hsw-v1'
LINE_TICKS = 1365
QUEUE_QUANTUM = 3
MAX_TICK = (1 << 64) - 1


def _integer(name, value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name} requires an integer in {low}..{high}')
    return value


def _boolean(name, value, wanted):
    if type(value) is not bool or value is not wanted:
        raise ValueError(f'{name} requires the observed value {wanted}')


def predict_blank_dma_read_wait(*, profile, access, cpu_divisor, vce_divider,
                                dma_words, launch_tick, launch_hclock,
                                target_tick, target_hclock, pending_dma_dots,
                                transfer_delay, queue_carry, read_pending,
                                write_pending, satb_pending_dots,
                                display_control, burst, sprite_count,
                                selected_register, hsw_excluded):
    """Predict one scalar-high or two-byte TAI queued-read wait.

    Preconditions describe a single VDC, constant VCE divider after the DMA
    launch, CR/latched display control zero, burst blanking, no sprites/SATB,
    one pending read, no write queue, VRR selected, and observed/source-backed
    exclusion of HSW gating throughout the post-DMA/post-delay candidate
    interval through grant. CR0 or burst alone does not establish that HSW
    fact. HSW earlier while DMA/delay blocks access is irrelevant. Counts refer to the
    target's entry, before its fixed CPU prefix. The launch is the actual
    LENR-high port write, before that store's injected CPU wait.

    Queue eligibility is evaluated at the start of each three-tick callback,
    before raster dots advance. The fixed prefix is one CPU cycle for LDA high,
    or fourteen startup plus two mapped-read cycles for TAI2. Those prefixes
    are exact multiples of three master ticks at both supported CPU speeds.
    Consequently a carry in 0..2 produces exactly one queue evaluation per
    callback and remains unchanged until the grant clears it. Transfer delay
    is accounted independently, rather than assuming a long DMA expires it.

    Actual HSW state and latch facts belong to the caller's exclusion proof;
    line position alone does not establish HSW. This version also excludes
    active-display fetches, queued writes, SATB interference and changes of VCE
    speed after launch.
    """
    if type(profile) is not str or profile != PROFILE:
        raise ValueError('Unsupported VDC phase profile')
    if type(access) is not str or access not in ('high', 'tai2'):
        raise ValueError('Supported accesses are scalar high and TAI2')
    _integer('cpu_divisor', cpu_divisor, 3, 12)
    _integer('vce_divider', vce_divider, 2, 4)
    if cpu_divisor not in (3, 12):
        raise ValueError('Supported CPU divisors are 3 and 12')
    _integer('dma_words', dma_words, 1, 65536)
    for name, value in (('launch_tick', launch_tick), ('target_tick', target_tick)):
        _integer(name, value, 0, MAX_TICK)
    for name, value in (('launch_hclock', launch_hclock), ('target_hclock', target_hclock)):
        _integer(name, value, 0, LINE_TICKS - 1)
    if target_tick < launch_tick:
        raise ValueError('Target precedes the observed DMA launch')
    _integer('pending_dma_dots', pending_dma_dots, 0, dma_words * 4)
    _integer('transfer_delay', transfer_delay, 0, 15 if vce_divider == 2 else 24)
    if transfer_delay % QUEUE_QUANTUM:
        raise ValueError('Unsupported partial read-transfer delay')
    _integer('queue_carry', queue_carry, 0, QUEUE_QUANTUM - 1)
    _boolean('read_pending', read_pending, True)
    _boolean('write_pending', write_pending, False)
    _boolean('burst', burst, True)
    _boolean('hsw_excluded', hsw_excluded, True)
    for name, value, wanted in (('satb_pending_dots', satb_pending_dots, 0),
                                ('display_control', display_control, 0),
                                ('sprite_count', sprite_count, 0),
                                ('selected_register', selected_register, 2)):
        _integer(name, value, wanted, wanted)

    # Each horizontal line restarts the dot phase. The incomplete line tail
    # contributes no dot at dividers2/4; flattening ticks/divider is incorrect.
    dots_per_line = LINE_TICKS // vce_divider
    position = launch_hclock + target_tick - launch_tick
    if position % LINE_TICKS != target_hclock:
        raise ValueError('Observed launch/target horizontal phases disagree')
    dots_at_target = ((position // LINE_TICKS) * dots_per_line
                      + (position % LINE_TICKS) // vce_divider)
    launch_dot_index = launch_hclock // vce_divider
    predicted_pending = max(0, dma_words * 4 - dots_at_target + launch_dot_index)
    if pending_dma_dots != predicted_pending:
        raise ValueError('Observed DMA countdown disagrees with launch/phase facts')

    # Invert the ordinal of the final DMA dot, including the plateau between
    # the last whole dot of one line and the next line's first dot.
    final_dot_index = launch_dot_index + dma_words * 4
    line, ordinal = divmod(final_dot_index - 1, dots_per_line)
    completion = launch_tick + line * LINE_TICKS + (ordinal + 1) * vce_divider - launch_hclock
    prefix = cpu_divisor * (1 if access == 'high' else 16)
    prefix_end = target_tick + prefix
    # A delay of3 becomes eligible at the first callback;24 at callback8.
    delay_first = target_tick + max(0, transfer_delay // QUEUE_QUANTUM - 1) * QUEUE_QUANTUM
    first = max(target_tick, completion, delay_first)
    callback = (first - target_tick + QUEUE_QUANTUM - 1) // QUEUE_QUANTUM
    # One full horizontal period visits every possible fast-cycle lattice
    # phase. This bound comes from the raster/clock periods, not an output quota.
    search_bound = LINE_TICKS // gcd(LINE_TICKS, QUEUE_QUANTUM)
    for examined in range(1, search_bound + 1):
        grant = target_tick + callback * QUEUE_QUANTUM
        hclock = (launch_hclock + grant - launch_tick) % LINE_TICKS
        if (hclock // vce_divider) % 2 == 0:
            break
        callback += 1
    else:
        raise ValueError('No blank slot in the complete supported phase period')
    end = grant + QUEUE_QUANTUM
    if max(completion, prefix_end, end) > MAX_TICK:
        raise ValueError('Predicted CPU/VDC clock overflows uint64')
    return dict(profile=PROFILE, predicted_wait_ticks=max(0, end - prefix_end),
                predicted_grant_start_tick=grant,
                predicted_completion_tick=completion,
                predicted_grant_hclock=hclock,
                pending_at_target=predicted_pending,
                prefix_ticks=prefix, queue_delay_first_eligible_tick=delay_first,
                queue_carry_at_target=queue_carry, queue_carry_after_grant=0,
                examined_callbacks=examined, search_bound_callbacks=search_bound,
                queue_quantum=QUEUE_QUANTUM, line_ticks=LINE_TICKS)

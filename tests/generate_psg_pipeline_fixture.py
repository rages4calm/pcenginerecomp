"""Authored PSG signal equations, never sampled runtime/emulator output.

Decimal arithmetic defines ideal 1.5 dB attenuation before integer quantization.
IEEE binary32 rounding is explicit at each HPF operation. The 48 kHz expectation
uses a separately evaluated Blackman/sinc equation and direct convolution over
the complete source sequence, without the runtime kernel or circular-buffer code.
"""
from decimal import Decimal, localcontext
import argparse
import math
from pathlib import Path
import struct


def gains():
    with localcontext() as ctx:
        ctx.prec = 80
        return [int(Decimal(65535)/192 * Decimal(10) ** (-Decimal(3)*i/40))
                for i in range(31)] + [0]


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def clamp(value):
    return max(-32768, min(32767, int(value)))


def truncdiv(value, divisor):
    return (-1 if value < 0 else 1) * (abs(value)//divisor)


def hpf(sums):
    previous_input = [0., 0.]
    previous_output = [0., 0.]
    result = []
    for pair in sums:
        output = []
        for side, value in enumerate(pair):
            x = f32(value / 2)
            y = f32(f32(x - previous_input[side]) +
                    f32(f32(Decimal('0.9985')) * previous_output[side]))
            previous_input[side], previous_output[side] = x, y
            output.append(clamp(y))
        result.append(output)
    return result


def source_data(frame, channel):
    # Ordinary authored DDA signals include constant positive/negative sections,
    # opposite stereo, a transition to silence and unclipped unipolar headroom.
    if frame < 4:
        return 31
    if frame < 8:
        return 0
    if frame < 40:
        return (frame * 11 + channel * 7) % 32
    return 16 if channel % 2 else 15


def source_sums(centered):
    result = []
    for frame in range(256):
        pair = [0, 0]
        for channel in range(6):
            level = 2 * source_data(frame, channel) - (31 if centered else 0)
            pair[0] += level * 341
            pair[1] += level * (10 if channel % 2 else 341)
        result.append(pair)
    return result


def resample(sequence):
    result = []
    # Direct output-time convolution; no phase accumulator or ring buffer.
    for output in range(1, len(sequence)*160//147+1):
        newest = (output*147+159)//160-1
        phase = (newest+1)*160-output*147
        center = 31+phase/160
        ideal = []
        for tap in range(64):
            x = tap-center
            z = 40000*x/44100
            window = .42+.5*math.cos(math.pi*x/32)+.08*math.cos(math.pi*x/16)
            ideal.append((40000/44100)*(1 if z == 0 else math.sin(math.pi*z)/(math.pi*z))*window)
        normalized = [v*(1 << 30)/sum(ideal) for v in ideal]
        coefficients = [math.floor(v+.5) if v >= 0 else -math.floor(-v+.5)
                        for v in normalized]
        coefficients[max(range(64), key=lambda i:abs(ideal[i]))] += (1 << 30)-sum(coefficients)
        pair = []
        for side in range(2):
            total = sum(coefficients[tap]*sequence[newest-tap][side]
                        for tap in range(min(64, newest+1)))
            rounded = (abs(total)+(1 << 29)) >> 30
            pair.append(clamp(-rounded if total < 0 else rounded))
        result.append(pair)
    return result


def render():
    parts = ['// Authored decimal/IEEE signal equations; regenerate with tests/generate_psg_pipeline_fixture.py.',
             '#pragma once', '#include <array>', '#include <cstdint>',
             'namespace psg_pipeline_fixture {',
             'inline constexpr std::array<unsigned,32> gain{'+','.join(map(str,gains()))+'};',
             'inline constexpr std::array<unsigned,16> balance{0,3,5,7,9,11,13,15,16,19,21,23,25,27,29,31};']

    def array(name, rows, wide=False):
        kind = 'std::int32_t' if wide else 'std::int16_t'
        parts.append(f'inline constexpr std::array<std::array<{kind},2>,{len(rows)}> {name}{{{{')
        parts.extend('    {{'+','.join(map(str,row))+'}},' for row in rows)
        parts.append('}};')

    for centered in (0,1):
        sums = source_sums(centered)
        array(f'source_{centered}', sums, True)
        raw = [[truncdiv(clamp(truncdiv(x,2)),3) for x in pair] for pair in sums]
        filtered = hpf(sums)
        array(f'filtered_{centered}', filtered)
        array(f'raw44100_{centered}', raw)
        mixed = [[truncdiv(x,3) for x in pair] for pair in filtered]
        array(f'filtered44100_{centered}', mixed)
        array(f'filtered48000_{centered}', resample(mixed))
    # Non-source signal vectors deliberately exceed S16 and expose clipped or
    # integer-halved history. Only these explicit math inputs bypass the PSG.
    edge_sums = [[3,-3],[3,-3],[6,-6],[200000,-200000],[0,0],
                 [-196608,196602],[0,0],[1,-1],[1,-1]]
    array('edge_sums',edge_sums,True)
    array('edge_filtered',hpf(edge_sums))
    # Authored polynomial sequence and independently counted LFO edges. These
    # are mathematical inputs, not records emitted by an emulator or runtime.
    noise_seeds = [131072,196608,229376,245760,253952,258048,129024,64512,
        32256,16128,8064,4032,133088,197616,229880,246012,254078,127039,
        194591,228367,245255,253699,257921,260032]
    array('noise_filtered',hpf([[10571 if seed%2 else -10571]*2 for seed in noise_seeds]))
    array('lfo_filtered',hpf([[-9889,0],[-9889,0],[-9207,0]]))
    decay = hpf([[10571,-10571]]*10001)
    marks = [0,1,2,31,127,511,2047,4095,8191,10000]
    parts.append('inline constexpr std::array<unsigned,10> decay_frames{'+','.join(map(str,marks))+'};')
    array('decay_filtered',[decay[i] for i in marks])
    parts.append('} // namespace psg_pipeline_fixture\n')
    return '\n'.join(parts)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('psg_pipeline_fixture.hpp'))
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    expected = render()
    if args.check:
        if args.output.read_text() != expected:
            raise SystemExit('PSG pipeline authored fixture is stale')
    else:
        args.output.write_text(expected,encoding='ascii',newline='\n')

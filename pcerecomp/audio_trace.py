"""Bounded, code-free audio traces with explicit signal domains.

Run ``python -m pcerecomp.audio_trace EXPECTED ACTUAL``. Comparisons never
filter, resample, align, change gain, or discard unequal samples implicitly.
Engine identity remains visible; a domain/fixture/phase mismatch is refused.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

FORMAT = 'pce-audio-trace-1'
MAX_FRAMES = 100_000
MAX_FILE_BYTES = 32 * 1024 * 1024
STAGES = ('psg-raw', 'psg-hpf', 'mixed-raw', 'mixed-filtered', 'resampled-filtered')
DOMAIN_KEYS = ('stage', 'timing', 'source_rate', 'output_rate', 'gain_divisor',
               'latency_source_frames', 'resampler')


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _keys(value, keys, label):
    _require(type(value) is dict and set(value) == set(keys), label + ' fields differ')


def _integer(value, low, high, label):
    _require(type(value) is int and low <= value <= high, 'Invalid ' + label)


def _digest(value, size, label):
    _require(type(value) is str and re.fullmatch('[0-9a-f]{' + str(size) + '}', value) is not None,
             'Invalid ' + label)


def validate_trace(trace):
    """Validate a complete trace; return it without projecting its fields."""
    _keys(trace, ('schema', 'format', 'engine', 'fixture_sha256', 'case', 'domain',
                  'first_frame', 'samples'), 'Audio trace')
    _require(type(trace['schema']) is int and trace['schema'] == 1 and trace['format'] == FORMAT,
             'Unsupported audio trace schema or format')
    engine = trace['engine']
    _keys(engine, ('name', 'revision', 'source_sha256', 'binary_sha256'), 'Audio engine')
    _require(type(engine['name']) is str and
             re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 ._+\-]{0,63}', engine['name']) is not None,
             'Invalid audio engine name')
    _digest(engine['revision'], 40, 'engine revision')
    for key in ('source_sha256', 'binary_sha256'):
        _digest(engine[key], 64, 'engine ' + key)
    _digest(trace['fixture_sha256'], 64, 'audio fixture digest')
    _require(type(trace['case']) is str and
             re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._\-]{0,95}', trace['case']) is not None,
             'Invalid audio case')
    domain = trace['domain']
    _keys(domain, DOMAIN_KEYS, 'Audio domain')
    _require(type(domain['stage']) is str and domain['stage'] in STAGES,
             'Unsupported audio stage')
    _require(type(domain['timing']) is str and domain['timing'] in ('gear-v1', 'legacy-v1'),
             'Unsupported audio sample timing')
    _integer(domain['source_rate'], 44100, 44100, 'audio source rate')
    _integer(domain['output_rate'], 44100, 48000, 'audio output rate')
    _require(domain['output_rate'] in (44100, 48000), 'Unsupported audio output rate')
    _integer(domain['gain_divisor'], 1, 3, 'audio gain divisor')
    _require(domain['gain_divisor'] in (1, 3), 'Unsupported audio gain divisor')
    _integer(domain['latency_source_frames'], 0, 31, 'audio source latency')
    if domain['stage'] == 'resampled-filtered':
        _require(domain['output_rate'] == 48000 and domain['gain_divisor'] == 3 and
                 domain['latency_source_frames'] == 31 and domain['resampler'] == 'fir64x160-q30-v1',
                 'Resampled audio domain requires the declared 48 kHz FIR and latency')
    else:
        _require(domain['output_rate'] == 44100 and domain['latency_source_frames'] == 0 and
                 domain['resampler'] == 'identity-v1',
                 'Source audio domain requires 44.1 kHz without resampling')
        if domain['stage'].startswith('mixed-'):
            _require(domain['gain_divisor'] == 3, 'Mixed audio requires the declared source headroom')
    _integer(trace['first_frame'], 1, 2**64 - 1, 'first audio frame')
    samples = trace['samples']
    _require(type(samples) is list and 1 <= len(samples) <= MAX_FRAMES,
             'Audio trace frame count outside bounds')
    _require(trace['first_frame'] + len(samples) - 1 <= 2**64 - 1,
             'Audio trace frame ordinal overflow')
    for row in samples:
        _require(type(row) is list and len(row) == 2, 'Stereo audio frame required')
        for value in row:
            _integer(value, -32768, 32767, 'signed 16-bit audio sample')
    return trace


def _parse(data):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, 'Duplicate audio JSON key: ' + key)
            result[key] = value
        return result

    def constant(value):
        raise ValueError('Invalid audio JSON constant: ' + value)

    try:
        trace = json.loads(data.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError('Invalid audio trace JSON or UTF-8') from error
    return validate_trace(trace)


def load_trace(path):
    """Load at most MAX_FILE_BYTES, including a file that grows during reading."""
    with Path(path).open('rb') as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    _require(len(data) <= MAX_FILE_BYTES, 'Audio trace file exceeds byte bound')
    return _parse(data)


def compare_traces(expected, actual):
    """Compare every S16 frame in compatible domains, retaining both engines."""
    expected, actual = validate_trace(expected), validate_trace(actual)
    for key in ('fixture_sha256', 'case', 'domain', 'first_frame'):
        _require(expected[key] == actual[key], 'Audio traces differ in ' + key + '; comparison refused')
    left, right = expected['samples'], actual['samples']
    matched = 0
    difference = None
    for ordinal, (a, b) in enumerate(zip(left, right)):
        if a != b:
            channel = next(i for i in range(2) if a[i] != b[i])
            difference = dict(frame=expected['first_frame'] + ordinal, channel=channel,
                              expected=a[channel], actual=b[channel])
            break
        matched += 1
    if difference is None and len(left) != len(right):
        difference = dict(frame=expected['first_frame'] + matched, field='frame-count',
                          expected=len(left), actual=len(right))
    return dict(schema=1, format='pce-audio-comparison-1', compatible=True,
                equal=difference is None, expected_engine=expected['engine'], actual_engine=actual['engine'],
                domain=expected['domain'], case=expected['case'], fixture_sha256=expected['fixture_sha256'],
                first_frame=expected['first_frame'], expected_frames=len(left), actual_frames=len(right),
                matched_frames=matched, first_difference=difference)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('expected', type=Path)
    parser.add_argument('actual', type=Path)
    parser.add_argument('--output', type=Path, help='Write a NEW comparison JSON file; never overwrite')
    args = parser.parse_args(argv)
    try:
        result = compare_traces(load_trace(args.expected), load_trace(args.actual))
        encoded = json.dumps(result, indent=2) + '\n'
        if args.output is not None:
            with args.output.open('x', encoding='utf-8', newline='\n') as stream:
                stream.write(encoded)
        print(encoded, end='')
        return 0 if result['equal'] else 1
    except (OSError, ValueError) as error:
        print(json.dumps(dict(schema=1, format='pce-audio-comparison-1', compatible=False,
                              error=str(error))))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

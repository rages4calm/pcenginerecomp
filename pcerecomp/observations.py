"""Private, additive code catalogues with independently verifiable raw provenance.

A profile is not a capture or a newly executed run. Historical counters sum
distinct input files; overlapping windows cannot be identified automatically.
"""
import base64
import binascii
import hashlib
import json
from pathlib import Path

from .capture import MAX_CAPTURE_BYTES, MAX_OBSERVATIONS, U64, integer, validate_capture
from .isa import decode

FORMAT = 'pce-observation-profile-1'
MAX_PROFILE_BYTES = 128 * 1024 * 1024
MAX_INPUTS = 256
MAX_TOTAL_INPUT_BYTES = 64 * 1024 * 1024
MAX_CONTRIBUTIONS = 262144


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key in observation input')
            result[key] = value
        return result

    def no_float(value):
        raise ValueError('Observation inputs require integer numeric tokens')

    try:
        return json.loads(raw, object_pairs_hook=unique, parse_float=no_float,
                          parse_constant=no_float)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError('Invalid observation JSON encoding or nesting') from exc


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          allow_nan=False).encode('utf-8')
    except (TypeError, RecursionError) as exc:
        raise ValueError('Invalid observation profile JSON values') from exc


def _digest(value):
    if (not isinstance(value, str) or len(value) != 64
            or any(c not in '0123456789abcdef' for c in value)):
        raise ValueError('Input identity requires lowercase SHA256')
    return value


def _add(left, right, label):
    return integer(left + right, U64, label)


def _derive(inputs, capacity):
    """Rebuild all union facts exclusively from hash-verified original bytes."""
    if not isinstance(inputs, list) or not 1 <= len(inputs) <= MAX_INPUTS:
        raise ValueError(f'Profile requires one to {MAX_INPUTS} distinct inputs')
    seen, union, metadata = set(), {}, []
    totals = {'native_hits': 0, 'interpreted_hits': 0, 'retired_instructions': 0}
    total_bytes = contributions = 0
    for source in inputs:
        if not isinstance(source, dict) or set(source) != {'sha256', 'size_bytes', 'raw_base64'}:
            raise ValueError('Invalid observation input provenance fields')
        digest = _digest(source['sha256'])
        if digest in seen:
            raise ValueError('Duplicate observation input SHA256')
        seen.add(digest)
        size = integer(source['size_bytes'], MAX_CAPTURE_BYTES, 'input byte size', 1)
        total_bytes += size
        if total_bytes > MAX_TOTAL_INPUT_BYTES:
            raise ValueError('Total original capture bytes exceed profile limit')
        encoded = source['raw_base64']
        if not isinstance(encoded, str) or len(encoded) != 4 * ((size + 2) // 3):
            raise ValueError('Input base64 length disagrees with original byte size')
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError('Invalid original capture base64') from exc
        if (len(raw) != size or base64.b64encode(raw).decode('ascii') != encoded
                or hashlib.sha256(raw).hexdigest() != digest):
            raise ValueError('Original capture SHA256, size or canonical base64 disagrees')
        capture = _json(raw)
        decoded = validate_capture(capture)
        if not capture['complete']:
            raise ValueError('Observation profiles require complete lossless inputs')
        contributions += len(decoded)
        if contributions > MAX_CONTRIBUTIONS:
            raise ValueError('Observation contribution capacity exceeded')
        native = sum(item['native_hits'] for item in decoded)
        interpreted = sum(item['interpreted_hits'] for item in decoded)
        for key, value in (('native_hits', native), ('interpreted_hits', interpreted),
                           ('retired_instructions', capture['retired_instructions'])):
            totals[key] = _add(totals[key], value, 'historical '+key)
        detail = {key: value for key, value in capture.items() if key != 'observations'}
        detail.update(sha256=digest, size_bytes=size, native_hits=native,
                      interpreted_hits=interpreted, observation_count=len(decoded))
        metadata.append(detail)
        for item in decoded:
            key = (item['pc'], tuple(item['mpr']), tuple(item['data']))
            if key not in union:
                if len(union) >= capacity:
                    raise ValueError('Observation union capacity exceeded; no identities dropped')
                union[key] = {name: list(item[name]) if name in ('mpr', 'physical', 'data') else item[name]
                              for name in ('pc', 'mpr', 'physical', 'data')}
                union[key].update(native_hits=0, interpreted_hits=0, contributions=[])
            entry = union[key]
            for tier in ('native_hits', 'interpreted_hits'):
                entry[tier] = _add(entry[tier], item[tier], 'union '+tier)
            _add(entry['native_hits'], entry['interpreted_hits'], 'union total hits')
            entry['contributions'].append({'input_sha256': digest,
                                          'native_hits': item['native_hits'],
                                          'interpreted_hits': item['interpreted_hits']})
    _add(totals['native_hits'], totals['interpreted_hits'], 'historical total hits')
    if totals['native_hits'] + totals['interpreted_hits'] != totals['retired_instructions']:
        raise ValueError('Historical retirement sum disagrees')
    ordered = sorted(union.values(), key=lambda item: (item['mpr'], item['pc'], item['data']))
    for item in ordered:
        item['contributions'].sort(key=lambda contribution: contribution['input_sha256'])
    return ordered, totals, sorted(metadata, key=lambda item: item['sha256'])


def compose_observation_profile(input_paths, *, capacity=MAX_OBSERVATIONS):
    """Compose lossless original capture files; duplicate raw files count once.

    No input is edited. SHA ordering makes results independent of argument order.
    Paths are deliberately absent from the portable, private profile.
    """
    integer(capacity, MAX_OBSERVATIONS, 'profile capacity', 1)
    sources, total = {}, 0
    for index, path in enumerate(input_paths):
        if index >= MAX_INPUTS:
            raise ValueError(f'At most {MAX_INPUTS} input paths are accepted')
        with Path(path).open('rb') as stream:
            raw = stream.read(MAX_CAPTURE_BYTES + 1)
        if len(raw) > MAX_CAPTURE_BYTES:
            raise ValueError('Code capture exceeds 64 MiB')
        digest = hashlib.sha256(raw).hexdigest()
        if digest in sources:
            continue
        total += len(raw)
        if total > MAX_TOTAL_INPUT_BYTES:
            raise ValueError('Total original capture bytes exceed profile limit')
        sources[digest] = {'sha256': digest, 'size_bytes': len(raw),
                           'raw_base64': base64.b64encode(raw).decode('ascii')}
    inputs = [sources[key] for key in sorted(sources)]
    observations, totals, _ = _derive(inputs, capacity)
    profile = {'format': FORMAT, 'schema': 1, 'execution_evidence': False,
               'capacity': capacity, 'inputs': inputs, 'observations': observations,
               'historical_totals': totals}
    if len(_canonical(profile)) > MAX_PROFILE_BYTES:
        raise ValueError('Observation profile exceeds 128 MiB')
    return profile


def _validate(profile):
    fields = {'format', 'schema', 'execution_evidence', 'capacity', 'inputs',
              'observations', 'historical_totals'}
    if not isinstance(profile, dict) or set(profile) != fields:
        raise ValueError('Invalid observation profile fields')
    if profile['format'] != FORMAT or type(profile['schema']) is not int or profile['schema'] != 1:
        raise ValueError('Unsupported observation profile format/schema')
    if profile['execution_evidence'] is not False:
        raise ValueError('An observation profile is not execution evidence')
    capacity = integer(profile['capacity'], MAX_OBSERVATIONS, 'profile capacity', 1)
    observations = profile['observations']
    if not isinstance(observations, list) or len(observations) > capacity:
        raise ValueError('Observation union capacity exceeded')
    if len(_canonical(profile)) > MAX_PROFILE_BYTES:
        raise ValueError('Observation profile exceeds 128 MiB')
    expected, totals, metadata = _derive(profile['inputs'], capacity)
    if [item['sha256'] for item in profile['inputs']] != sorted(item['sha256'] for item in profile['inputs']):
        raise ValueError('Profile input provenance must be in canonical SHA256 order')
    # JSON comparison preserves strict numeric types (True and 1 are different).
    if _canonical(observations) != _canonical(expected):
        raise ValueError('Profile observations/contributions disagree with original captures')
    if _canonical(profile['historical_totals']) != _canonical(totals):
        raise ValueError('Profile historical totals disagree with original captures')
    # Decode translation reports without manufacturing a singular capture ABI.
    decoded = []
    for item in expected:
        pc, data, mpr = item['pc'], item['data'], tuple(item['mpr'])
        ins = decode(lambda address: data[(address - pc) & 65535], pc, mpr)
        decoded.append(ins.report() | {'mpr': mpr, 'native_hits': item['native_hits'],
                                       'interpreted_hits': item['interpreted_hits']})
    return decoded, metadata


def validate_observation_profile(profile):
    """Return decoded canonical identities, after rehashing all original inputs."""
    return _validate(profile)[0]


def observation_profile_provenance(profile):
    """Return exact original per-input metadata, without embedding source bytes."""
    return _validate(profile)[1]


def load_observation_profile(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_PROFILE_BYTES + 1)
    if len(raw) > MAX_PROFILE_BYTES:
        raise ValueError('Observation profile exceeds 128 MiB')
    profile = _json(raw)
    validate_observation_profile(profile)
    return profile, hashlib.sha256(raw).hexdigest()

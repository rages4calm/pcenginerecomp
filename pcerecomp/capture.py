"""Strict bounded private observations; captures contain translated-source bytes."""
import hashlib
import io
import json
from pathlib import Path

from .abi import CAPTURE_ABIS
from .isa import decode

MAX_CAPTURE_BYTES = 64 * 1024 * 1024
MAX_OBSERVATIONS = 65536
EXTENDED_FORMAT = 'pce-code-capture-2'
EXTENDED_SCHEMA = 2
EXTENDED_MAGIC = b'{"format":"pce-code-capture-2","schema":2}\n'
MAX_EXTENDED_CAPTURE_BYTES = 512 * 1024 * 1024
MAX_EXTENDED_OBSERVATIONS = 1048576
MAX_CAPTURE_LINE_BYTES = 64 * 1024
U64 = (1 << 64) - 1


def integer(value, maximum, label, minimum=0):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer in {minimum}..{maximum}")
    return value


def validate_execution_policy(policy):
    """Exact host capability metadata; this never changes guest state identity."""
    fields = {'schema', 'reference_enabled', 'selected', 'configured_tier',
              'effective_policy', 'effective_native_span'}
    if not isinstance(policy, dict) or set(policy) != fields:
        raise ValueError('Invalid execution policy fields')
    if type(policy['schema']) is not int or policy['schema'] != 1:
        raise ValueError('Unsupported execution policy schema')
    if any(type(policy[key]) is not bool for key in ('reference_enabled', 'selected')):
        raise ValueError('Execution policy flags require booleans')
    tier, selected = policy['configured_tier'], policy['selected']
    if tier not in ('native', 'hybrid'):
        raise ValueError('Invalid configured execution tier')
    expected = 'interpreter' if selected else tier
    if policy['effective_policy'] != expected or (selected and not policy['reference_enabled']):
        raise ValueError('Incoherent execution policy selection')
    span = integer(policy['effective_native_span'], 256, 'effective native span')
    if (selected and span != 0) or (not selected and span == 0):
        raise ValueError('Execution policy span disagrees with selection')
    return dict(policy)


def validate_capture(capture):
    """Return canonical observations with decoder-derived instruction metadata."""
    fields = {
        'schema', 'runtime_abi', 'capacity', 'dropped_instructions',
        'unreadable_instructions', 'retired_instructions', 'complete', 'observations'
    }
    optional = {'checkpoint_origin', 'execution_policy'}
    extended = (isinstance(capture, dict) and type(capture.get('schema')) is int
                and capture['schema'] == EXTENDED_SCHEMA)
    if extended:
        fields = fields | {'format'}
    if not isinstance(capture, dict) or not fields <= set(capture) or set(capture) - fields - optional:
        raise ValueError('Invalid code-capture fields')
    if 'checkpoint_origin' in capture:
        validate_checkpoint_origin(capture['checkpoint_origin'])
    if type(capture['schema']) is not int or capture['schema'] not in (1, EXTENDED_SCHEMA):
        raise ValueError('Unsupported code-capture schema')
    if extended and (capture['format'] != EXTENDED_FORMAT or capture['runtime_abi'] != 29):
        raise ValueError('Extended code capture requires its declared format and ABI29')
    if type(capture['runtime_abi']) is not int or capture['runtime_abi'] not in CAPTURE_ABIS:
        raise ValueError('Unsupported code-capture runtime ABI')
    policy = None
    if 'execution_policy' in capture:
        policy = validate_execution_policy(capture['execution_policy'])
        if capture['runtime_abi'] < 29 or not policy['reference_enabled']:
            raise ValueError('Capture execution policy requires a reference-enabled ABI29 producer')
    capacity = integer(capture['capacity'], MAX_EXTENDED_OBSERVATIONS if extended else MAX_OBSERVATIONS, 'capacity', 1)
    dropped = integer(capture['dropped_instructions'], U64, 'dropped instructions')
    unreadable = integer(capture['unreadable_instructions'], U64, 'unreadable instructions')
    retired = integer(capture['retired_instructions'], U64, 'retired instructions')
    if type(capture['complete']) is not bool or capture['complete'] != (dropped == 0 and unreadable == 0):
        raise ValueError('Capture completeness disagrees with counters')
    observations = capture['observations']
    if not isinstance(observations, list) or len(observations) > capacity:
        raise ValueError('Observation capacity exceeded')
    seen, result, total = set(), [], dropped + unreadable
    for item in observations:
        if not isinstance(item, dict) or set(item) != {'pc', 'mpr', 'physical', 'data', 'native_hits', 'interpreted_hits'}:
            raise ValueError('Invalid observation fields')
        pc = integer(item['pc'], 65535, 'logical PC')
        mpr, raw, addresses = item['mpr'], item['data'], item['physical']
        if not isinstance(mpr, list) or len(mpr) != 8:
            raise ValueError('MPR mapping requires eight bytes')
        mpr = tuple(integer(v, 255, 'MPR') for v in mpr)
        if not isinstance(raw, list) or not 1 <= len(raw) <= 7:
            raise ValueError('Instruction data requires one to seven bytes')
        raw = tuple(integer(v, 255, 'instruction byte') for v in raw)
        if not isinstance(addresses, list) or len(addresses) != len(raw):
            raise ValueError('Physical addresses must match instruction bytes')
        addresses = tuple(integer(v, 0x1fffff, 'physical address') for v in addresses)
        def read(address):
            offset = (address - pc) & 65535
            if offset >= len(raw):
                raise ValueError('Truncated instruction data')
            return raw[offset]
        ins = decode(read, pc, mpr)
        if ins.data != raw or ins.physical != addresses:
            raise ValueError('Instruction length or physical mapping disagrees with decoder')
        native = integer(item['native_hits'], U64, 'native hits')
        if policy and policy['selected'] and native:
            raise ValueError('Interpreter reference capture contains native retirements')
        interpreted = integer(item['interpreted_hits'], U64, 'interpreted hits')
        if not 0 < native + interpreted <= U64:
            raise ValueError('Observation must have a bounded nonzero hit count')
        key = (pc, mpr, raw)
        if key in seen:
            raise ValueError('Duplicate observed instruction identity')
        seen.add(key)
        total += native + interpreted
        result.append(ins.report() | {'mpr': mpr, 'native_hits': native, 'interpreted_hits': interpreted})
    if total != retired:
        raise ValueError('Capture retirement total disagrees with observations')
    return sorted(result, key=lambda ins: (ins['mpr'], ins['pc'], ins['data']))


def validate_checkpoint_origin(origin):
    """Exact imported boundary; observation totals describe only its new suffix."""
    fields = {'sha256', 'ticks', 'frame', 'native_steps', 'interpreter_steps'}
    if not isinstance(origin, dict) or set(origin) != fields:
        raise ValueError('Invalid checkpoint capture origin fields')
    digest = origin['sha256']
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('Checkpoint origin requires lowercase SHA256')
    for key in fields - {'sha256'}:
        integer(origin[key], U64, 'checkpoint origin '+key)
    return dict(origin)


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key in code capture')
            result[key] = value
        return result
    def no_float(value):
        raise ValueError('Code capture requires integer numeric tokens')
    try:
        return json.loads(raw, object_pairs_hook=unique, parse_float=no_float,
                          parse_constant=no_float)
    except (UnicodeError, RecursionError) as error:
        raise ValueError('Invalid code-capture JSON encoding or nesting') from error


def parse_capture_bytes(raw, *, validate=True):
    """Admit legacy JSON or exact framed format 2; never infer wider legacy limits.

    Shared derivation may explicitly defer decoder validation to its own next
    step. Framing, per-record bounds and legacy schema discrimination always run.
    """
    if not isinstance(raw, bytes):
        raise ValueError('Code capture input requires original bytes')
    if type(validate) is not bool:
        raise ValueError('Capture validation selection requires a boolean')
    if not raw.startswith(EXTENDED_MAGIC):
        if len(raw) > MAX_CAPTURE_BYTES:
            raise ValueError('Code capture exceeds 64 MiB')
        capture = _json(raw)
        if not isinstance(capture, dict) or type(capture.get('schema')) is not int or capture['schema'] != 1:
            raise ValueError('Unframed code capture requires legacy schema 1')
    else:
        if len(raw) > MAX_EXTENDED_CAPTURE_BYTES:
            raise ValueError('Extended code capture exceeds 512 MiB')
        stream = io.BytesIO(raw)
        stream.seek(len(EXTENDED_MAGIC))

        def record():
            line = stream.readline(MAX_CAPTURE_LINE_BYTES+1)
            if not line or len(line) > MAX_CAPTURE_LINE_BYTES or not line.endswith(b'\n'):
                raise ValueError('Extended capture record is missing, truncated or exceeds 64 KiB')
            try:
                text = line.decode('utf-8')
            except UnicodeError as error:
                raise ValueError('Extended capture records require UTF-8') from error
            if '\0' in text or text.startswith('\ufeff'):
                raise ValueError('Extended capture records require UTF-8 without a BOM or NUL')
            value = _json(text)
            if type(value) is not dict:
                raise ValueError('Extended capture record requires a JSON object')
            return value, line

        header, _ = record()
        required = {'runtime_abi', 'capacity', 'dropped_instructions',
                    'unreadable_instructions', 'retired_instructions', 'complete'}
        if not required <= set(header) or set(header)-required-{'checkpoint_origin', 'execution_policy'}:
            raise ValueError('Invalid extended capture header fields')
        # Bound the allocation before reading or retaining observation records.
        capacity = integer(header['capacity'], MAX_EXTENDED_OBSERVATIONS, 'capacity', 1)
        rows = []
        while True:
            value, line = record()
            if 'record' in value:
                if (set(value) != {'record', 'observations'} or value['record'] != 'end'
                        or type(value['observations']) is not int or value['observations'] != len(rows)):
                    raise ValueError('Invalid extended capture footer or observation count')
                expected = b'{"record":"end","observations":'+str(len(rows)).encode('ascii')+b'}\n'
                if line != expected or stream.read(1):
                    raise ValueError('Extended capture footer must be exact and terminal')
                break
            if len(rows) == capacity:
                raise ValueError('Extended capture observation capacity exceeded')
            if set(value) != {'pc', 'mpr', 'physical', 'data', 'native_hits', 'interpreted_hits'}:
                raise ValueError('Invalid extended observation fields')
            rows.append(value)
        capture = dict(schema=EXTENDED_SCHEMA, format=EXTENDED_FORMAT, **header, observations=rows)
    if validate:
        validate_capture(capture)
    return capture


def load_capture(path: Path):
    with Path(path).open('rb') as stream:
        extended = stream.read(len(EXTENDED_MAGIC)) == EXTENDED_MAGIC
        stream.seek(0)
        raw = stream.read((MAX_EXTENDED_CAPTURE_BYTES if extended else MAX_CAPTURE_BYTES)+1)
    capture = parse_capture_bytes(raw)
    return capture, hashlib.sha256(raw).hexdigest()

"""Versioned consumer contract, checked builds and bounded execution receipts.

No installation, dependency download or implicit media/save discovery.
All descriptor paths are relative to the descriptor, never the caller's cwd.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import tomllib

from .abi import ABI
MAX_WALL_SECONDS = 86400
MAX_MODULE_MANIFEST_BYTES = 64 * 1024 * 1024
SOURCE_DIRS = ("pcerecomp", "runtime", "cmake")
ASSETS = {"bios", "bram", "toc", "disc", "libchdr", "input_script", "cartridge"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_identity(root: Path) -> dict:
    """Hash exact relevant source bytes, including untracked relevant files.

    Canonical encoding: sorted UTF-8 relative POSIX paths, NUL, ASCII decimal
    byte count, NUL, exact file bytes. Caches, docs and tests are not code inputs.
    """
    root = root.resolve()
    paths = [root / "CMakeLists.txt"]
    for directory in SOURCE_DIRS:
        base = root / directory
        if not base.is_dir():
            raise ValueError(f"Missing tool source directory: {directory}")
        paths.extend(p for p in base.rglob("*") if p.is_file()
                     and "__pycache__" not in p.parts
                     and p.suffix in {".py", ".cpp", ".hpp", ".h", ".cmake"})
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda p: p.relative_to(root).as_posix()):
        name = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(name + b"\0" + str(path.stat().st_size).encode() + b"\0")
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True, check=False)
    revision = None
    if top.returncode == 0 and Path(top.stdout.strip()).resolve() == root:
        result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                                capture_output=True, text=True, check=False)
        if result.returncode == 0:
            revision = result.stdout.strip()
    return {"revision": revision, "source_sha256": digest.hexdigest(),
            "source_files": len(paths)}


def _table(value, required, optional=(), name="table"):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise ValueError(f"Invalid {name} fields; required {sorted(required)}, optional {sorted(optional)}")
    return value


def _integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be {low}..{high}")
    return value


def _digest(value, name):
    if not isinstance(value, str) or re.fullmatch("[0-9a-f]{64}", value) is None:
        raise ValueError(f"{name} must be a lowercase SHA256")
    return value


def _choice(value, values, name):
    if value not in values:
        raise ValueError(f"{name} must be one of {values}")


def _file(base, entry, name):
    _table(entry, {"path", "sha256"}, name=name)
    if not isinstance(entry["path"], str) or not entry["path"]:
        raise ValueError(f"Invalid {name} path")
    path = (base / entry["path"]).resolve()
    expected = _digest(entry["sha256"], name)
    if not path.is_file() or sha256(path) != expected:
        raise ValueError(f"{name} SHA256 mismatch or missing file")
    return path


def _module_artifacts(files, manifest):
    """Pin all authored/generated code inputs of a multi-unit module.

    Legacy manifests without either list still describe one source. Once a
    list is present, both lists are required, even for a single translation
    unit with no generated headers. Names are portable direct children of the
    manifest directory; a manifest never authorizes arbitrary extra paths.
    """
    if not ({"translation_units", "generated_headers"} & manifest.keys()):
        return
    base = files["module_manifest"].parent
    seen, units = set(), []
    maximum_units = 1048577 if (manifest.get('observation_history_schema') == 2
                               or manifest.get('capture_schema') == 2
                               or 'declared_roots_sha256' in manifest) else 65537
    for field, suffix, minimum, maximum, prefix in (
            ("translation_units", ".cpp", 1, maximum_units, "module_unit"),
            ("generated_headers", ".hpp", 0, 256, "module_header")):
        entries = manifest.get(field)
        if not isinstance(entries, list) or not minimum <= len(entries) <= maximum:
            raise ValueError(f"Module {field} requires {minimum}..{maximum} artifact entries")
        for entry in entries:
            _table(entry, {"file", "sha256"}, name=f"Module {field} artifact")
            name = entry["file"]
            if (not isinstance(name, str) or not 1 <= len(name) <= 128
                    or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) is None
                    or not name.endswith(suffix)
                    or name.split(".", 1)[0].upper() in {
                        "CON", "PRN", "AUX", "NUL",
                        *(f"COM{i}" for i in range(1, 10)),
                        *(f"LPT{i}" for i in range(1, 10))}):
                raise ValueError(f"Module {field} requires portable {suffix} basenames")
            if name.casefold() in seen:
                raise ValueError("Duplicate module artifact basename (case-insensitive)")
            seen.add(name.casefold())
            artifact = base / name
            path = artifact.resolve()
            if artifact.is_symlink() or path.parent != base:
                raise ValueError("Module artifact must remain in manifest directory and cannot be a symlink")
            expected = _digest(entry["sha256"], f"Module artifact {name}")
            if not path.is_file() or sha256(path) != expected:
                raise ValueError(f"Module artifact {name} SHA256 mismatch or missing file")
            files[f"{prefix}:{name}"] = path
            if field == "translation_units":
                units.append(path)
    if files["module_source"] not in units:
        raise ValueError("Module translation_units must include module source entry")


def _module_manifest(path):
    """Read one bounded manifest without ambiguous JSON fields or numbers."""
    if path.stat().st_size > MAX_MODULE_MANIFEST_BYTES:
        raise ValueError('Module manifest exceeds 64 MiB')
    with path.open('rb') as stream:
        raw = stream.read(MAX_MODULE_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MODULE_MANIFEST_BYTES:
        raise ValueError('Module manifest exceeds 64 MiB')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key in module manifest')
            result[key] = value
        return result
    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('Nonfinite number in module manifest')
        return result
    def no_constant(value):
        raise ValueError('Nonfinite number in module manifest')
    try:
        manifest = json.loads(raw, object_pairs_hook=unique, parse_float=finite_float,
                              parse_constant=no_constant)
        if isinstance(manifest, dict):
            from .native_catalog import _shared_layout_contract
            _shared_layout_contract(manifest)
        return manifest
    except (UnicodeError, RecursionError) as error:
        raise ValueError('Invalid module manifest JSON encoding or nesting') from error


def _module_observation_profile(base, entry, files, manifest):
    """Bind original profile provenance and selection facts, without code emission.

    Code artifact hashes remain the existing module contract. These checks do
    not authenticate original execution or claim to re-prove generated code.
    """
    from .capture import U64
    from .emitter import NATIVE
    from .observations import MAX_PROFILE_BYTES, load_observation_profile_details, _profile_accounting

    _table(entry, {'path', 'sha256'}, name='module.observation_profile')
    if not isinstance(entry['path'], str) or not entry['path']:
        raise ValueError('Invalid module.observation_profile path')
    path = (base / entry['path']).resolve()
    expected_digest = _digest(entry['sha256'], 'module.observation_profile')
    if not path.is_file():
        raise ValueError('module.observation_profile SHA256 mismatch or missing file')
    if path.stat().st_size > MAX_PROFILE_BYTES:
        raise ValueError('Observation profile exceeds 128 MiB')
    profile, digest, instructions, provenance = load_observation_profile_details(path)
    if digest != expected_digest:
        raise ValueError('module.observation_profile SHA256 mismatch or changed during verification')
    if (manifest.get('execution_evidence') is not False
            or any(key.startswith(('capture_', 'captured_')) for key in manifest)
            or {'code_capture_sha256', 'checkpoint_origin', 'execution_window'} & manifest.keys()
            or any(key.startswith('observation_history_') for key in manifest)):
        raise ValueError('Bound observation profile cannot declare capture execution evidence')

    def exact(key, expected):
        # Serialized equality preserves strict nested numeric types, unlike ==.
        actual = json.dumps(manifest.get(key), sort_keys=True, separators=(',', ':'), allow_nan=False)
        wanted = json.dumps(expected, sort_keys=True, separators=(',', ':'), allow_nan=False)
        if actual != wanted:
            raise ValueError('Module observation profile disagrees with '+key)

    for key, value in {
        'observation_profile_sha256': digest,
        'observation_profile_format': profile['format'],
        'observation_profile_schema': profile['schema'],
        'observation_inputs': provenance,
        **_profile_accounting(profile),
    }.items():
        exact(key, value)
    if profile['schema'] == 1 and any(key in manifest for key in (
            'selection_stages', 'selected_historical_totals', 'selection_counts', 'selection_policy')):
        raise ValueError('Version 1 profile cannot declare additive selection accounting')
    spans = manifest.get('excluded_physical_ranges')
    if not isinstance(spans, list) or len(spans) > 256:
        raise ValueError('Module profile exclusions require at most 256 ranges')
    exclusions = []
    for span in spans:
        _table(span, {'start', 'length'}, name='module profile exclusion')
        start = _integer(span['start'], 0, 0x1fffff, 'excluded physical start')
        length = _integer(span['length'], 1, 0x200000-start, 'excluded physical length')
        exclusions.append((start, length))
    if exclusions != sorted(set(exclusions)):
        raise ValueError('Module profile exclusions require canonical sorted unique ranges')
    selected, excluded = [], []
    for ins in instructions:
        remove = any(start <= address < start+length
                     for address in ins['physical'] for start, length in exclusions)
        (excluded if remove else selected).append(ins)
    native = [ins for ins in selected if ins['data'][0] in NATIVE]
    counts = {
        'observed_instructions': len(instructions),
        'native_instructions_emitted': len(native),
        'native_contexts': len({ins['mpr'] for ins in native}),
        'excluded_observations': len(excluded),
        'excluded_retired_hits': sum(ins['native_hits']+ins['interpreted_hits'] for ins in excluded),
        'unsupported_observations': len(selected)-len(native),
    }
    for key, value in counts.items():
        _integer(manifest.get(key), 0, U64, 'module profile '+key)
        exact(key, value)
    files['module_observation_profile'] = path


def _module_observation_history(base, entry, files, manifest):
    """Bind the complete authenticated history graph, not only its index.

    The module declares a selection from historical observations. This does
    not attest the producer or convert historical hits into executed work.
    """
    from .capture import U64
    from .isa import NATIVE
    from .history import load_history

    _table(entry, {'path', 'sha256'}, name='module.observation_history')
    if type(entry['path']) is not str or not entry['path']:
        raise ValueError('Invalid module.observation_history path')
    path = base / entry['path']
    admitted = load_history(path)
    if admitted.index_sha256 != _digest(entry['sha256'], 'module.observation_history'):
        raise ValueError('module.observation_history SHA256 mismatch')
    if (manifest.get('execution_evidence') is not False
            or any(key.startswith(('capture_', 'captured_', 'observation_profile_')) for key in manifest)
            or {'code_capture_sha256', 'checkpoint_origin', 'execution_window'} & manifest.keys()):
        raise ValueError('Bound observation history cannot declare capture/profile execution evidence')

    def exact(key, value):
        actual = json.dumps(manifest.get(key), sort_keys=True, separators=(',', ':'), allow_nan=False)
        expected = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
        if actual != expected:
            raise ValueError('Module observation history disagrees with '+key)

    for key, value in dict(observation_history_sha256=admitted.index_sha256,
            observation_history_format=admitted.index['format'], observation_history_schema=admitted.index['schema'],
            observation_inputs=admitted.input_metadata, **admitted.accounting).items():
        exact(key, value)
    spans = manifest.get('excluded_physical_ranges')
    if type(spans) is not list or len(spans) > 256:
        raise ValueError('Module history exclusions require at most 256 ranges')
    exclusions = []
    for span in spans:
        _table(span, {'start', 'length'}, name='module history exclusion')
        start = _integer(span['start'], 0, 0x1fffff, 'excluded physical start')
        length = _integer(span['length'], 1, 0x200000-start, 'excluded physical length')
        exclusions.append((start, length))
    if exclusions != sorted(set(exclusions)):
        raise ValueError('Module history exclusions require canonical sorted unique ranges')
    instructions = admitted.instructions
    selected, excluded = [], []
    for ins in instructions:
        remove = any(start <= address < start+length
                     for address in ins['physical'] for start, length in exclusions)
        (excluded if remove else selected).append(ins)
    native = [ins for ins in selected if ins['data'][0] in NATIVE]
    counts = dict(observed_instructions=len(instructions),
        native_instructions_emitted=len(native), native_contexts=len({tuple(ins['mpr']) for ins in native}),
        excluded_observations=len(excluded),
        excluded_retired_hits=sum(ins['native_hits']+ins['interpreted_hits'] for ins in excluded),
        unsupported_observations=len(selected)-len(native))
    for key, value in counts.items():
        _integer(manifest.get(key), 0, U64, 'module history '+key)
        exact(key, value)
    files['module_observation_history'] = admitted.index_path
    for relative, artifact in admitted.artifact_bindings.items():
        if relative != 'history.json':
            files['module_history:'+relative] = artifact['path']
    admitted.revalidate()
    return admitted


def _declared_cartridge_source(card):
    """Exact raw-image conversion contract shared by prepare and verify."""
    return dict(image_sha256=card.raw_sha256, decoded_rom_sha256=card.decoded_sha256,
                profile=card.profile, header=card.header, encoding=card.encoding,
                file_bytes=card.path.stat().st_size, rom_bytes=len(card.rom))


def _module_declared_roots(base, module, files, manifest, boot, card):
    from .declarations import load_compilation
    from .isa import NATIVE

    entry = _table(module['declared_roots'], {'path', 'sha256'}, name='module.declared_roots')
    if type(entry['path']) is not str or not entry['path']:
        raise ValueError('Invalid module.declared_roots path')
    history_path = None
    if 'observation_history' in module:
        history = _table(module['observation_history'], {'path', 'sha256'}, name='module.observation_history')
        if type(history['path']) is not str or not history['path']:
            raise ValueError('Invalid module.observation_history path')
        history_path = base/history['path']
    admitted = load_compilation(base/entry['path'], card.path, observation_history=history_path)
    if admitted.declarations.sha256 != _digest(entry['sha256'], 'module.declared_roots'):
        raise ValueError('module.declared_roots SHA256 mismatch')
    if admitted.declarations.source_metadata != _declared_cartridge_source(card):
        raise ValueError('Declared roots image/profile/header/encoding disagrees with HuCard boot')
    if (manifest.get('execution_evidence') is not False
            or any(key.startswith(('capture_', 'captured_', 'observation_profile_')) for key in manifest)
            or {'code_capture_sha256', 'checkpoint_origin', 'execution_window'} & manifest.keys()):
        raise ValueError('Declared roots cannot declare capture/profile execution evidence')
    spans = manifest.get('excluded_physical_ranges')
    if type(spans) is not list or len(spans) > 256:
        raise ValueError('Declared module exclusions require at most 256 ranges')
    exclusions = []
    for span in spans:
        _table(span,{'start','length'},name='declared module exclusion')
        exclusions.append((span['start'],span['length']))
    selection = admitted.selection(exclusions)
    native = [item for item in selection['instructions'] if item['data'][0] in NATIVE]
    expected_fields = {**admitted.provenance, **admitted.accounting, **selection['counts'],
        'excluded_physical_ranges':selection['exclusions'],
        'native_instructions_emitted':len(native),
        'native_contexts':len({tuple(item['mpr']) for item in native})}
    for key, expected in expected_fields.items():
        actual = json.dumps(manifest.get(key),sort_keys=True,separators=(',', ':'),allow_nan=False)
        if actual != json.dumps(expected,sort_keys=True,separators=(',', ':'),allow_nan=False):
            raise ValueError('Declared module disagrees with '+key)
    files['module_declared_roots'] = admitted.declarations.path
    # The image remains a fixed cartridge asset, never a mutable module input.
    if admitted.history is not None:
        if admitted.history.index_sha256 != _digest(module['observation_history']['sha256'], 'module.observation_history'):
            raise ValueError('module.observation_history SHA256 mismatch')
        files['module_observation_history'] = admitted.history.index_path
        files.update({'module_history:'+relative:artifact['path']
                      for relative,artifact in admitted.history.artifact_bindings.items() if relative != 'history.json'})
    elif (any(key.startswith('observation_history_') for key in manifest)
          or {'observation_inputs', 'historical_totals', 'historical_count_policy', 'selection_stages',
              'selected_historical_totals', 'selection_counts', 'selection_policy'} & manifest.keys()):
        raise ValueError('Pure declared roots cannot invent an observation history')
    admitted.revalidate()
    return admitted


def _module_discovery(base, module, files, declarations, card):
    from .discovery import load_discovery, REPORT_NAME
    binding = _table(module['discovery'], {'path', 'sha256'}, name='module.discovery')
    if type(binding['path']) is not str or not binding['path']:
        raise ValueError('Invalid module.discovery path')
    admitted = load_discovery(base/binding['path'], card.path)
    if admitted.sha256 != _digest(binding['sha256'], 'module.discovery'):
        raise ValueError('module.discovery SHA256 mismatch')
    if admitted.declarations.sha256 != declarations.declarations.sha256:
        raise ValueError('Discovery expanded roots differ from compiled declarations')
    files['module_discovery'] = admitted.report_path
    files.update({'module_discovery:'+name: item['path']
                  for name,item in admitted.artifact_bindings.items()
                  if name not in (REPORT_NAME, 'source_image')})
    admitted.revalidate()
    return admitted


def verify(descriptor: Path, *, allow_revision_override=False) -> dict:
    descriptor = descriptor.resolve()
    config = tomllib.loads(descriptor.read_text(encoding="utf-8"))
    _table(config, {"schema", "name", "tool", "module", "runtime", "limits"}, ASSETS | {"payload", "boot"}, "project")
    if ("boot" in config) == ("payload" in config):
        raise ValueError("Exactly one of payload or reset boot is required")
    reset_boot = "boot" in config
    hucard_boot = False
    if reset_boot:
        from .cartridge import HEADERS, ENCODINGS, PROFILES
        candidate = config['boot']
        hucard_boot = isinstance(candidate, dict) and candidate.get('mode') == 'hucard-reset'
        if hucard_boot:
            boot = _table(candidate, {'mode', 'profile', 'header', 'encoding'}, name='boot')
            _choice(boot['profile'], PROFILES, 'boot.profile')
            _choice(boot['header'], HEADERS, 'boot.header')
            _choice(boot['encoding'], ENCODINGS, 'boot.encoding')
            if 'cartridge' not in config or {'bios', 'bram', 'toc', 'disc', 'libchdr'} & config.keys():
                raise ValueError('HuCard boot requires cartridge and excludes CD/BIOS/BRAM assets')
        else:
            boot = _table(candidate, {"mode", "profile"}, optional={"arcade_card"}, name="boot")
            _choice(boot["mode"], ("system-card-reset",), "boot.mode")
            _choice(boot["profile"], ("standard", "super"), "boot.profile")
            if "arcade_card" in boot:
                _choice(boot["arcade_card"], ("duo",), "boot.arcade_card")
                if boot["profile"] != "super":
                    raise ValueError("Arcade Card Duo requires Super System Card reset boot")
            if "bios" not in config:
                raise ValueError("System Card reset boot requires hashed bios")
    if not hucard_boot and 'cartridge' in config:
        raise ValueError('Cartridge requires an explicit HuCard reset recipe')
    if type(config["schema"]) is not int or config["schema"] != 1:
        raise ValueError("Expected consumer schema = 1")
    if not isinstance(config["name"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", config["name"]):
        raise ValueError("Invalid consumer name")
    base = descriptor.parent
    tool = _table(config["tool"], {"path", "revision", "source_sha256", "runtime_abi"}, name="tool")
    if not isinstance(tool["path"], str) or not tool["path"]:
        raise ValueError("Invalid tool path")
    if not isinstance(tool["revision"], str) or re.fullmatch("[0-9a-f]{40}", tool["revision"]) is None:
        raise ValueError("tool.revision must be a complete Git commit")
    if type(tool["runtime_abi"]) is not int or tool["runtime_abi"] != ABI:
        raise ValueError("Unsupported runtime ABI")
    tool_root = (base / tool["path"]).resolve()
    identity = source_identity(tool_root)
    if identity["source_sha256"] != _digest(tool["source_sha256"], "tool.source_sha256"):
        raise ValueError("Tool source digest mismatch (including dirty or untracked source)")
    if identity["revision"] != tool["revision"] and not allow_revision_override:
        raise ValueError("Tool revision mismatch/unavailable; explicit --allow-revision-override still requires exact source digest")
    header = (tool_root / "runtime/include/pce/runtime.hpp").read_text(encoding="utf-8")
    if re.search(rf"\babi_version\s*=\s*{ABI}\s*;", header) is None:
        raise ValueError("Tool source ABI mismatch")
    module = _table(config["module"], {"source", "manifest"}, {'observation_profile', 'observation_history', 'declared_roots', 'discovery'}, name="module")
    if 'discovery' in module and 'declared_roots' not in module:
        raise ValueError('Discovery requires its complete declared_roots binding')
    if {'observation_profile', 'observation_history'} <= module.keys():
        raise ValueError('Module observation profile and history bindings are mutually exclusive')
    if 'declared_roots' in module and ('observation_profile' in module or not hucard_boot):
        raise ValueError('Declared roots require HuCard reset and only an optional observation history')
    files = {"module_source": _file(base, module["source"], "module.source"),
             "module_manifest": _file(base, module["manifest"], "module.manifest")}
    manifest = _module_manifest(files['module_manifest'])
    if (not isinstance(manifest, dict) or type(manifest.get("schema")) is not int or manifest["schema"] != 1
            or type(manifest.get("runtime_abi")) is not int or manifest["runtime_abi"] != ABI):
        raise ValueError("Module schema/runtime ABI mismatch")
    maximum_sites = (1048576 if manifest.get('observation_history_schema') == 2
                     or manifest.get('capture_schema') == 2 or 'declared_roots_sha256' in manifest else 1000000)
    _integer(manifest.get("native_instructions_emitted"), 1, maximum_sites, "native_instructions_emitted")
    if ('observation_history_sha256' in manifest) != ('observation_history' in module):
        raise ValueError('History modules require their complete observation_history binding')
    if ('declared_roots_sha256' in manifest) != ('declared_roots' in module):
        raise ValueError('Declared modules require their complete declared_roots binding')
    _module_artifacts(files, manifest)
    if 'bus_trace' in manifest:
        trace = _table(manifest['bus_trace'], {'schema', 'profile', 'code_fetch'}, name='module.bus_trace')
        if (type(trace['schema']) is not int or trace['schema'] != 1
                or trace['profile'] != 'software-access-callback-v1'
                or trace['code_fetch'] != 'separate-v1'):
            raise ValueError('Unsupported bus trace module contract')
    if 'observation_profile' in module:
        _module_observation_profile(base, module['observation_profile'], files, manifest)
    admitted_history = None
    if 'observation_history' in module and 'declared_roots' not in module:
        admitted_history = _module_observation_history(base, module['observation_history'], files, manifest)
    admitted_declarations = None
    admitted_discovery = None
    if 'native_span' in manifest:
        span = _table(manifest['native_span'], {'schema', 'protocol'}, name='module.native_span')
        if (type(span['schema']) is not int or span['schema'] != 1
                or span['protocol'] != 'per_instruction_v1'
                or manifest.get('partition_layout') != 'stable'
                or manifest.get('partition_identity') != 'full_mpr_logical_pc_range_v1'
                or type(manifest.get('pc_bucket_size')) is not int or manifest['pc_bucket_size'] != 256):
            raise ValueError('Unsupported native span module contract')
    if not reset_boot:
        payload = _table(config["payload"], {"path", "sha256", "physical_load", "pc", "mpr"}, name="payload")
        files["payload"] = _file(base, {k: payload[k] for k in ("path", "sha256")}, "payload")
        load = _integer(payload["physical_load"], 0, 0x1fffff, "physical_load")
        _integer(payload["pc"], 0, 65535, "pc")
        if not isinstance(payload["mpr"], list) or len(payload["mpr"]) != 8:
            raise ValueError("mpr requires all eight bytes")
        for item in payload["mpr"]:
            _integer(item, 0, 255, "mpr byte")
        size = files["payload"].stat().st_size
        if not size or load + size > 0x200000 or any(bank not in {*range(0x80, 0x88), 0xf8}
                for bank in range(load >> 13, ((load + size - 1) >> 13) + 1)):
            raise ValueError("Payload must fit standard CD/work RAM")
    runtime = _table(config["runtime"], {"tier", "video", "cd_unknown_status", "joypad", "region", "multitap"}, optional={"audio", "audio_profile", "audio_rate", "audio_timing", "vdc_access", "native_span", "cd_timing", "cd_subchannel"}, name="runtime")
    if 'native_span' in runtime:
        _integer(runtime['native_span'], 1, 256, 'native_span')
        if runtime['native_span'] > 1 and 'native_span' not in manifest:
            raise ValueError('native_span > 1 requires an opted-in generated module')
    if hucard_boot and runtime['cd_unknown_status'] != 'fault':
        raise ValueError('HuCard has no CD unknown-command response profile')
    if 'cd_timing' in runtime:
        _choice(runtime['cd_timing'], ('fixed', 'gear-distance'), 'cd_timing')
        if hucard_boot and runtime['cd_timing'] != 'fixed':
            raise ValueError('HuCard has no distance-aware CD timing profile')
    if 'cd_subchannel' in runtime:
        _choice(runtime['cd_subchannel'], ('synthesized', 'captured-q'), 'cd_subchannel')
        if runtime['cd_subchannel'] == 'captured-q' and (hucard_boot or 'disc' not in config):
            raise ValueError('captured-q requires an explicit CD disc provider')
    for key, values in (("tier", ("native", "hybrid")), ("video", ("snapshot", "continuous")),
                        ("cd_unknown_status", ("fault", "gear-good", "nec-invalid")), ("joypad", (2, 6)),
                        ("region", ("usa", "japan")), ("multitap", ("off", "on"))):
        _choice(runtime[key], values, key)
    if type(runtime["joypad"]) is not int:
        raise ValueError("joypad requires integer 2 or 6")
    if "vdc_access" in runtime:
        _choice(runtime["vdc_access"], ("queued", "immediate"), "vdc_access")
        if not (reset_boot or "bios" in config or runtime["video"] == "continuous"):
            raise ValueError("vdc_access requires an enabled clocked VDC profile")
    if "audio" in runtime:
        _choice(runtime["audio"], ("on", "off"), "audio")
    if {"audio_profile", "audio_rate", "audio_timing"} & runtime.keys():
        if runtime.get("audio") != "on":
            raise ValueError("audio_profile, audio_rate and audio_timing require explicit audio = on")
        if "audio_timing" in runtime:
            _choice(runtime["audio_timing"], ("gear", "legacy"), "audio_timing")
        if "audio_profile" in runtime:
            _choice(runtime["audio_profile"], ("raw", "filtered"), "audio_profile")
        if "audio_rate" in runtime:
            if type(runtime["audio_rate"]) is not int or runtime["audio_rate"] not in (44100, 48000):
                raise ValueError("audio_rate requires integer 44100 or 48000")
        if runtime.get("audio_profile", "raw") == "raw" and runtime.get("audio_rate", 44100) != 44100:
            raise ValueError("raw audio requires audio_rate = 44100")
    limits = _table(config["limits"], {"steps", "ticks", "wall_seconds"}, name="limits")
    _integer(limits["steps"], 1, 20000000000, "steps")
    _integer(limits["ticks"], 1, 2**64 - 1, "ticks")
    _integer(limits["wall_seconds"], 1, MAX_WALL_SECONDS, "wall_seconds")
    cue_disc = None
    for name in ASSETS & config.keys():
        entry = config[name]
        if name == "disc" and isinstance(entry, dict) and isinstance(entry.get("path"), str) and Path(entry["path"]).suffix.lower() == ".cue":
            from .cue import Cue
            _table(entry, {"path", "sha256"}, name="disc")
            disc = Cue(base / entry["path"])
            if disc.image_sha256() != _digest(entry["sha256"], "disc"):
                raise ValueError("disc complete BIN/CUE image SHA256 mismatch")
            # FILE names are relative to the declared CUE location. Passing
            # its symlink's resolved target could silently select other BINs.
            files[name] = disc.declared_path
            files.update({f"disc_component:{name}": path for name, path in disc.referenced_files.items()})
            cue_disc = disc
        else:
            files[name] = _file(base, entry, name)
    for name, expected_size in (("bios", 262144), ("bram", 2048)):
        if name in files and files[name].stat().st_size != expected_size:
            raise ValueError(f"{name} requires exactly {expected_size} bytes")
    if "libchdr" in files and "disc" not in files:
        raise ValueError("libchdr requires disc")
    if hucard_boot:
        from .cartridge import Cartridge
        card = Cartridge(files['cartridge'], boot['header'], boot['encoding'], boot['profile'])
        if card.raw_sha256 != config['cartridge']['sha256']:
            raise ValueError('Cartridge changed during verification')
        if 'declared_roots' in module:
            admitted_declarations = _module_declared_roots(base,module,files,manifest,boot,card)
        if 'discovery' in module:
            admitted_discovery = _module_discovery(base,module,files,admitted_declarations,card)
    identities = {name: sha256(path) for name, path in sorted(files.items())}
    if ('observation_profile' in module
            and identities['module_observation_profile'] != module['observation_profile']['sha256']):
        raise ValueError('module.observation_profile changed during input binding')
    descriptor_hash = sha256(descriptor)
    if cue_disc is not None:
        cue_disc.check_unchanged()
    if hucard_boot:
        card.check_unchanged()
        if identities['cartridge'] != config['cartridge']['sha256']:
            raise ValueError('Cartridge changed during input binding')
    if admitted_history is not None:
        admitted_history.revalidate()
    if admitted_declarations is not None:
        admitted_declarations.revalidate()
    if admitted_discovery is not None:
        admitted_discovery.revalidate()
    return {"descriptor": descriptor, "config": config, "tool_root": tool_root,
            "tool_identity": identity, "revision_override": identity["revision"] != tool["revision"],
            "files": files, "identities": identities, "descriptor_sha256": descriptor_hash}


def _binding(project):
    return {"descriptor_sha256": project["descriptor_sha256"],
            "tool": project["tool_identity"], "files": project["identities"],
            "revision_override": project["revision_override"]}


def _write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def _cmake_path(path):
    text = path.as_posix()
    if any(c in text for c in '\n\r";$'):
        raise ValueError("Path cannot be represented safely in generated CMake")
    return '"' + text + '"'


def build(descriptor: Path, build_dir: Path, *, allow_revision_override=False,
          generator=None, desktop=False, cmake_args=(), cache_root=None,
          cache_toolchain_root=None, cache_dependency_roots=(), recoverable=False,
          recovery_toolchain_root=None, recovery_dependency_roots=()) -> dict:
    if type(recoverable) is not bool:
        raise ValueError('recoverable must be boolean')
    if recoverable:
        if cache_root is not None or cache_toolchain_root is not None or cache_dependency_roots:
            raise ValueError('Recoverable builds and package-cache builds are separate producers')
        for argument in cmake_args:
            if not isinstance(argument, str) or not re.fullmatch(
                    r'-D(CMAKE_CXX_COMPILER|CMAKE_MAKE_PROGRAM|SDL3_DIR)=[^\r\n\x00]+', argument):
                raise ValueError('Unsupported recovery CMake argument')
        from .build_recovery import build as recovery_build
        return recovery_build(descriptor, build_dir, allow_revision_override=allow_revision_override,
            generator=generator, desktop=desktop, cmake_args=cmake_args,
            toolchain_root=recovery_toolchain_root, dependency_roots=recovery_dependency_roots)
    if recovery_toolchain_root is not None or recovery_dependency_roots:
        raise ValueError('Recovery input roots require --recoverable')
    project = verify(descriptor, allow_revision_override=allow_revision_override)
    build_dir = build_dir.resolve()
    if build_dir.exists():
        raise ValueError("Build directory exists; choose a new directory")
    if type(desktop) is not bool:
        raise ValueError("desktop must be boolean")
    if desktop and project["config"]["runtime"]["video"] != "continuous":
        raise ValueError("Desktop requires continuous video")
    # Additional CMake options are intentionally only toolchain/package paths.
    for argument in cmake_args:
        if not isinstance(argument, str) or not re.fullmatch(r"-D(CMAKE_CXX_COMPILER|CMAKE_MAKE_PROGRAM|SDL3_DIR|CMAKE_TOOLCHAIN_FILE)=[^\r\n]+", argument):
            raise ValueError("Unsupported extra CMake argument")
    if cache_root is None and (cache_toolchain_root is not None or cache_dependency_roots):
        raise ValueError('Cache input roots require --cache-root')
    if cache_root is not None:
        return _cached_build(project, build_dir, allow_revision_override=allow_revision_override,
            generator=generator, desktop=desktop, cmake_args=cmake_args, cache_root=cache_root,
            cache_toolchain_root=cache_toolchain_root, cache_dependency_roots=cache_dependency_roots)
    return _compile_build(project, build_dir, allow_revision_override=allow_revision_override,
                          generator=generator, desktop=desktop, cmake_args=cmake_args)


def resume(descriptor: Path, build_dir: Path, *, allow_revision_override=False) -> dict:
    """Resume only a pre-existing, verified recoverable-build contract."""
    from .build_recovery import build as recovery_build
    return recovery_build(descriptor, build_dir, resume=True,
                          allow_revision_override=allow_revision_override)


def _compile_build(project, build_dir, *, allow_revision_override, generator, desktop,
                   cmake_args, cache_context=None):
    commands = _configure_build(project, build_dir, generator=generator, desktop=desktop,
                                cmake_args=cmake_args, cache_context=cache_context)
    return _compile_configured(project, build_dir, allow_revision_override=allow_revision_override,
        desktop=desktop, commands=commands, cache_context=cache_context)


def _configure_build(project, build_dir, *, generator, desktop, cmake_args, cache_context=None):
    wrapper = build_dir / "source"
    wrapper.mkdir(parents=True)
    source = ["cmake_minimum_required(VERSION 3.20)", "project(PCEConsumer LANGUAGES CXX)",
              "set(BUILD_TESTING OFF CACHE BOOL \"\" FORCE)",
              "set(PCE_BUILD_TESTS OFF CACHE BOOL \"\" FORCE)",
              "set(PCE_BUILD_TOOLS OFF CACHE BOOL \"\" FORCE)",
              "set(PCE_BUILD_REFERENCE_PROBE OFF CACHE BOOL \"\" FORCE)",
              f"set(PCE_BUILD_DESKTOP {'ON' if desktop else 'OFF'} CACHE BOOL \"\" FORCE)",
              f"add_subdirectory({_cmake_path(project['tool_root'])} tool)",
              f"pce_add_consumer(pce-consumer MODULE {_cmake_path(project['files']['module_source'])} MANIFEST {_cmake_path(project['files']['module_manifest'])}{' DESKTOP' if desktop else ''})",
              'set_target_properties(pce-consumer PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin/$<0:>")', ""]
    if cache_context and desktop:
        source.append('file(GENERATE OUTPUT "${CMAKE_BINARY_DIR}/cache-sdl-runtime.txt" CONTENT "$<TARGET_PROPERTY:pce-desktop-host,PCE_DESKTOP_RUNTIME_DLL>")')
    (wrapper / "CMakeLists.txt").write_text("\n".join(source), encoding="utf-8")
    binary_dir = build_dir / "build"
    cmake = str(cache_context['tools']['cmake']) if cache_context else 'cmake'
    configure = [cmake, "-S", str(wrapper), "-B", str(binary_dir), "-DCMAKE_BUILD_TYPE=Release"]
    if generator:
        configure += ["-G", generator]
    configure += list(cmake_args)
    if cache_context:
        configure += ['-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF',
                      '-DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=OFF',
                      '-DCMAKE_FIND_USE_CMAKE_ENVIRONMENT_PATH=OFF',
                      '-DCMAKE_FIND_USE_SYSTEM_ENVIRONMENT_PATH=OFF']
        if cache_context.get('recovery'):
            configure.append('-DCMAKE_SUPPRESS_REGENERATION=ON')
        query = binary_dir/'.cmake/api/v1/query'
        query.mkdir(parents=True)
        for name in ('codemodel-v2', 'toolchains-v1', 'cmakeFiles-v1'):
            (query/name).touch()
    options = {'env':cache_context['environment']} if cache_context else {}
    runner = (cache_context or {}).get('runner', subprocess.run)
    runner(configure, check=True, shell=False, **options)
    return [configure]


def _compile_configured(project, build_dir, *, allow_revision_override, desktop, commands,
                        cache_context=None, runner=None):
    descriptor = project['descriptor']
    binary_dir = build_dir / 'build'
    cmake = str(cache_context['tools']['cmake']) if cache_context else 'cmake'
    compile_command = [cmake, "--build", str(binary_dir), "--config", "Release", "--target", "pce-consumer", "--parallel", "2"]
    options = {'env':cache_context['environment']} if cache_context else {}
    execute = runner or (cache_context or {}).get('runner', subprocess.run)
    execute(compile_command, check=True, shell=False, **options)
    # The build may have raced a source modification: refuse to bless it.
    after = verify(descriptor, allow_revision_override=allow_revision_override)
    if _binding(after) != _binding(project):
        raise ValueError("Source/input identity changed during build")
    binary = binary_dir / "bin" / ("pce-consumer.exe" if os.name == "nt" else "pce-consumer")
    dependencies = {p.name: sha256(p) for p in sorted(binary.parent.iterdir()) if p.is_file()}
    receipt = {"schema": 1, "kind": "pce-consumer-build", "binding": _binding(project),
               "binary": str(binary), "binary_sha256": sha256(binary), "desktop": desktop,
               "output_files": dependencies, "commands": commands + [compile_command],
               "execution_evidence": False}
    if cache_context is None:
        _write_new(build_dir / "build-receipt.json", receipt)
    return receipt


def _cached_build(project, build_dir, *, allow_revision_override, generator, desktop,
                  cmake_args, cache_root, cache_toolchain_root, cache_dependency_roots):
    from .build_cache import BuildCache, contract_identity
    from .build_inputs import prepare, verify_closure, configuration_identity
    started = time.monotonic()
    arguments = dict(generator=generator, desktop=desktop, cmake_args=cmake_args,
        toolchain_root=cache_toolchain_root, dependency_roots=cache_dependency_roots,
        build_dir=build_dir, cache_root=cache_root)
    context = prepare(project, **arguments)
    initial_contract = context['contract']
    commands = _configure_build(project, build_dir, generator=generator, desktop=desktop,
                                cmake_args=cmake_args, cache_context=context)
    configured = configuration_identity(context, build_dir/'build')
    context = dict(context, contract=dict(initial_contract, configured=configured))
    def unchanged():
        current = verify(project['descriptor'], allow_revision_override=allow_revision_override)
        if (_binding(current) != _binding(project)
                or prepare(current, **arguments)['contract'] != initial_contract
                or configuration_identity(context, build_dir/'build') != configured):
            raise ValueError('Cache source, module, SDK or toolchain changed during build/reuse')
    # Keep every audited field in the receipt, but bind large source graphs by
    # their complete canonical identity rather than duplicating them in each
    # bounded package manifest. No field is omitted from the digest.
    key_contract = contract_identity(context['contract'])
    with BuildCache(cache_root, key_contract) as cache:
        package = build_dir/'build/bin'
        package.parent.mkdir(parents=True, exist_ok=True)
        # CMake creates the output directory during generation. Restore is
        # create-new: only remove that empty directory, never its contents.
        if package.exists():
            package.rmdir()
        manifest = cache.restore(package)
        hit = manifest is not None
        audit = None
        if hit:
            unchanged()
            binary = package/'pce-consumer.exe'
            receipt = dict(schema=1, kind='pce-consumer-build', binding=_binding(project),
                binary=str(binary), binary_sha256=sha256(binary), desktop=desktop,
                output_files={p.name:sha256(p) for p in sorted(package.iterdir()) if p.is_file()},
                commands=commands, execution_evidence=False)
        else:
            receipt = _compile_configured(project, build_dir, allow_revision_override=allow_revision_override,
                desktop=desktop, commands=commands, cache_context=context)
            audit = verify_closure(context, build_dir/'build')
            unchanged()
            manifest = cache.publish(package)
        manifest_path = cache.entry/'manifest.json'
        receipt['cache'] = dict(schema=1, hit=hit, key=cache.key,
            producer=context['contract']['producer'], manifest_sha256=sha256(manifest_path),
            manifest=dict(path=str(manifest_path), sha256=sha256(manifest_path), bytes=manifest_path.stat().st_size),
            input_contract=context['contract'], key_contract=key_contract, input_audit=audit,
            elapsed_seconds=time.monotonic()-started,
            scope='Verified exact binary-package reuse only; no cached execution receipt or native-coverage promotion')
        _write_new(build_dir/'build-receipt.json', receipt)
        return receipt


def checkpoint_context(project: dict, *, reference_enabled=False) -> str:
    """Exact reviewed source/input/profile recipe, independent of run limits."""
    if type(reference_enabled) is not bool:
        raise ValueError('reference_enabled requires a boolean')
    config = project['config']
    recipe = {'schema': 1, 'kind': 'pce-developer-checkpoint-context',
              'tool': {'revision': project['tool_identity']['revision'],
                       'source_sha256': project['tool_identity']['source_sha256'],
                       'runtime_abi': config['tool']['runtime_abi']},
              'inputs': project['identities'], 'runtime': config['runtime']}
    if 'boot' in config:
        recipe['boot'] = config['boot']
    else:
        recipe['payload'] = {key: value for key, value in config['payload'].items() if key not in {'path', 'sha256'}}
    if reference_enabled:
        recipe['reference_capability'] = 'pce-reference-capability-v1'
    return hashlib.sha256(json.dumps(recipe, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _checkpoint_name(name):
    if (not isinstance(name, str) or not 1 <= len(name) <= 96 or '..' in name or not name.endswith('.pcec')
            or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name) is None
            or name.split('.', 1)[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
                *(f'COM{i}' for i in range(10)), *(f'LPT{i}' for i in range(10))}):
        raise ValueError('checkpoint_load requires a portable direct basename')
    return name


def command_for(project: dict, binary: Path, *, dev_port=None, start_paused=False, memory_write=False,
                code_capture=None, capture_limit=None, capture_profile='legacy', checkpoint_dir=None, checkpoint_load=None,
                reference_enabled=False, bus_trace=None, bus_trace_calls=None, bus_trace_events=None):
    config, files = project["config"], project["files"]
    limits, runtime = config["limits"], config["runtime"]
    if type(start_paused) is not bool or type(memory_write) is not bool:
        raise ValueError('start_paused and memory_write require booleans')
    if start_paused and dev_port is None:
        raise ValueError('start_paused requires TCP startup')
    if type(reference_enabled) is not bool:
        raise ValueError('reference_enabled requires a boolean')
    if reference_enabled and (dev_port is None or not start_paused or runtime['video'] != 'continuous'):
        raise ValueError('reference_enabled requires continuous paused TCP startup')
    if "boot" in config:
        if config['boot']['mode'] == 'hucard-reset':
            command = [str(binary), '--hucard-reset', config['boot']['profile'], str(files['cartridge']),
                       str(limits['steps']), str(limits['ticks']), runtime['tier'],
                       '--rom-header', config['boot']['header'], '--rom-encoding', config['boot']['encoding']]
        else:
            command = [str(binary), "--system-card-reset", config["boot"]["profile"], str(files["bios"]),
                       str(limits["steps"]), str(limits["ticks"]), runtime["tier"]]
            if "arcade_card" in config["boot"]:
                command += ["--arcade-card", config["boot"]["arcade_card"]]
    else:
        payload = config["payload"]
        command = [str(binary), str(files["payload"]), str(payload["physical_load"]), str(payload["pc"]),
                   ",".join(map(str, payload["mpr"])), str(limits["steps"]), str(limits["ticks"]), runtime["tier"]]
    for key, flag in (("video", "video-output"), ("cd_unknown_status", "cd-unknown-status"),
                      ("joypad", "joypad"), ("region", "joypad-region"), ("multitap", "multitap")):
        command += ["--" + flag, str(runtime[key])]
    command += ["--wall-seconds", str(limits["wall_seconds"])]
    if "audio" in runtime:
        command += ["--audio-output", runtime["audio"]]
    for field, flag in (("audio_profile", "audio-profile"), ("audio_rate", "audio-rate"), ("audio_timing", "audio-timing"), ("vdc_access", "vdc-access"), ("native_span", "native-span"), ("cd_timing", "cd-timing"), ("cd_subchannel", "cd-subchannel")):
        if field in runtime:
            command += ["--" + flag, str(runtime[field])]
    for name in sorted(ASSETS & files.keys()):
        if name == 'cartridge':
            continue
        if name == "bios" and "boot" in config:
            continue
        command += ["--" + name.replace("_", "-"), str(files[name])]
    if dev_port is not None:
        _integer(dev_port, 0, 65535, "dev_port")
        if runtime["video"] != "continuous":
            raise ValueError("TCP requires continuous video")
        command += ["--dev-port", str(dev_port), "--dev-start-paused", "on" if start_paused else "off",
                    "--dev-memory-write", "on" if memory_write else "off"]
    elif start_paused or memory_write:
        raise ValueError("Pause/memory writes require --dev-port")
    if reference_enabled:
        command += ['--dev-reference', 'on']
    _choice(capture_profile, ('legacy', 'extended'), 'capture_profile')
    if code_capture is not None:
        command += ["--code-capture", str(Path(code_capture).resolve())]
        if capture_profile == 'extended':
            command += ['--capture-profile', 'extended']
        if capture_limit is not None:
            _integer(capture_limit, 1, 1048576 if capture_profile == 'extended' else 65536, "capture_limit")
            command += ["--capture-limit", str(capture_limit)]
    elif capture_limit is not None:
        raise ValueError("capture_limit requires code_capture")
    elif capture_profile != 'legacy':
        raise ValueError('capture_profile requires code_capture')
    if bus_trace is not None:
        if _module_manifest(files['module_manifest']).get('bus_trace') != {'schema': 1, 'profile': 'software-access-callback-v1', 'code_fetch': 'separate-v1'}:
            raise ValueError('Bus tracing requires a regenerated separate-v1 module')
        if runtime.get('native_span', 1) != 1:
            raise ValueError('Bus tracing requires scalar native_span = 1')
        calls = 256 if bus_trace_calls is None else bus_trace_calls
        events = 60000 if bus_trace_events is None else bus_trace_events
        _integer(calls, 1, 10000, 'bus_trace_calls')
        _integer(events, 1, 60000, 'bus_trace_events')
        command += ['--bus-trace', str(Path(bus_trace).resolve()), '--bus-trace-calls', str(calls),
                    '--bus-trace-events', str(events), '--bus-trace-context',
                    checkpoint_context(project, reference_enabled=reference_enabled),
                    '--bus-trace-source', project['tool_identity']['source_sha256'],
                    '--bus-trace-revision', project['tool_identity']['revision']]
    elif bus_trace_calls is not None or bus_trace_events is not None:
        raise ValueError('Bus trace bounds require bus_trace')
    if checkpoint_dir is not None:
        directory = Path(checkpoint_dir).absolute()
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError('checkpoint_dir requires an existing private directory without a symlink')
        if dev_port is None or not start_paused:
            raise ValueError('Developer checkpoints require paused TCP startup')
        command += ['--checkpoint-dir', str(directory), '--checkpoint-context',
                    checkpoint_context(project, reference_enabled=reference_enabled)]
        if checkpoint_load is not None:
            command += ['--checkpoint-load', _checkpoint_name(checkpoint_load)]
    elif checkpoint_load is not None:
        raise ValueError('checkpoint_load requires checkpoint_dir')
    return command


def _verified_package(descriptor, build_dir, *, allow_revision_override=False):
    """Shared package admission for execution and caller-owned launch planning."""
    from .snapshots import SnapshotStore
    checked = verify(descriptor, allow_revision_override=allow_revision_override)
    store = SnapshotStore()
    snapshot = store.read_json(Path(build_dir) / 'build-receipt.json',
                               max_bytes=MAX_MODULE_MANIFEST_BYTES)
    built = snapshot.value
    if (type(built) is not dict or type(built.get('schema')) is not int
            or built['schema'] != 1 or built.get('kind') != 'pce-consumer-build'
            or json.dumps(built.get('binding'), sort_keys=True, allow_nan=False)
               != json.dumps(_binding(checked), sort_keys=True, allow_nan=False)):
        raise ValueError('Build receipt does not match verified consumer')
    if 'incremental' in built:
        from .incremental import validate_run
        validate_run(Path(build_dir), built)
    if type(built.get('binary')) is not str or not built['binary']:
        raise ValueError('Invalid build executable path')
    binary = Path(built['binary'])
    if sha256(binary) != built.get('binary_sha256'):
        raise ValueError('Built executable changed')
    outputs = {p.name: sha256(p) for p in sorted(binary.parent.iterdir()) if p.is_file()}
    if outputs != built.get('output_files'):
        raise ValueError('Build output/dependency identities changed')
    store.revalidate()
    return checked, built, binary, snapshot.sha256


def prepare_launch(descriptor: Path, build_dir: Path, *, allow_revision_override=False,
                   dev_port=None, start_paused=False, memory_write=False,
                   code_capture=None, capture_limit=None, capture_profile='legacy',
                   checkpoint_dir=None, checkpoint_load=None, reference_enabled=False,
                   bus_trace=None, bus_trace_calls=None, bus_trace_events=None):
    """Validate a built consumer and return argv without executing or reserving output.

    Callers own process lifetime, TCP evidence and execution qualification. The
    plan checks current content, not a filesystem lock or durable launch lease.
    """
    checked, built, binary, receipt_sha = _verified_package(descriptor, build_dir,
        allow_revision_override=allow_revision_override)
    destinations = {}
    for role, value, label in (('code_capture', code_capture, 'Code capture'),
                               ('bus_trace', bus_trace, 'Bus trace')):
        if value is None:
            continue
        path = Path(value).resolve()
        if path.exists() or path.is_symlink() or not path.parent.is_dir():
            raise ValueError(label + ' requires a new file in an existing directory')
        destinations[role] = path
    if len(set(destinations.values())) != len(destinations):
        raise ValueError('Code capture and bus trace require separate paths')
    command = command_for(checked, binary, dev_port=dev_port, start_paused=start_paused,
        memory_write=memory_write, code_capture=destinations.get('code_capture'), capture_limit=capture_limit,
        capture_profile=capture_profile, checkpoint_dir=checkpoint_dir, checkpoint_load=checkpoint_load,
        reference_enabled=reference_enabled, bus_trace=destinations.get('bus_trace'), bus_trace_calls=bus_trace_calls,
        bus_trace_events=bus_trace_events)
    # Metadata can change while command derivation performs its own I/O. Re-admit
    # the complete package rather than treating an earlier hash as a live lock.
    after, later, later_binary, later_sha = _verified_package(descriptor, build_dir,
        allow_revision_override=allow_revision_override)
    if (_binding(after) != _binding(checked) or later != built or later_binary != binary
            or later_sha != receipt_sha):
        raise ValueError('Consumer package changed during launch preparation')
    for path in destinations.values():
        if path.exists() or path.is_symlink() or not path.parent.is_dir():
            raise ValueError('Launch output changed during preparation')
    return dict(schema=1, kind='pce-consumer-launch-plan', executed=False,
        execution_evidence=False, binding=_binding(checked),
        build_receipt=dict(path=str(Path(build_dir).resolve() / 'build-receipt.json'), sha256=receipt_sha),
        binary=str(binary), binary_sha256=built['binary_sha256'], output_files=built['output_files'],
        command=command)


def _checkpoint_provenance(result, *, requested=False):
    value = result.get('checkpoint') if isinstance(result, dict) else None
    if value is None and not requested:
        return None
    try:
        if not isinstance(value, dict) or type(value.get('resumed')) is not bool:
            raise ValueError('Missing checkpoint execution origin')
        if not value['resumed']:
            if requested or set(value) != {'resumed'}:
                raise ValueError('Requested checkpoint did not resume')
            return {'valid': True, 'resumed': False}
        _table(value, {'resumed', 'origin', 'window'}, optional={'audio_origin'}, name='checkpoint execution')
        from .capture import validate_checkpoint_origin
        origin = validate_checkpoint_origin(value['origin'])
        window = _table(value['window'], {'ticks', 'native_steps', 'interpreter_steps'}, name='checkpoint execution window')
        for key in window:
            _integer(window[key], 0, 2**64-1, 'checkpoint window '+key)
            _integer(result.get(key), 0, 2**64-1, 'checkpoint lifetime '+key)
            if result[key] < origin[key] or result[key]-origin[key] != window[key]:
                raise ValueError('Checkpoint imported/window counters disagree with lifetime '+key)
        report = {'valid': True, 'resumed': True, 'origin': origin, 'window': dict(window)}
        if 'audio_origin' in value:
            audio = _table(value['audio_origin'], {'pending_pcm_frames', 'source_wav_frames'}, name='checkpoint audio origin')
            _integer(audio['pending_pcm_frames'], 0, 8192, 'checkpoint pending PCM frames')
            _integer(audio['source_wav_frames'], 0, 2**64-1, 'checkpoint source WAV frames')
            report['audio_origin'] = dict(audio)
        return report
    except (ValueError, TypeError, KeyError) as error:
        return {'valid': False, 'error': str(error)}


def _boot_provenance(project, result, *, bram_seeded=None):
    """Validate reported initial reset state, independently of final CPU state."""
    if "boot" not in project["config"]:
        return None
    try:
        boot = project['config']['boot']
        card = None
        if boot['mode'] == 'hucard-reset':
            from .cartridge import Cartridge
            card = Cartridge(project['files']['cartridge'], boot['header'], boot['encoding'], boot['profile'])
            if card.raw_sha256 != project['identities']['cartridge']:
                raise ValueError('Reset vector is not from the pinned cartridge')
            pc = card.reset_pc
        else:
            with project["files"]["bios"].open("rb") as stream:
                stream.seek(0x1FFE)
                vector = stream.read(2)
            if len(vector) != 2:
                raise ValueError("Reset vector is unavailable in the pinned BIOS")
            pc = vector[0] | (vector[1] << 8)
        expected = {"mode": boot['mode'], "profile": boot['profile'],
                    "initialization": "gear-deterministic-zero-v1", "vector_physical": 8190,
                    "pc": pc, "a": 0, "x": 0, "y": 0, "sp": 0, "p": 4,
                    "clock_divisor": 12, "ticks": 0, "cycles": 0, "mpr": [0] * 8}
        if card is not None:
            expected.update(header=boot['header'], encoding=boot['encoding'], rom_bytes=len(card.rom), cd=False)
            if boot['profile'] == 'sf2':
                expected['mapper_latch'] = 0
            elif boot['profile'] == 'populous':
                expected['cartridge_ram_bytes'] = 32768
        else:
            seeded = "bram" in project["files"] if bram_seeded is None else bram_seeded
            expected['bram'] = "explicit-image" if seeded else "blank-unformatted"
            if "arcade_card" in boot:
                expected['arcade_card'] = boot['arcade_card']
        reported = result.get("boot") if isinstance(result, dict) else None
        if not isinstance(reported, dict) or set(reported) != set(expected):
            raise ValueError("Reset boot metadata fields differ from the declared startup recipe")
        for key, value in expected.items():
            actual = reported[key]
            if type(actual) is not type(value) or actual != value:
                raise ValueError(f"Reset boot metadata mismatch: {key}")
            if key == "mpr" and any(type(item) is not int for item in actual):
                raise ValueError("Reset boot MPR metadata requires integer bytes")
        if card is not None:
            card.check_unchanged()
        return {"valid": True}
    except (ValueError, OSError) as error:
        return {"valid": False, "error": str(error)}


def _vdc_access_provenance(project, result):
    """Validate an explicitly selected access profile without guessing legacy output."""
    expected = project["config"]["runtime"].get("vdc_access")
    if expected is None:
        return None
    try:
        value = result.get("vdc_access") if isinstance(result, dict) else None
        _table(value, {"profile", "pending_read", "pending_write", "delay", "phase", "wait_ticks"}, name="vdc_access report")
        if value["profile"] != expected:
            raise ValueError("Reported VDC access profile differs from the declared runtime")
        if type(value["pending_read"]) is not bool or type(value["pending_write"]) is not bool:
            raise ValueError("Reported VDC pending flags must be boolean")
        _integer(value["delay"], 0, 2**64-1, "VDC transfer delay")
        _integer(value["phase"], 0, 2, "VDC transfer phase")
        _integer(value["wait_ticks"], 0, 2**64-1, "VDC wait ticks")
        if value["wait_ticks"] % 3:
            raise ValueError("VDC waits must be whole fast master cycles")
        if not value["pending_read"] and not value["pending_write"] and (value["delay"] or value["phase"]):
            raise ValueError("Idle VDC access state retains a transfer countdown")
        if expected == "immediate" and any(value[key] for key in ("pending_read", "pending_write", "delay", "phase", "wait_ticks")):
            raise ValueError("Immediate VDC access profile cannot retain queued accesses or wait ticks")
        return {"valid": True}
    except (ValueError, TypeError, KeyError) as error:
        return {"valid": False, "error": str(error)}


def _execution_policy_provenance(project, result, *, reference_enabled=False):
    value = result.get('execution_policy') if isinstance(result, dict) else None
    if not reference_enabled and (not isinstance(result, dict) or 'execution_policy' not in result):
        return None
    try:
        if not reference_enabled:
            raise ValueError('Execution policy requires explicit reference capability')
        _table(value, {'schema', 'reference_enabled', 'selected', 'configured_tier',
                       'effective_policy', 'effective_native_span'}, name='execution_policy')
        if (type(value['schema']) is not int or value['schema'] != 1
                or value['reference_enabled'] is not True or type(value['selected']) is not bool):
            raise ValueError('Unsupported execution policy report')
        runtime = project['config']['runtime']
        if value['configured_tier'] != runtime['tier']:
            raise ValueError('Execution policy configured tier differs from recipe')
        expected_policy = 'interpreter' if value['selected'] else runtime['tier']
        expected_span = 0 if value['selected'] else runtime.get('native_span', 1)
        _integer(value['effective_native_span'], 0, 256, 'effective_native_span')
        if value['effective_policy'] != expected_policy or value['effective_native_span'] != expected_span:
            raise ValueError('Inconsistent effective execution policy')
        if value['selected']:
            checkpoint = _checkpoint_provenance(result)
            if checkpoint is not None and not checkpoint['valid']:
                raise ValueError(checkpoint['error'])
            native = (checkpoint['window']['native_steps'] if checkpoint and checkpoint['resumed']
                      else result.get('native_steps'))
            if type(native) is not int or native != 0:
                raise ValueError('Interpreter reference window contains native retirements')
        return {'valid': True, **value}
    except (ValueError, KeyError, TypeError) as error:
        return {'valid': False, 'error': str(error)}


def _native_dispatch_provenance(project, result, *, reference_enabled=False):
    expected = project['config']['runtime'].get('native_span')
    if expected is None:
        return None
    try:
        value = result.get('native_dispatch') if isinstance(result, dict) else None
        fields = {'schema', 'protocol', 'supported', 'limit', 'batches', 'generated_calls',
                  'native_completed', 'interpreted_completed', 'local_continuations', 'max_completed'}
        _table(value, fields, name='native_dispatch report')
        if (type(value['schema']) is not int or value['schema'] != 1
                or value['protocol'] != 'per_instruction_v1'
                or type(value['supported']) is not bool):
            raise ValueError('Unsupported native dispatch report')
        manifest = json.loads(project['files']['module_manifest'].read_text(encoding='utf-8'))
        if value['supported'] != ('native_span' in manifest):
            raise ValueError('Reported native span support differs from the bound module')
        for key in fields - {'protocol', 'supported'}:
            _integer(value[key], 0, 2**64-1, 'native_dispatch.'+key)
        if value['limit'] != expected:
            raise ValueError('Reported native span limit differs from the declared runtime')
        policy = _execution_policy_provenance(project, result, reference_enabled=reference_enabled)
        if policy is not None and not policy['valid']:
            raise ValueError(policy['error'])
        if policy is not None and policy['selected']:
            if any(value[key] for key in ('batches', 'generated_calls', 'native_completed',
                                         'interpreted_completed', 'local_continuations', 'max_completed')):
                raise ValueError('Interpreter reference must bypass native span dispatch')
            return {'valid': True, **value}
        n, i = result.get('native_steps'), result.get('interpreter_steps')
        checkpoint = _checkpoint_provenance(result)
        if checkpoint is not None:
            if not checkpoint['valid']:
                raise ValueError(checkpoint['error'])
            if checkpoint['resumed']:
                n, i = (checkpoint['window'][key] for key in ('native_steps', 'interpreter_steps'))
        if type(n) is not int or type(i) is not int or n < 0 or i < 0:
            raise ValueError('Missing native dispatch retirement counters')
        total = n+i
        if value['native_completed'] != n or value['interpreted_completed'] != i:
            raise ValueError('Native dispatch completions differ from actual retired work')
        if (not (total+expected-1)//expected <= value['batches'] <= total+1
                or value['generated_calls'] > total+1
                or value['generated_calls'] < i
                or n and (not value['generated_calls'] or value['local_continuations'] >= n)
                or value['local_continuations'] > n
                or value['generated_calls'] < n-value['local_continuations']
                or not (1 if total else 0) <= value['max_completed'] <= (min(expected,total) if total else 0)
                or expected == 1 and value['local_continuations']):
            raise ValueError('Inconsistent native dispatch boundary accounting')
        return {'valid': True, **value}
    except (ValueError, OSError, KeyError, TypeError) as error:
        return {'valid': False, 'error': str(error)}


def save_identity(project, contract: str) -> str:
    """Stable save binding: exact media/firmware plus an explicit mod/save contract.

    Compiler revisions, ABI numbers and native coverage are intentionally absent.
    Changes to game modifications or save layout require a new caller contract.
    """
    _digest(contract, "save_contract")
    if "bram" in project["files"]:
        raise ValueError("Persistent sessions cannot also use a descriptor BRAM seed")
    boot = project["config"].get("boot")
    if boot is None or boot.get("mode") != "system-card-reset":
        raise ValueError("Consumer persistence requires explicit System Card reset boot")
    binding = {"schema": 1, "kind": "pce-bram-compatibility", "contract": contract,
               "boot": boot, "media": {key: value for key, value in project["identities"].items()
                       if key in {"bios", "disc", "toc"} or key.startswith("disc_component:")}}
    return hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def run(descriptor: Path, build_dir: Path, receipt_path: Path, *, allow_revision_override=False,
        dev_port=None, start_paused=False, memory_write=False, code_capture=None, capture_limit=None, capture_profile='legacy',
        save_root=None, save_namespace=None, save_contract=None, checkpoint_dir=None, checkpoint_load=None,
        reference_enabled=False, bus_trace=None, bus_trace_calls=None, bus_trace_events=None) -> dict:
    options = dict(allow_revision_override=allow_revision_override, dev_port=dev_port,
                   start_paused=start_paused, memory_write=memory_write,
                   code_capture=code_capture, capture_limit=capture_limit, capture_profile=capture_profile,
                   checkpoint_dir=checkpoint_dir, checkpoint_load=checkpoint_load, reference_enabled=reference_enabled,
                   bus_trace=bus_trace, bus_trace_calls=bus_trace_calls, bus_trace_events=bus_trace_events)
    requested = (save_root is not None, save_namespace is not None, save_contract is not None)
    if not any(requested):
        return _run(descriptor, build_dir, receipt_path, **options)
    if not all(requested):
        raise ValueError("Persistence requires save_root, save_namespace and save_contract together")
    if reference_enabled:
        raise ValueError('Reference capability cannot publish a persistent BRAM session')
    if checkpoint_load is not None:
        raise ValueError('Checkpoint loading cannot publish a persistent BRAM session')
    if receipt_path.exists() or receipt_path.is_symlink():
        raise ValueError("Execution receipt already exists")
    checked = verify(descriptor, allow_revision_override=allow_revision_override)
    identity = save_identity(checked, save_contract)
    root = Path(save_root).absolute()
    # Keep disposable outputs out of the dedicated mutable-save directory.
    for output in (receipt_path, code_capture, bus_trace):
        if output is not None and Path(output).resolve().is_relative_to(root.resolve()):
            raise ValueError("Execution receipt/capture must be outside the save root")
    from .saves import BramSession
    with BramSession(root, save_namespace, identity) as session:
        return _run(descriptor, build_dir, receipt_path, bram_session=session, bram_contract=save_contract, **options)


def _run(descriptor: Path, build_dir: Path, receipt_path: Path, *, allow_revision_override=False,
         dev_port=None, start_paused=False, memory_write=False, code_capture=None, capture_limit=None, capture_profile='legacy',
         bram_session=None, bram_contract=None, checkpoint_dir=None, checkpoint_load=None,
         reference_enabled=False, bus_trace=None, bus_trace_calls=None, bus_trace_events=None) -> dict:
    if receipt_path.exists() or receipt_path.is_symlink():
        raise ValueError("Execution receipt already exists")
    project, built, binary, _ = _verified_package(descriptor, build_dir,
        allow_revision_override=allow_revision_override)
    if code_capture is not None:
        code_capture = Path(code_capture).resolve()
        if code_capture.exists() or code_capture.is_symlink() or not code_capture.parent.is_dir():
            raise ValueError("Code capture requires a new file in an existing directory")
        if code_capture == receipt_path.resolve():
            raise ValueError("Capture and execution receipt require separate paths")
    if bus_trace is not None:
        bus_trace = Path(bus_trace).resolve()
        if bus_trace.exists() or bus_trace.is_symlink() or not bus_trace.parent.is_dir():
            raise ValueError('Bus trace requires a new file in an existing directory')
        if bus_trace == receipt_path.resolve() or (code_capture is not None and bus_trace == code_capture):
            raise ValueError('Bus trace, capture and receipt require separate paths')
    command = command_for(project, binary, dev_port=dev_port, start_paused=start_paused, memory_write=memory_write,
                          code_capture=code_capture, capture_limit=capture_limit, capture_profile=capture_profile,
                          checkpoint_dir=checkpoint_dir, checkpoint_load=checkpoint_load, reference_enabled=reference_enabled,
                   bus_trace=bus_trace, bus_trace_calls=bus_trace_calls, bus_trace_events=bus_trace_events)
    if bram_session is not None:
        if save_identity(project, bram_contract) != bram_session.compatibility_sha256:
            raise ValueError("Consumer save binding changed before execution")
        if bram_session.seed_path is not None:
            command += ["--bram", str(bram_session.seed_path)]
        command += ["--bram-out", str(bram_session.output_path)]
    started = time.monotonic()
    # Inherit stderr so ephemeral TCP port discovery remains immediately visible.
    timed_out = False
    try:
        completed = subprocess.run(command, stdout=subprocess.PIPE, text=True, shell=False,
                                   timeout=project["config"]["limits"]["wall_seconds"] + 10)
    except subprocess.TimeoutExpired as error:
        timed_out = True
        output = error.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        completed = subprocess.CompletedProcess(command, -1, output)
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        result = None
    checkpoint_report = _checkpoint_provenance(result, requested=checkpoint_load is not None)
    counters = None
    if isinstance(result, dict) and all(type(result.get(k)) is int and result[k] >= 0 for k in ("native_steps", "interpreter_steps")):
        native, interpreted = result["native_steps"], result["interpreter_steps"]
        if checkpoint_report is not None and checkpoint_report['valid'] and checkpoint_report['resumed']:
            native, interpreted = (checkpoint_report['window'][key] for key in ('native_steps', 'interpreter_steps'))
        counters = {"native": native, "interpreted": interpreted, "total": native + interpreted,
                    "native_fraction": native / (native + interpreted) if native + interpreted else 0.0}
    if checkpoint_report is not None and not checkpoint_report['valid']:
        counters = None
    unchanged = {name: path.is_file() and sha256(path) == project["identities"][name] for name, path in project["files"].items()}
    source_unchanged = source_identity(project["tool_root"]) == project["tool_identity"]
    outputs_unchanged = all((binary.parent / name).is_file() and sha256(binary.parent / name) == digest
                            for name, digest in built["output_files"].items())
    boot_report = _boot_provenance(project, result, bram_seeded=(bram_session.seed_path is not None)
                                   if bram_session is not None else None)
    vdc_report = _vdc_access_provenance(project, result)
    policy_report = _execution_policy_provenance(project, result, reference_enabled=reference_enabled)
    dispatch_report = _native_dispatch_provenance(project, result, reference_enabled=reference_enabled)
    capture_report = None
    if code_capture is not None:
        from .capture import load_capture
        try:
            capture, capture_hash = load_capture(code_capture)
            expected_schema = 2 if capture_profile == 'extended' else 1
            if capture.get('schema') != expected_schema:
                raise ValueError('Fresh code capture schema differs from requested capture_profile')
            if capture_profile == 'extended' and capture.get('format') != 'pce-code-capture-2':
                raise ValueError('Fresh code capture format differs from requested capture_profile')
            if capture["runtime_abi"] != ABI:
                raise ValueError("Fresh code capture runtime ABI differs from the running tool")
            expected_origin = (checkpoint_report['origin'] if checkpoint_report and checkpoint_report['valid']
                               and checkpoint_report['resumed'] else None)
            if capture.get('checkpoint_origin') != expected_origin:
                raise ValueError('Code capture checkpoint origin differs from execution window')
            expected_policy = ({key: value for key, value in policy_report.items() if key != 'valid'}
                               if policy_report and policy_report['valid'] else None)
            if capture.get('execution_policy') != expected_policy:
                raise ValueError('Code capture execution policy differs from the host report')
            if capture["capacity"] != (capture_limit if capture_limit is not None else 16384):
                raise ValueError("Code capture capacity differs from the requested limit")
            if counters is None or capture["retired_instructions"] != counters["total"]:
                raise ValueError("Code capture total differs from final execution counters")
            native_hits = sum(item["native_hits"] for item in capture["observations"])
            interpreted_hits = sum(item["interpreted_hits"] for item in capture["observations"])
            if native_hits > counters["native"] or interpreted_hits > counters["interpreted"]:
                raise ValueError("Code capture tier hits exceed final execution counters")
            lost = capture["dropped_instructions"] + capture["unreadable_instructions"]
            if counters["total"] - native_hits - interpreted_hits != lost:
                raise ValueError("Code capture missing retirements differ from its recorded loss")
            # Loss counters have no execution tier. Retain that uncertainty;
            # a lossless capture must account for each tier exactly.
            if not lost and (native_hits != counters["native"] or interpreted_hits != counters["interpreted"]):
                raise ValueError("Complete code capture tier hits differ from final execution counters")
            capture_report = {"path": str(code_capture), "sha256": capture_hash,
                              "bytes": code_capture.stat().st_size, "valid": True,
                              "runtime_abi": capture["runtime_abi"], "native_hits": native_hits,
                              "interpreted_hits": interpreted_hits, "unclassified_retirements": lost,
                              **{key: capture[key] for key in ("capacity", "complete", "dropped_instructions",
                                   "unreadable_instructions", "retired_instructions")},
                              "observations": len(capture["observations"])}
            if capture_profile == 'extended':
                capture_report.update(capture_profile='extended', capture_schema=2,
                                      capture_format='pce-code-capture-2')
            if expected_origin is not None:
                capture_report['checkpoint_origin'] = expected_origin
            if expected_policy is not None:
                capture_report['execution_policy'] = expected_policy
            if sha256(code_capture) != capture_hash:
                raise ValueError('Code capture changed during admission')
        except (ValueError, OSError, KeyError, TypeError) as error:
            capture_report = {"path": str(code_capture), "valid": False, "error": str(error)}
    bus_trace_report = None
    if bus_trace is not None:
        from .bus_trace import load_trace
        try:
            if type(result) is not dict:
                raise ValueError('Host result unavailable for bus trace binding')
            trace = load_trace(bus_trace)
            if trace.sha256 != sha256(bus_trace) or trace.sha256 != result.get('bus_trace_sha256'):
                raise ValueError('Bus trace changed during admission')
            producer = trace.header['engine']
            if producer != {'name': 'pcenginerecomp', 'revision': project['tool_identity']['revision'],
                    'source_sha256': project['tool_identity']['source_sha256'], 'binary_sha256': built['binary_sha256']}:
                raise ValueError('Bus trace producer differs from verified build')
            if trace.header['fixture_sha256'] != checkpoint_context(project, reference_enabled=reference_enabled):
                raise ValueError('Bus trace fixture context differs from reviewed recipe')
            expected_origin = (checkpoint_report['origin'] if checkpoint_report and checkpoint_report['valid']
                               and checkpoint_report['resumed'] else None)
            if trace.header.get('checkpoint_origin') != expected_origin:
                raise ValueError('Bus trace checkpoint origin differs from actual execution')
            expected_calls = 256 if bus_trace_calls is None else bus_trace_calls
            expected_events = 60000 if bus_trace_events is None else bus_trace_events
            if trace.header['limits']['calls'] != expected_calls or trace.header['limits']['events'] != expected_events:
                raise ValueError('Bus trace bounds differ from requested window')
            native = sum(call['end']['native'] for call in trace.calls)
            interpreted = sum(call['end']['interpreted'] for call in trace.calls)
            irqs = sum(call['end']['irq'] for call in trace.calls)
            summary = dict(schema=1, enabled=True, calls=len(trace.calls), events=len(trace.events),
                           call_limit=expected_calls, event_limit=expected_events, native=native,
                           interpreted=interpreted, irq=irqs, complete=trace.final['complete'])
            if result.get('bus_trace') != summary:
                raise ValueError('Bus trace closure differs from host observer counters')
            if counters is None or native > counters['native'] or interpreted > counters['interpreted']:
                raise ValueError('Bus trace counters exceed newly executed window')
            if trace.final['state']['ticks'] > result['ticks']:
                raise ValueError('Bus trace boundary exceeds final guest time')
            bus_trace_report = dict(path=str(bus_trace), sha256=trace.sha256, bytes=bus_trace.stat().st_size,
                valid=trace.final['complete'], producer=producer, checkpoint_origin=expected_origin,
                initial=trace.initial, final=trace.final, counters=summary,
                scope='Bounded callback window; later guest execution is separate')
        except (ValueError, OSError, KeyError, TypeError) as error:
            bus_trace_report = dict(path=str(bus_trace), valid=False, error=str(error))
    receipt = {"schema": 1, "kind": "pce-consumer-execution", "binding": _binding(project),
               "binary_sha256": built["binary_sha256"], "command": command,
               "elapsed_seconds": time.monotonic() - started, "exit_code": completed.returncode,
               "timed_out": timed_out, "tool_source_unchanged": source_unchanged,
               "build_outputs_unchanged": outputs_unchanged, "code_capture": capture_report, "bus_trace": bus_trace_report,
               "input_hashes_unchanged": unchanged, "work": counters, "result": result,
               "qualified": completed.returncode == 0 and counters is not None and all(unchanged.values())
                            and source_unchanged and outputs_unchanged and (capture_report is None or capture_report["valid"])
                            and (bus_trace_report is None or bus_trace_report["valid"])
                            and (boot_report is None or boot_report["valid"])
                            and (vdc_report is None or vdc_report["valid"])
                            and (policy_report is None or policy_report['valid'])
                            and (dispatch_report is None or dispatch_report['valid']),
               "limits": ["Execution receipt is reproducibility evidence, not independent emulator parity",
                          "Native site count is not executed native work; full host diagnostics retained",
                          "BRAM is volatile unless an explicit save session commits; unknown-command profile is explicit"]}
    if checkpoint_report is not None:
        receipt['checkpoint_validation'] = checkpoint_report
        receipt['qualified'] &= checkpoint_report['valid']
        if checkpoint_report['valid'] and checkpoint_report['resumed']:
            receipt['work']['execution_window'] = 'resumed-checkpoint-suffix'
            receipt['work']['imported'] = checkpoint_report['origin']
            receipt['limits'].append('Work counts describe only this resumed checkpoint suffix; imported prefix is separate')
    if boot_report is not None:
        receipt["boot_validation"] = boot_report
    if vdc_report is not None:
        receipt["vdc_access_validation"] = vdc_report
    if dispatch_report is not None:
        receipt['native_dispatch_validation'] = dispatch_report
    if policy_report is not None:
        receipt['execution_policy_validation'] = policy_report
    if bram_session is not None:
        save_report = {"namespace": bram_session.namespace,
                       "compatibility_sha256": bram_session.compatibility_sha256,
                       "seeded": bram_session.seed_path is not None,
                       "previous_payload_sha256": bram_session.previous_payload_sha256,
                       "committed": False}
        if receipt["qualified"]:
            try:
                if result.get("stop") not in {"step_limit", "budget", "dev_quit", "window_closed"}:
                    raise ValueError("Save session requires an orderly budget or quit stop")
                save_report.update(bram_session.commit(), committed=True)
            except (ValueError, OSError) as error:
                save_report["error"] = str(error)
                save_report["committed"] = bram_session.committed
                receipt["qualified"] = False
        receipt["bram_session"] = save_report
    _write_new(receipt_path, receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    identity_parser = commands.add_parser("identity")
    identity_parser.add_argument("tool_root", type=Path)
    for name in ("verify", "build", "resume", "run", "launch-plan"):
        sub = commands.add_parser(name)
        sub.add_argument("descriptor", type=Path)
        sub.add_argument("--allow-revision-override", action="store_true")
        if name in ("build", "resume", "run", "launch-plan"):
            sub.add_argument("--build-dir", type=Path, required=True)
        if name == "build":
            sub.add_argument("--generator")
            sub.add_argument("--desktop", action="store_true")
            sub.add_argument("--cmake-arg", action="append", default=[])
            sub.add_argument('--cache-root', type=Path)
            sub.add_argument('--cache-toolchain-root', type=Path)
            sub.add_argument('--cache-dependency-root', type=Path, action='append', default=[])
            sub.add_argument('--recoverable', action='store_true')
            sub.add_argument('--recovery-toolchain-root', type=Path)
            sub.add_argument('--recovery-dependency-root', type=Path, action='append', default=[])
        if name in ("run", "launch-plan"):
            if name == 'run':
                sub.add_argument("--receipt", type=Path, required=True)
            sub.add_argument("--dev-port", type=int)
            sub.add_argument("--start-paused", action="store_true")
            sub.add_argument("--memory-write", action="store_true")
            sub.add_argument('--reference-enabled', action='store_true',
                             help='Enable same-build paused interpreter reference windows')
            sub.add_argument("--code-capture", type=Path)
            sub.add_argument("--capture-limit", type=int)
            sub.add_argument('--capture-profile', choices=('legacy', 'extended'), default='legacy')
            sub.add_argument('--bus-trace', type=Path, help='Private bounded software data-access JSONL')
            sub.add_argument('--bus-trace-calls', type=int)
            sub.add_argument('--bus-trace-events', type=int)
            if name == 'run':
                sub.add_argument("--save-root", type=Path)
                sub.add_argument("--save-namespace")
                sub.add_argument("--save-contract", help="SHA256 of the consumer's explicit save/mod compatibility contract")
            sub.add_argument('--checkpoint-dir', type=Path)
            sub.add_argument('--checkpoint-load', help='Private direct checkpoint basename to import at paused startup')
    args = parser.parse_args(argv)
    try:
        if args.command == "identity":
            result = source_identity(args.tool_root)
        elif args.command == "verify":
            checked = verify(args.descriptor, allow_revision_override=args.allow_revision_override)
            result = {"schema": 1, "verified": True, **_binding(checked)}
        elif args.command == "build":
            result = build(args.descriptor, args.build_dir, allow_revision_override=args.allow_revision_override,
                           generator=args.generator, desktop=args.desktop, cmake_args=args.cmake_arg,
                           cache_root=args.cache_root, cache_toolchain_root=args.cache_toolchain_root,
                           cache_dependency_roots=args.cache_dependency_root, recoverable=args.recoverable,
                           recovery_toolchain_root=args.recovery_toolchain_root,
                           recovery_dependency_roots=args.recovery_dependency_root)
        elif args.command == 'resume':
            result = resume(args.descriptor, args.build_dir,
                            allow_revision_override=args.allow_revision_override)
        elif args.command == 'launch-plan':
            result = prepare_launch(args.descriptor, args.build_dir,
                allow_revision_override=args.allow_revision_override, dev_port=args.dev_port,
                start_paused=args.start_paused, memory_write=args.memory_write,
                code_capture=args.code_capture, capture_limit=args.capture_limit,
                capture_profile=args.capture_profile, reference_enabled=args.reference_enabled,
                checkpoint_dir=args.checkpoint_dir, checkpoint_load=args.checkpoint_load,
                bus_trace=args.bus_trace, bus_trace_calls=args.bus_trace_calls,
                bus_trace_events=args.bus_trace_events)
        else:
            result = run(args.descriptor, args.build_dir, args.receipt, allow_revision_override=args.allow_revision_override,
                         dev_port=args.dev_port, start_paused=args.start_paused, memory_write=args.memory_write,
                         code_capture=args.code_capture, capture_limit=args.capture_limit, capture_profile=args.capture_profile,
                         save_root=args.save_root, save_namespace=args.save_namespace, save_contract=args.save_contract,
                         checkpoint_dir=args.checkpoint_dir, checkpoint_load=args.checkpoint_load,
                         reference_enabled=args.reference_enabled, bus_trace=args.bus_trace,
                         bus_trace_calls=args.bus_trace_calls, bus_trace_events=args.bus_trace_events)
        print(json.dumps(result, indent=2))
        return 0 if args.command != "run" or result["qualified"] else 3
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, TypeError) as error:
        print(f"consumer: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

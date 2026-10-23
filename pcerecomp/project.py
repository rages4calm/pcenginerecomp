"""Versioned consumer contract, checked builds and bounded execution receipts.

No installation, dependency download, implicit media search or save persistence.
All descriptor paths are relative to the descriptor, never the caller's cwd.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import tomllib

ABI = 13
MAX_MODULE_MANIFEST_BYTES = 64 * 1024 * 1024
SOURCE_DIRS = ("pcerecomp", "runtime", "cmake")
ASSETS = {"bios", "bram", "toc", "disc", "libchdr", "input_script"}


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
    for field, suffix, minimum, maximum, prefix in (
            ("translation_units", ".cpp", 1, 65537, "module_unit"),
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


def verify(descriptor: Path, *, allow_revision_override=False) -> dict:
    descriptor = descriptor.resolve()
    config = tomllib.loads(descriptor.read_text(encoding="utf-8"))
    _table(config, {"schema", "name", "tool", "module", "payload", "runtime", "limits"}, ASSETS, "project")
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
    if re.search(r"\babi_version\s*=\s*13\s*;", header) is None:
        raise ValueError("Tool source ABI mismatch")
    module = _table(config["module"], {"source", "manifest"}, name="module")
    files = {"module_source": _file(base, module["source"], "module.source"),
             "module_manifest": _file(base, module["manifest"], "module.manifest")}
    if files["module_manifest"].stat().st_size > MAX_MODULE_MANIFEST_BYTES:
        raise ValueError("Module manifest exceeds 64 MiB")
    manifest = json.loads(files["module_manifest"].read_text(encoding="utf-8"))
    if (not isinstance(manifest, dict) or type(manifest.get("schema")) is not int or manifest["schema"] != 1
            or type(manifest.get("runtime_abi")) is not int or manifest["runtime_abi"] != ABI):
        raise ValueError("Module schema/runtime ABI mismatch")
    _integer(manifest.get("native_instructions_emitted"), 1, 1000000, "native_instructions_emitted")
    _module_artifacts(files, manifest)
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
    runtime = _table(config["runtime"], {"tier", "video", "cd_unknown_status", "joypad", "region", "multitap"}, optional={"audio"}, name="runtime")
    for key, values in (("tier", ("native", "hybrid")), ("video", ("snapshot", "continuous")),
                        ("cd_unknown_status", ("fault", "gear-good")), ("joypad", (2, 6)),
                        ("region", ("usa", "japan")), ("multitap", ("off", "on"))):
        _choice(runtime[key], values, key)
    if type(runtime["joypad"]) is not int:
        raise ValueError("joypad requires integer 2 or 6")
    if "audio" in runtime:
        _choice(runtime["audio"], ("on", "off"), "audio")
    limits = _table(config["limits"], {"steps", "ticks", "wall_seconds"}, name="limits")
    _integer(limits["steps"], 1, 20000000000, "steps")
    _integer(limits["ticks"], 1, 2**64 - 1, "ticks")
    _integer(limits["wall_seconds"], 1, 600, "wall_seconds")
    for name in ASSETS & config.keys():
        files[name] = _file(base, config[name], name)
    for name, expected_size in (("bios", 262144), ("bram", 2048)):
        if name in files and files[name].stat().st_size != expected_size:
            raise ValueError(f"{name} requires exactly {expected_size} bytes")
    if "libchdr" in files and "disc" not in files:
        raise ValueError("libchdr requires disc")
    return {"descriptor": descriptor, "config": config, "tool_root": tool_root,
            "tool_identity": identity, "revision_override": identity["revision"] != tool["revision"],
            "files": files, "identities": {name: sha256(path) for name, path in sorted(files.items())},
            "descriptor_sha256": sha256(descriptor)}


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
          generator=None, desktop=False, cmake_args=()) -> dict:
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
    (wrapper / "CMakeLists.txt").write_text("\n".join(source), encoding="utf-8")
    binary_dir = build_dir / "build"
    configure = ["cmake", "-S", str(wrapper), "-B", str(binary_dir), "-DCMAKE_BUILD_TYPE=Release"]
    if generator:
        configure += ["-G", generator]
    configure += list(cmake_args)
    compile_command = ["cmake", "--build", str(binary_dir), "--config", "Release", "--target", "pce-consumer", "--parallel", "2"]
    for command in (configure, compile_command):
        subprocess.run(command, check=True, shell=False)
    # The build may have raced a source modification: refuse to bless it.
    after = verify(descriptor, allow_revision_override=allow_revision_override)
    if _binding(after) != _binding(project):
        raise ValueError("Source/input identity changed during build")
    binary = binary_dir / "bin" / ("pce-consumer.exe" if os.name == "nt" else "pce-consumer")
    dependencies = {p.name: sha256(p) for p in sorted(binary.parent.iterdir()) if p.is_file()}
    receipt = {"schema": 1, "kind": "pce-consumer-build", "binding": _binding(project),
               "binary": str(binary), "binary_sha256": sha256(binary), "desktop": desktop,
               "output_files": dependencies, "commands": [configure, compile_command],
               "execution_evidence": False}
    _write_new(build_dir / "build-receipt.json", receipt)
    return receipt


def command_for(project: dict, binary: Path, *, dev_port=None, start_paused=False, memory_write=False,
                code_capture=None, capture_limit=None):
    config, files = project["config"], project["files"]
    payload, limits, runtime = config["payload"], config["limits"], config["runtime"]
    command = [str(binary), str(files["payload"]), str(payload["physical_load"]), str(payload["pc"]),
               ",".join(map(str, payload["mpr"])), str(limits["steps"]), str(limits["ticks"]), runtime["tier"]]
    for key, flag in (("video", "video-output"), ("cd_unknown_status", "cd-unknown-status"),
                      ("joypad", "joypad"), ("region", "joypad-region"), ("multitap", "multitap")):
        command += ["--" + flag, str(runtime[key])]
    command += ["--wall-seconds", str(limits["wall_seconds"])]
    if "audio" in runtime:
        command += ["--audio-output", runtime["audio"]]
    for name in sorted(ASSETS & files.keys()):
        command += ["--" + name.replace("_", "-"), str(files[name])]
    if dev_port is not None:
        _integer(dev_port, 0, 65535, "dev_port")
        if runtime["video"] != "continuous":
            raise ValueError("TCP requires continuous video")
        command += ["--dev-port", str(dev_port), "--dev-start-paused", "on" if start_paused else "off",
                    "--dev-memory-write", "on" if memory_write else "off"]
    elif start_paused or memory_write:
        raise ValueError("Pause/memory writes require --dev-port")
    if code_capture is not None:
        command += ["--code-capture", str(Path(code_capture).resolve())]
        if capture_limit is not None:
            _integer(capture_limit, 1, 65536, "capture_limit")
            command += ["--capture-limit", str(capture_limit)]
    elif capture_limit is not None:
        raise ValueError("capture_limit requires code_capture")
    return command


def run(descriptor: Path, build_dir: Path, receipt_path: Path, *, allow_revision_override=False,
        dev_port=None, start_paused=False, memory_write=False, code_capture=None, capture_limit=None) -> dict:
    if receipt_path.exists():
        raise ValueError("Execution receipt already exists")
    project = verify(descriptor, allow_revision_override=allow_revision_override)
    built = json.loads((build_dir / "build-receipt.json").read_text(encoding="utf-8"))
    if built.get("schema") != 1 or built.get("kind") != "pce-consumer-build" or built.get("binding") != _binding(project):
        raise ValueError("Build receipt does not match verified consumer")
    binary = Path(built["binary"])
    if sha256(binary) != built["binary_sha256"]:
        raise ValueError("Built executable changed")
    outputs = {p.name: sha256(p) for p in sorted(binary.parent.iterdir()) if p.is_file()}
    if outputs != built["output_files"]:
        raise ValueError("Build output/dependency identities changed")
    if code_capture is not None:
        code_capture = Path(code_capture).resolve()
        if code_capture.exists() or code_capture.is_symlink() or not code_capture.parent.is_dir():
            raise ValueError("Code capture requires a new file in an existing directory")
        if code_capture == receipt_path.resolve():
            raise ValueError("Capture and execution receipt require separate paths")
    command = command_for(project, binary, dev_port=dev_port, start_paused=start_paused, memory_write=memory_write,
                          code_capture=code_capture, capture_limit=capture_limit)
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
    counters = None
    if isinstance(result, dict) and all(type(result.get(k)) is int and result[k] >= 0 for k in ("native_steps", "interpreter_steps")):
        native, interpreted = result["native_steps"], result["interpreter_steps"]
        counters = {"native": native, "interpreted": interpreted, "total": native + interpreted,
                    "native_fraction": native / (native + interpreted) if native + interpreted else 0.0}
    unchanged = {name: path.is_file() and sha256(path) == project["identities"][name] for name, path in project["files"].items()}
    source_unchanged = source_identity(project["tool_root"]) == project["tool_identity"]
    outputs_unchanged = all((binary.parent / name).is_file() and sha256(binary.parent / name) == digest
                            for name, digest in built["output_files"].items())
    capture_report = None
    if code_capture is not None:
        from .capture import load_capture
        try:
            capture, capture_hash = load_capture(code_capture)
            if counters is None or capture["retired_instructions"] != counters["total"]:
                raise ValueError("Code capture total differs from final execution counters")
            capture_report = {"path": str(code_capture), "sha256": capture_hash,
                              "bytes": code_capture.stat().st_size, "valid": True,
                              **{key: capture[key] for key in ("capacity", "complete", "dropped_instructions",
                                   "unreadable_instructions", "retired_instructions")},
                              "observations": len(capture["observations"])}
        except (ValueError, OSError, KeyError, TypeError) as error:
            capture_report = {"path": str(code_capture), "valid": False, "error": str(error)}
    receipt = {"schema": 1, "kind": "pce-consumer-execution", "binding": _binding(project),
               "binary_sha256": built["binary_sha256"], "command": command,
               "elapsed_seconds": time.monotonic() - started, "exit_code": completed.returncode,
               "timed_out": timed_out, "tool_source_unchanged": source_unchanged,
               "build_outputs_unchanged": outputs_unchanged, "code_capture": capture_report,
               "input_hashes_unchanged": unchanged, "work": counters, "result": result,
               "qualified": completed.returncode == 0 and counters is not None and all(unchanged.values())
                            and source_unchanged and outputs_unchanged and (capture_report is None or capture_report["valid"]),
               "limits": ["Execution receipt is reproducibility evidence, not independent emulator parity",
                          "Native site count is not executed native work; full host diagnostics retained",
                          "BRAM remains volatile; unknown-command profile is explicit"]}
    _write_new(receipt_path, receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    identity_parser = commands.add_parser("identity")
    identity_parser.add_argument("tool_root", type=Path)
    for name in ("verify", "build", "run"):
        sub = commands.add_parser(name)
        sub.add_argument("descriptor", type=Path)
        sub.add_argument("--allow-revision-override", action="store_true")
        if name in ("build", "run"):
            sub.add_argument("--build-dir", type=Path, required=True)
        if name == "build":
            sub.add_argument("--generator")
            sub.add_argument("--desktop", action="store_true")
            sub.add_argument("--cmake-arg", action="append", default=[])
        if name == "run":
            sub.add_argument("--receipt", type=Path, required=True)
            sub.add_argument("--dev-port", type=int)
            sub.add_argument("--start-paused", action="store_true")
            sub.add_argument("--memory-write", action="store_true")
            sub.add_argument("--code-capture", type=Path)
            sub.add_argument("--capture-limit", type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == "identity":
            result = source_identity(args.tool_root)
        elif args.command == "verify":
            checked = verify(args.descriptor, allow_revision_override=args.allow_revision_override)
            result = {"schema": 1, "verified": True, **_binding(checked)}
        elif args.command == "build":
            result = build(args.descriptor, args.build_dir, allow_revision_override=args.allow_revision_override,
                           generator=args.generator, desktop=args.desktop, cmake_args=args.cmake_arg)
        else:
            result = run(args.descriptor, args.build_dir, args.receipt, allow_revision_override=args.allow_revision_override,
                         dev_port=args.dev_port, start_paused=args.start_paused, memory_write=args.memory_write,
                         code_capture=args.code_capture, capture_limit=args.capture_limit)
        print(json.dumps(result, indent=2))
        return 0 if args.command != "run" or result["qualified"] else 3
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, TypeError) as error:
        print(f"consumer: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

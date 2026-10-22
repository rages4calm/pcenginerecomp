import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

from . import __version__
from .analysis import Snapshot, analyze
from .emitter import emit
from .isa import Instruction, listing
from .media import Chd, ChdReader, Ipl, IsoReader, MediaError, sha256


def library_default():
    root = Path(__file__).resolve().parent.parent
    for name in ("libchdr.dll", "libchdr.so", "libchdr.dylib"):
        path = root / ".deps" / "libchdr-build" / name
        if path.exists():
            return path
    return None


def write_json(path: Path, result):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")


def protect_input(source: Path, output: Path):
    if source.resolve() == output.resolve() or (output.exists() and os.path.samefile(source, output)):
        raise ValueError("Output aliases the input; refusing to replace source data")


def boot(args):
    if args.out.exists() and any(args.out.iterdir()):
        raise ValueError("Boot output must be an empty directory")
    if args.image.suffix.lower() == ".chd":
        disc = Chd(args.image)
        tracks = [t for t in disc.tracks if t.type in ("MODE1", "MODE1_RAW")]
        if len(tracks) != 1:
            raise MediaError("Select a supported single-data-track disc for baseline boot discovery")
        if not args.libchdr:
            raise MediaError("CHD boot discovery needs --libchdr; see scripts/bootstrap_chd.py")
        track = tracks[0]
        with ChdReader(disc, args.libchdr) as reader:
            ipl = Ipl.parse(reader.sector(track, 1))
            validate_boot(ipl)
            # Boot-file coordinates are track-relative for this supported path.
            payload = b"".join(reader.sector(track, ipl.start_sector+n) for n in range(ipl.sector_count))
            transport = {"track": track.number, "disc_index1_lba": track.disc_start,
                         "chd_index1_frame": track.index1_frame,
                         "hunks_decompressed": reader.hunks_read,
                         "sector_coordinate": "relative to sole data track INDEX 01"}
    elif args.image.suffix.lower() == ".iso":
        reader = IsoReader(args.image)
        ipl = Ipl.parse(reader.sector(1))
        validate_boot(ipl)
        payload = b"".join(reader.sector(ipl.start_sector+n) for n in range(ipl.sector_count))
        transport = {"sector_coordinate": "relative to single-track ISO"}
    else:
        raise MediaError("Boot discovery accepts CHD or 2048-byte-sector ISO")
    mpr = tuple(ipl.report()["mpr"])
    # The loader can wrap banks in ways this milestone doesn't yet model.
    # Reject rather than map large programs through assumed MPRs.
    if ipl.load_address < 0x4000 or ipl.load_address+len(payload) > 0xE000:
        raise MediaError("Boot payload crosses unsupported loader/BIOS regions")
    if not ipl.load_address <= ipl.entry_address < ipl.load_address+len(payload):
        raise MediaError("IPL entry does not lie in the loaded program")
    segments = []
    occupied = set()
    for offset in range(0, len(payload), 1):
        logical = ipl.load_address+offset
        pa = (mpr[logical >> 13] << 13) | (logical & 8191)
        if pa in occupied:
            raise MediaError("Aliasing IPL load pages need a loader-aware profile; unsupported")
        occupied.add(pa)
        if not segments or pa != segments[-1][0]+len(segments[-1][1]):
            segments.append((pa, bytearray()))
        segments[-1][1].append(payload[offset])
    args.out.mkdir(parents=True, exist_ok=True)
    text = f"schema = 1\nmpr = {list(mpr)}\nentry_points = [{ipl.entry_address}]\n"
    for index, (pa, data) in enumerate(segments):
        name = f"boot-{index}.bin"
        (args.out / name).write_bytes(data)
        text += f'\n[[segments]]\nphysical = {pa}\nfile = "{name}"\nsha256 = "{hashlib.sha256(data).hexdigest()}"\n'
    (args.out / "snapshot.toml").write_text(text, encoding="utf-8")
    result = {"schema": 1, "image_sha256": sha256(args.image), "ipl": ipl.report(),
              "transport": transport, "payload_bytes": len(payload), "payload_sha256": hashlib.sha256(payload).hexdigest(),
              "scope": "boot-file extraction and explicit analysis snapshot; no BIOS execution or game boot"}
    write_json(args.out / "boot.json", result)
    print(json.dumps(result, indent=2))


def validate_boot(ipl):
    if not ipl.sector_count:
        raise MediaError("Embedded IPL execution (zero-sector programs) is not yet supported")
    if ipl.opening_mode:
        raise MediaError("IPL opening-mode media initialization needs a System Card loader; unsupported")
    if any(x > 7 for x in ipl.mpr_offsets):
        raise MediaError("Only standard CD RAM IPL mapping is supported in baseline extraction")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="pcerecomp", description="Experimental PC Engine recompilation toolkit")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="Report tool availability without installing anything")
    inspect = commands.add_parser("inspect", help="Inspect CHDv5 metadata; no decompression needed")
    inspect.add_argument("image", type=Path)
    inspect.add_argument("--hash", action="store_true", help="Compute file SHA256, not full CHD integrity verification")
    inspect.add_argument("--out", type=Path)
    load = commands.add_parser("boot", help="Extract bounded initial program into a private snapshot")
    load.add_argument("image", type=Path)
    load.add_argument("--libchdr", type=Path, default=library_default())
    load.add_argument("--out", type=Path, required=True)
    for name in ("analyze", "emit"):
        command = commands.add_parser(name, help="Analyze a pinned snapshot" if name == "analyze" else "Emit guarded native C++ from a snapshot")
        command.add_argument("snapshot", type=Path)
        command.add_argument("--limit", type=int, default=10000)
        command.add_argument("--out", type=Path, required=True)
        if name == "analyze":
            command.add_argument("--listing", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            print(json.dumps({"version": __version__, "python": sys.version.split()[0],
                              "tools": {name: shutil.which(name) for name in ("cmake", "ninja", "clang++", "git")},
                              "libchdr": str(library_default()) if library_default() else None,
                              "status": "development foundation; no playable games certified"}, indent=2))
        elif args.command == "inspect":
            report = Chd(args.image).report(args.hash)
            if args.out:
                protect_input(args.image, args.out)
                write_json(args.out, report)
            print(json.dumps(report, indent=2))
        elif args.command == "boot":
            boot(args)
        else:
            result = analyze(Snapshot.load(args.snapshot), args.limit)
            if args.command == "emit":
                print(json.dumps(emit(result, args.out), indent=2))
            else:
                protect_input(args.snapshot, args.out)
                write_json(args.out, result)
                if args.listing:
                    for item in result["instructions"]:
                        print(listing(Instruction(item["pc"], tuple(item["physical"]), tuple(item["data"]), item["mnemonic"], item["mode"], item["target"])))
                print(json.dumps(result["summary"], indent=2))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"pcerecomp: {exc}", file=sys.stderr)
        return 2

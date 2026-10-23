"""Audit tracked source paths/content before publication; read-only."""
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
BLOCKED_PARTS = {".local", ".research", ".deps", "build", "dist", "generated", "__pycache__", ".venv"}
BLOCKED_EXTENSIONS = {".chd", ".pce", ".sgx", ".cue", ".bin", ".iso", ".rom", ".sav", ".srm", ".state", ".toc", ".dll", ".exe", ".zip", ".7z"}
SECRET = re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)")
PERSONAL = re.compile(rb"(?:[A-Za-z]:[\\/]Users[\\/][^\s\"'<>]+|/[U]sers/[^\s\"'<>]+|/[h]ome/[^\s\"'<>]+)")


def main():
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
    problems, total, count = [], 0, 0
    for name in filter(None, names):
        path = PurePosixPath(name)
        if set(path.parts) & BLOCKED_PARTS or path.suffix.lower() in BLOCKED_EXTENSIONS:
            problems.append(f"blocked output/input path: {name}")
            continue
        file = ROOT / name
        if file.is_symlink() or not file.is_file():
            problems.append(f"non-regular tracked file: {name}")
            continue
        size = int(subprocess.check_output(["git", "cat-file", "-s", f":{name}"], cwd=ROOT))
        if size > 2*1024*1024:
            problems.append(f"file exceeds 2 MiB publication cap: {name}")
            continue
        data = subprocess.check_output(["git", "show", f":{name}"], cwd=ROOT)
        total += len(data); count += 1
        if b"\0" in data:
            problems.append(f"binary content: {name}")
        if SECRET.search(data):
            problems.append(f"credential-like content: {name}")
        if PERSONAL.search(data):
            problems.append(f"personal absolute path: {name}")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            problems.append(f"non-UTF8 content: {name}")
    if total > 10*1024*1024:
        problems.append("tracked source exceeds 10 MiB baseline publication cap")
    for problem in problems:
        print(problem, file=sys.stderr)
    print(f"Audited {count} tracked text files, {total} bytes; {len(problems)} problems")
    return bool(problems)


if __name__ == "__main__":
    raise SystemExit(main())

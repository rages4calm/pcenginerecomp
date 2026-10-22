"""Opt-in, project-local libchdr source acquisition/build. No installation."""
import argparse
from pathlib import Path
import subprocess
import sys

PIN = "47d794151b2b64f6aba60304e6480f4f5a2bc24b"
ROOT = Path(__file__).resolve().parent.parent


def run(*args):
    subprocess.run(args, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    source = ROOT / ".deps" / "libchdr"
    source.parent.mkdir(exist_ok=True)
    if not source.exists():
        run("git", "init", str(source))
        run("git", "-C", str(source), "remote", "add", "origin", "https://github.com/rtissera/libchdr.git")
        run("git", "-C", str(source), "fetch", "--depth", "1", "origin", PIN)
        run("git", "-C", str(source), "checkout", "--detach", "FETCH_HEAD")
    actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"], text=True)
    if actual != PIN or dirty:
        raise RuntimeError("Existing libchdr source differs from the pin or has local edits; refusing to change it")
    run("cmake", "-S", str(source), "-B", str(ROOT / ".deps/libchdr-build"), "-G", "Ninja",
        "-DCMAKE_BUILD_TYPE=Release", f"-DCMAKE_C_COMPILER={args.cc}", "-DBUILD_SHARED_LIBS=ON", "-DCHDR_WANT_TESTS=OFF")
    run("cmake", "--build", str(ROOT / ".deps/libchdr-build"), "--target", "chdr", "--parallel", "4")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)

"""Run the same two suites as CTest, including in toolchains without ctest."""
from pathlib import Path
import argparse
import os
import subprocess
import sys

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--build", type=Path, default=root / "build")
args = parser.parse_args()
environment=os.environ.copy()
environment["PCE_TEST_HEADLESS"]=str(args.build.resolve() / ("pce-headless.exe" if os.name=="nt" else "pce-headless"))
subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"], cwd=root, env=environment, check=True, timeout=60)
binary = args.build.resolve() / ("pce-runtime-tests.exe" if os.name == "nt" else "pce-runtime-tests")
subprocess.run([str(binary)], cwd=root, check=True, timeout=60)

"""Run the same suites as CTest, including in toolchains without ctest."""
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
io_binary=args.build.resolve() / ("pce-io-tests.exe" if os.name=="nt" else "pce-io-tests")
subprocess.run([str(io_binary)], cwd=root, check=True, timeout=60)
vdc_binary=args.build.resolve() / ("pce-vdc-tests.exe" if os.name=="nt" else "pce-vdc-tests")
subprocess.run([str(vdc_binary)], cwd=root, check=True, timeout=60)
raster_binary=args.build.resolve() / ("pce-raster-tests.exe" if os.name=="nt" else "pce-raster-tests")
subprocess.run([str(raster_binary)], cwd=root, check=True, timeout=60)
scsi_binary=args.build.resolve() / ("pce-scsi-tests.exe" if os.name=="nt" else "pce-scsi-tests")
subprocess.run([str(scsi_binary)], cwd=root, check=True, timeout=60)
joypad_binary=args.build.resolve() / ("pce-joypad-tests.exe" if os.name=="nt" else "pce-joypad-tests")
subprocess.run([str(joypad_binary)], cwd=root, check=True, timeout=60)

for suite in ("pce-read-tests", "pce-sector-tests"):
    command=[str(args.build.resolve() / (suite + (".exe" if os.name=="nt" else "")))]
    if suite=="pce-sector-tests":
        extension=".dll" if os.name=="nt" else (".so")
        prefix=""
        if sys.platform=="darwin": extension=".so"
        command.append(str(args.build.resolve() / (prefix+"pce-sector-decoder-fixture"+extension)))
    subprocess.run(command,cwd=root,check=True,timeout=60)

subprocess.run([str(args.build.resolve() / ("pce-block-tests.exe" if os.name=="nt" else "pce-block-tests"))],cwd=root,check=True,timeout=60)

subprocess.run([str(args.build.resolve() / ("pce-irq-tests.exe" if os.name=="nt" else "pce-irq-tests"))],cwd=root,check=True,timeout=60)

subprocess.run([str(args.build.resolve() / ("pce-video-tests.exe" if os.name=="nt" else "pce-video-tests"))],cwd=root,check=True,timeout=60)

for suite in ("pce-audio-tests","pce-dma-tests"):
    subprocess.run([str(args.build.resolve() / (suite+(".exe" if os.name=="nt" else "")))],cwd=root,check=True,timeout=60)

subprocess.run([str(args.build.resolve() / ("pce-adpcm-tests.exe" if os.name=="nt" else "pce-adpcm-tests"))],cwd=root,check=True,timeout=60)

subprocess.run([str(args.build.resolve() / ("pce-cdda-tests.exe" if os.name=="nt" else "pce-cdda-tests"))],cwd=root,check=True,timeout=60)

subprocess.run([str(args.build.resolve() / ("pce-input-script-tests.exe" if os.name=="nt" else "pce-input-script-tests"))],cwd=root,check=True,timeout=60)

"""Windows embedded consumers must ship and pin their selected SDL runtime."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from examples.consumer.prepare import prepare
from pcerecomp.project import sha256
from scripts.build_config import cmake_cache

ROOT = Path(__file__).resolve().parent.parent
COMPILER = shutil.which("clang++") or shutil.which("g++")
DESKTOP = Path(os.environ.get("PCE_TEST_DESKTOP", ROOT / "build/pce-desktop.exe"))


def sdk_directory():
    cache = cmake_cache(DESKTOP.parent, os.environ.get("PCE_TEST_CMAKE_CACHE"))
    if DESKTOP.is_file() and cache is not None:
        for line in cache.read_text(encoding="utf-8").splitlines():
            if line.startswith("SDL3_DIR:") and "=" in line:
                return line.split("=", 1)[1]
    return None


@unittest.skipUnless(os.name == "nt" and shutil.which("cmake") and
                     shutil.which("ninja") and COMPILER,
                     "Windows CMake/Ninja/C++ toolchain required")
class DesktopConsumerPackagingTests(unittest.TestCase):
    def test_local_imported_runtime_mapping_static_and_built_targets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child = root / "child"
            child.mkdir()
            (child / "empty.cpp").write_text("// Authored configure-only shared library.\n")
            (child / "CMakeLists.txt").write_text('''
add_library(local_sdl SHARED IMPORTED)
set_target_properties(local_sdl PROPERTIES
  IMPORTED_CONFIGURATIONS "RELEASE;DEBUG"
  IMPORTED_LOCATION_RELEASE "${CMAKE_CURRENT_SOURCE_DIR}/release.dll"
  IMPORTED_LOCATION_DEBUG "${CMAKE_CURRENT_SOURCE_DIR}/debug.dll"
  MAP_IMPORTED_CONFIG_RELWITHDEBINFO RELEASE)
add_library(SDL3::SDL3 ALIAS local_sdl)
add_library(embedded_host INTERFACE)
pce_record_desktop_runtime(embedded_host SDL3::SDL3)
add_library(static_sdl STATIC IMPORTED)
add_library(static_host INTERFACE)
pce_record_desktop_runtime(static_host static_sdl)
add_library(built_sdl SHARED empty.cpp)
add_library(built_alias ALIAS built_sdl)
add_library(built_host INTERFACE)
pce_record_desktop_runtime(built_host built_alias)
''', encoding="utf-8")
            (root / "CMakeLists.txt").write_text(f'''
cmake_minimum_required(VERSION 3.20)
project(RuntimeScope LANGUAGES CXX)
include("{ROOT.as_posix()}/cmake/PCEConsumer.cmake")
add_subdirectory(child)
if(TARGET local_sdl OR TARGET SDL3::SDL3)
  message(FATAL_ERROR "Imported targets escaped their original directory")
endif()
get_target_property(runtime embedded_host PCE_DESKTOP_RUNTIME_DLL)
get_target_property(static_runtime static_host PCE_DESKTOP_RUNTIME_DLL)
if(static_runtime)
  message(FATAL_ERROR "Static SDL unexpectedly requests a runtime DLL")
endif()
get_target_property(built_runtime built_host PCE_DESKTOP_RUNTIME_DLL)
file(GENERATE OUTPUT "${{CMAKE_BINARY_DIR}}/runtime-$<CONFIG>.txt" CONTENT "${{runtime}}")
file(GENERATE OUTPUT "${{CMAKE_BINARY_DIR}}/built-$<CONFIG>.txt" CONTENT "${{built_runtime}}")
''', encoding="utf-8")
            for generator, name in (("Ninja", "single"), ("Ninja Multi-Config", "multi")):
                build = root / name
                command = ["cmake", "-S", str(root), "-B", str(build), "-G", generator,
                           f"-DCMAKE_CXX_COMPILER={COMPILER}", "-DCMAKE_BUILD_TYPE=Debug"]
                result = subprocess.run(command, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                configs = {"Debug": "debug"} if name == "single" else {
                    "Debug": "debug", "Release": "release", "RelWithDebInfo": "release"}
                for config, selected in configs.items():
                    self.assertEqual(Path((build / f"runtime-{config}.txt").read_text()),
                                     child / f"{selected}.dll")
                    built = Path((build / f"built-{config}.txt").read_text())
                    self.assertEqual(built.suffix, ".dll")
                    self.assertTrue(built.stem.endswith("built_sdl"))

    @unittest.skipUnless(sdk_directory(), "Enabled SDL build required for actual consumer packaging")
    def test_official_desktop_build_ships_pins_and_loads_sdl_without_sdk_path(self):
        sdk = sdk_directory()
        expected = sha256(DESKTOP.parent / "SDL3.dll")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            descriptor = prepare(root / "project")
            descriptor.write_text(descriptor.read_text().replace("[runtime]", '[runtime]\naudio = "on"'))
            build = root / "consumer-build"
            command = [sys.executable, "-m", "pcerecomp.project", "build", str(descriptor),
                       "--build-dir", str(build), "--desktop", "--generator", "Ninja",
                       f"--cmake-arg=-DCMAKE_CXX_COMPILER={COMPILER}", f"--cmake-arg=-DSDL3_DIR={sdk}"]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            receipt = json.loads((build / "build-receipt.json").read_text())
            dll = Path(receipt["binary"]).parent / "SDL3.dll"
            self.assertTrue(dll.is_file(), "Embedded consumer omitted its SDL runtime")
            self.assertEqual(sha256(dll), expected)
            self.assertEqual(receipt["output_files"]["SDL3.dll"], expected)
            env = os.environ.copy()
            env.update(SDL_VIDEODRIVER="dummy", SDL_RENDER_DRIVER="software", SDL_AUDIODRIVER="dummy")
            env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep)
                                          if not (Path(p) / "SDL3.dll").is_file())
            run_receipt = root / "run.json"
            run = [sys.executable, "-m", "pcerecomp.project", "run", str(descriptor),
                   "--build-dir", str(build), "--receipt", str(run_receipt)]
            result = subprocess.run(run, cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            qualified = json.loads(run_receipt.read_text())
            self.assertTrue(qualified["qualified"])
            self.assertEqual((qualified["work"]["native"], qualified["work"]["interpreted"]), (200, 0))
            self.assertEqual((qualified["result"]["a"], qualified["result"]["x"],
                              qualified["result"]["pc"]), (41, 140, 16387))
            self.assertTrue(qualified["result"]["audio_output"]["device_open"])
            self.assertTrue(qualified["build_outputs_unchanged"])
            original = dll.read_bytes()
            try:
                dll.write_bytes(original + b"authored stale runtime marker")
                refused = root / "refused.json"
                run[-1] = str(refused)
                result = subprocess.run(run, cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertFalse(refused.exists())
            finally:
                dll.write_bytes(original)
            self.assertEqual(sha256(DESKTOP.parent / "SDL3.dll"), expected)

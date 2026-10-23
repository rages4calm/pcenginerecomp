"""Configure a real parent project without disabling its own tests."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
COMPILER = shutil.which("clang++") or shutil.which("g++")


@unittest.skipUnless(shutil.which("cmake") and shutil.which("ninja") and COMPILER,
                     "CMake/Ninja/C++ compiler required for embedding configure check")
class CMakeConsumerTests(unittest.TestCase):
    def test_parent_testing_survives_without_tool_tests_or_runners(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "module.cpp").write_text("// Authored configure-only module fixture.\n")
            (root / "CMakeLists.txt").write_text(f'''cmake_minimum_required(VERSION 3.20)
project(ParentConsumer LANGUAGES CXX)
set(BUILD_TESTING ON CACHE BOOL "" FORCE)
include(CTest)
add_subdirectory("{ROOT.as_posix()}" tool)
pce_add_consumer(parent-consumer MODULE module.cpp)
if(NOT BUILD_TESTING OR PCE_BUILD_TESTS OR PCE_BUILD_TOOLS)
  message(FATAL_ERROR "Embedding changed parent test policy or enabled tool extras")
endif()
if(NOT TARGET parent-consumer OR NOT TARGET pce-runtime OR TARGET pce-headless OR TARGET pce-runtime-tests)
  message(FATAL_ERROR "Unexpected embedding target graph")
endif()
''', encoding="utf-8")
            result = subprocess.run(["cmake", "-S", str(root), "-B", str(root / "build"),
                                     "-G", "Ninja", f"-DCMAKE_CXX_COMPILER={COMPILER}"],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

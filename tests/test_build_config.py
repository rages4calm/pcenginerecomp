"""Authored standalone, embedded and explicit SDK configuration discovery."""
from pathlib import Path
import tempfile
import unittest

from scripts.build_config import cmake_cache


class BuildConfigurationTests(unittest.TestCase):
    def test_nearest_cache_for_supported_binary_layouts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / "CMakeCache.txt"
            cache.write_text("PCE_BUILD_DESKTOP:BOOL=ON\n")
            for path in (root, root / "upstream", root / "upstream/Debug"):
                path.mkdir(parents=True, exist_ok=True)
                self.assertEqual(cmake_cache(path), cache.resolve())
            nested = root / "upstream/CMakeCache.txt"
            nested.write_text("PCE_BUILD_DESKTOP:BOOL=OFF\n")
            self.assertEqual(cmake_cache(root / "upstream/Debug"), nested.resolve())

    def test_explicit_missing_cache_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "CMakeCache.txt").write_text("authored")
            self.assertIsNone(cmake_cache(root, root / "missing.txt"))
            explicit = root / "explicit.txt"
            explicit.write_text("authored explicit")
            self.assertEqual(cmake_cache(root, explicit), explicit.resolve())

    def test_no_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertIsNone(cmake_cache(Path(temporary)))

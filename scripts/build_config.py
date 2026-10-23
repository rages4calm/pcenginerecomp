"""Locate configuration for standalone or nested authored CMake test builds."""
from pathlib import Path


def cmake_cache(binary_directory: Path, explicit=None):
    if explicit:
        candidate = Path(explicit).resolve()
        return candidate if candidate.is_file() else None
    directory = Path(binary_directory).resolve()
    # Standalone, nested add_subdirectory, and multi-config binary layouts.
    for parent in (directory, directory.parent, directory.parent.parent):
        candidate = parent / "CMakeCache.txt"
        if candidate.is_file():
            return candidate
    return None

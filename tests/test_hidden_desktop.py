"""Mock Win32 contracts only; no desktop or GPU is created by these tests."""
import ctypes
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hidden_desktop", ROOT/"scripts/hidden_desktop.py")
hidden = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hidden)


class FakeKernel:
    def __init__(self):
        self.closed, self.attributes_deleted, self.duplicates = [], 0, []
        self.created, self.resumed, self.killed = [], [], []
        self.failure, self.running, self.wait_result = None, False, hidden.WAIT_OBJECT_0

    def GetCurrentProcess(self):
        return 50

    def DuplicateHandle(self, source_process, source, destination_process, target, rights, inherit, options):
        if self.failure == "duplicate" and self.duplicates:
            return False
        self.duplicates.append((source_process, source, destination_process, rights, inherit, options))
        target._obj.value = 100+len(self.duplicates)
        return True

    def InitializeProcThreadAttributeList(self, buffer, count, flags, size):
        size._obj.value = 128
        return buffer is not None

    def UpdateProcThreadAttribute(self, attributes, flags, key, handles, size, previous, returned):
        self.handle_list = list(handles)
        self.attribute_key = key
        return self.failure != "attribute"

    def DeleteProcThreadAttributeList(self, buffer):
        self.attributes_deleted += 1

    def CreateProcessW(self, application, command, psecurity, tsecurity, inherit, flags, env, cwd, startup, process):
        self.created.append({"application": application, "command": command.value,
            "inherit": inherit, "flags": flags, "desktop": startup._obj.StartupInfo.lpDesktop,
            "cb": startup._obj.StartupInfo.cb, "stdin": startup._obj.StartupInfo.hStdInput,
            "stdout": startup._obj.StartupInfo.hStdOutput, "stderr": startup._obj.StartupInfo.hStdError,
            "env": env, "cwd": cwd})
        if self.failure == "create":
            return False
        process._obj.hProcess, process._obj.hThread = 9001, 9002
        process._obj.dwProcessId = 12345
        return True

    def ResumeThread(self, handle):
        self.resumed.append(handle)
        return 0xFFFFFFFF if self.failure == "resume" else 1

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return True

    def WaitForSingleObject(self, process, milliseconds):
        self.last_wait = (process, milliseconds)
        if self.running:
            return hidden.WAIT_TIMEOUT
        return self.wait_result

    def GetExitCodeProcess(self, process, code):
        code._obj.value = 7
        return True

    def TerminateProcess(self, process, code):
        self.killed.append((process, code))
        self.running = False
        return True


class FakeUser:
    def __init__(self):
        self.created, self.closed = [], []

    def CreateDesktopW(self, name, device, mode, flags, rights, security):
        self.created.append((name, device, mode, flags, rights, security))
        return 8001

    def CloseDesktop(self, handle):
        self.closed.append(handle)
        return True


class HiddenDesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stdout = (self.root/"out.log").open("wb")
        self.stderr = (self.root/"err.log").open("wb")
        self.addCleanup(self.stdout.close)
        self.addCleanup(self.stderr.close)
        self.api = object.__new__(hidden.WindowsApi)
        self.api.kernel, self.api.user = FakeKernel(), FakeUser()
        self.args = [str(self.root/"a program.exe"), "--out", "a frame.ppm"]
        self.env = {"Z": "last", "A": "first"}
        fake_crt = types.ModuleType("msvcrt")
        fake_crt.get_osfhandle = lambda descriptor: descriptor+1000
        self.addCleanup(patch.stopall)
        patch.dict(sys.modules, {"msvcrt": fake_crt}).start()
        patch.object(hidden, "_error", side_effect=lambda operation: OSError("authored "+operation)).start()

    def create(self):
        return hidden.IsolatedProcess(self.args, stdout=self.stdout, stderr=self.stderr, env=self.env, api=self.api)

    def test_unique_desktop_and_exact_explicit_stdio_inheritance(self):
        child = self.create()
        launch = self.api.kernel.created[0]
        self.assertEqual(launch["application"], self.args[0])
        self.assertEqual(launch["command"], subprocess.list2cmdline(self.args))
        self.assertEqual(launch["desktop"], child.desktop_name)
        self.assertTrue(child.desktop_name.startswith("PceProbe_"))
        self.assertEqual(launch["cb"], ctypes.sizeof(hidden.STARTUPINFOEX))
        self.assertEqual(launch["cwd"], os.path.dirname(self.args[0]))
        self.assertEqual(self.api.kernel.handle_list, [101, 102, 103])
        self.assertEqual([launch[key] for key in ("stdin", "stdout", "stderr")], [101, 102, 103])
        self.assertEqual(self.api.kernel.attribute_key, hidden.PROC_THREAD_ATTRIBUTE_HANDLE_LIST)
        self.assertEqual(launch["flags"], hidden.EXTENDED_STARTUPINFO_PRESENT | hidden.CREATE_UNICODE_ENVIRONMENT |
                         hidden.CREATE_NO_WINDOW | hidden.CREATE_SUSPENDED)
        self.assertEqual(self.api.kernel.resumed, [9002])
        self.assertEqual(self.api.kernel.closed, [103, 102, 101, 9002])
        self.assertEqual(self.api.kernel.attributes_deleted, 1)
        self.assertEqual(self.api.user.created[0][4] & hidden.DESKTOP_SWITCHDESKTOP, 0)
        self.assertEqual(self.api.user.created[0][5], None)
        self.assertEqual(child.poll(), 7)
        child.close()
        self.assertTrue(child.closed)
        self.assertEqual(self.api.kernel.closed[-1], 9001)
        self.assertEqual(self.api.user.closed, [8001])
        child.close()
        self.assertEqual(self.api.user.closed, [8001])
        other = self.create()
        self.assertNotEqual(other.desktop_name, child.desktop_name)
        other.close()

    def test_failed_duplicate_attribute_and_process_creation_close_all_acquired_handles(self):
        for failure, closed, attribute_deletions in (
                ("duplicate", [101], 0), ("attribute", [103, 102, 101], 1),
                ("create", [103, 102, 101], 1), ("resume", [103, 102, 101, 9001, 9002], 1)):
            with self.subTest(failure=failure):
                self.api.kernel, self.api.user = FakeKernel(), FakeUser()
                self.api.kernel.failure = failure
                with self.assertRaises(OSError):
                    self.create()
                self.assertEqual(self.api.kernel.closed, closed)
                self.assertEqual(self.api.kernel.attributes_deleted, attribute_deletions)
                self.assertEqual(self.api.user.closed, [8001])

    def test_timeout_ownership_and_bounded_wait(self):
        child = self.create()
        self.api.kernel.running = True
        with self.assertRaises(subprocess.TimeoutExpired):
            child.wait(2)
        self.assertEqual(self.api.kernel.last_wait, (9001, 2000))
        with self.assertRaises(subprocess.TimeoutExpired):
            child.wait(100)
        self.assertEqual(self.api.kernel.last_wait, (9001, 15000))
        with self.assertRaisesRegex(OSError, "while probe is running"):
            child.close()
        self.assertEqual(self.api.user.closed, [])
        child.kill()
        self.assertEqual(self.api.kernel.killed, [(9001, 1)])
        self.assertEqual(child.wait(3), 7)
        child.close()
        self.assertTrue(child.closed)

    def test_wait_failure_is_not_exit_success(self):
        child = self.create()
        self.api.kernel.wait_result = hidden.WAIT_FAILED
        with self.assertRaisesRegex(OSError, "WaitForSingleObject"):
            child.poll()
        self.api.kernel.wait_result = hidden.WAIT_OBJECT_0
        child.close()

    def test_null_environment_values_reject_before_process_creation(self):
        self.env["BAD"] = "contains\0null"
        with self.assertRaisesRegex(ValueError, "environment"):
            self.create()
        self.assertEqual(self.api.kernel.created, [])
        self.assertEqual(self.api.kernel.closed, [103, 102, 101])
        self.assertEqual(self.api.user.closed, [8001])


if __name__ == "__main__":
    unittest.main()

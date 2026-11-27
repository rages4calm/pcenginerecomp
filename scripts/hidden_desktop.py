"""One owned Windows child on a private, never-switched desktop.

Window/focus isolation only: the physical GPU and its driver remain shared.
Independently implemented against the Win32 desktop/process API contracts.
"""
import ctypes
import os
import subprocess
import uuid

DWORD = ctypes.c_uint32
HANDLE = ctypes.c_void_p
SIZE_T = ctypes.c_size_t
DESKTOP_ACCESS = 0x0001 | 0x0002 | 0x0004 | 0x0040 | 0x0080
DESKTOP_SWITCHDESKTOP = 0x0100
STARTF_USESTDHANDLES = 0x0100
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_NO_WINDOW = 0x08000000
CREATE_SUSPENDED = 0x00000004
PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
WAIT_OBJECT_0, WAIT_TIMEOUT, WAIT_FAILED = 0, 258, 0xFFFFFFFF


class STARTUPINFO(ctypes.Structure):
    _fields_ = [("cb", DWORD), ("lpReserved", ctypes.c_wchar_p), ("lpDesktop", ctypes.c_wchar_p),
                ("lpTitle", ctypes.c_wchar_p), ("dwX", DWORD), ("dwY", DWORD), ("dwXSize", DWORD),
                ("dwYSize", DWORD), ("dwXCountChars", DWORD), ("dwYCountChars", DWORD),
                ("dwFillAttribute", DWORD), ("dwFlags", DWORD), ("wShowWindow", ctypes.c_uint16),
                ("cbReserved2", ctypes.c_uint16), ("lpReserved2", ctypes.c_void_p),
                ("hStdInput", HANDLE), ("hStdOutput", HANDLE), ("hStdError", HANDLE)]


class STARTUPINFOEX(ctypes.Structure):
    _fields_ = [("StartupInfo", STARTUPINFO), ("lpAttributeList", ctypes.c_void_p)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", HANDLE), ("hThread", HANDLE), ("dwProcessId", DWORD), ("dwThreadId", DWORD)]


def _error(operation):
    code = ctypes.get_last_error()
    return OSError(code, operation+": "+ctypes.FormatError(code))


class WindowsApi:
    def __init__(self):
        if os.name != "nt":
            raise OSError("Isolated Windows desktops are unavailable on this platform")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        signatures = [
            (self.user.CreateDesktopW, HANDLE, [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_void_p, DWORD, DWORD, ctypes.c_void_p]),
            (self.user.CloseDesktop, ctypes.c_int, [HANDLE]),
            (self.kernel.GetCurrentProcess, HANDLE, []),
            (self.kernel.DuplicateHandle, ctypes.c_int, [HANDLE, HANDLE, HANDLE, ctypes.POINTER(HANDLE), DWORD, ctypes.c_int, DWORD]),
            (self.kernel.CloseHandle, ctypes.c_int, [HANDLE]),
            (self.kernel.InitializeProcThreadAttributeList, ctypes.c_int, [ctypes.c_void_p, DWORD, DWORD, ctypes.POINTER(SIZE_T)]),
            (self.kernel.UpdateProcThreadAttribute, ctypes.c_int, [ctypes.c_void_p, DWORD, SIZE_T, ctypes.c_void_p, SIZE_T, ctypes.c_void_p, ctypes.c_void_p]),
            (self.kernel.DeleteProcThreadAttributeList, None, [ctypes.c_void_p]),
            (self.kernel.CreateProcessW, ctypes.c_int, [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_int, DWORD, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.POINTER(STARTUPINFOEX), ctypes.POINTER(PROCESS_INFORMATION)]),
            (self.kernel.WaitForSingleObject, DWORD, [HANDLE, DWORD]),
            (self.kernel.GetExitCodeProcess, ctypes.c_int, [HANDLE, ctypes.POINTER(DWORD)]),
            (self.kernel.TerminateProcess, ctypes.c_int, [HANDLE, ctypes.c_uint]),
            (self.kernel.ResumeThread, DWORD, [HANDLE]),
        ]
        for function, result, arguments in signatures:
            function.restype, function.argtypes = result, arguments

    def create_desktop(self, name):
        desktop = self.user.CreateDesktopW(name, None, None, 0, DESKTOP_ACCESS, None)
        if not desktop:
            raise _error("CreateDesktopW")
        return desktop

    def close_desktop(self, handle):
        if not self.user.CloseDesktop(handle):
            raise _error("CloseDesktop")

    def close_handle(self, handle):
        if not self.kernel.CloseHandle(handle):
            raise _error("CloseHandle")

    def spawn(self, args, env, desktop_name, stdout, stderr):
        import msvcrt
        # Duplicate just our three stdio handles. Do not make the caller's file
        # handles inheritable or change process-global standard handles.
        duplicated = []
        attribute_buffer = None
        attributes_initialized = False
        process = PROCESS_INFORMATION()
        transferred = False
        try:
            with open(os.devnull, "rb") as stdin:
                for stream in (stdin, stdout, stderr):
                    duplicate = HANDLE()
                    current = self.kernel.GetCurrentProcess()
                    if not self.kernel.DuplicateHandle(current, msvcrt.get_osfhandle(stream.fileno()), current,
                                                       ctypes.byref(duplicate), 0, True, 2):
                        raise _error("DuplicateHandle")
                    duplicated.append(duplicate.value)
            size = SIZE_T()
            self.kernel.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
            if not size.value or size.value > 65536:
                raise _error("InitializeProcThreadAttributeList size")
            attribute_buffer = ctypes.create_string_buffer(size.value)
            if not self.kernel.InitializeProcThreadAttributeList(attribute_buffer, 1, 0, ctypes.byref(size)):
                raise _error("InitializeProcThreadAttributeList")
            attributes_initialized = True
            handles = (HANDLE*len(duplicated))(*duplicated)
            if not self.kernel.UpdateProcThreadAttribute(attribute_buffer, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                    handles, ctypes.sizeof(handles), None, None):
                raise _error("UpdateProcThreadAttribute handle list")
            startup = STARTUPINFOEX()
            startup.StartupInfo.cb = ctypes.sizeof(startup)
            startup.StartupInfo.lpDesktop = desktop_name
            startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES
            startup.StartupInfo.hStdInput, startup.StartupInfo.hStdOutput, startup.StartupInfo.hStdError = duplicated
            startup.lpAttributeList = ctypes.addressof(attribute_buffer)
            command = ctypes.create_unicode_buffer(subprocess.list2cmdline(list(map(str, args))))
            entries = sorted(env.items(), key=lambda pair: pair[0].upper())
            if any("\0" in key+value or "=" in key[1:] for key, value in entries):
                raise ValueError("Invalid process environment")
            environment = ctypes.create_unicode_buffer("".join(key+"="+value+"\0" for key, value in entries)+"\0")
            flags = EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT | CREATE_NO_WINDOW | CREATE_SUSPENDED
            if not self.kernel.CreateProcessW(str(args[0]), command, None, None, True, flags,
                    environment, str(os.path.dirname(args[0])), ctypes.byref(startup), ctypes.byref(process)):
                raise _error("CreateProcessW")
            # Release temporary inheritance state before handing ownership to
            # the caller. An error still leaves the exact created process here
            # for bounded cleanup, never an untracked running probe.
            self.kernel.DeleteProcThreadAttributeList(attribute_buffer)
            attributes_initialized = False
            while duplicated:
                self.close_handle(duplicated[-1])
                duplicated.pop()
            if self.kernel.ResumeThread(process.hThread) == 0xFFFFFFFF:
                raise _error("ResumeThread")
            self.close_handle(process.hThread)
            process.hThread = None
            transferred = True
            return process.hProcess, process.dwProcessId
        finally:
            cleanup_errors = []
            if process.hProcess and not transferred:
                try:
                    if self.poll(process.hProcess) is None:
                        self.kill(process.hProcess)
                        self.wait(process.hProcess, 3)
                except (OSError, subprocess.TimeoutExpired) as error:
                    cleanup_errors.append(str(error))
                for handle in (process.hProcess, process.hThread):
                    if handle:
                        try:
                            self.close_handle(handle)
                        except OSError as error:
                            cleanup_errors.append(str(error))
            if attributes_initialized:
                self.kernel.DeleteProcThreadAttributeList(attribute_buffer)
            for handle in reversed(duplicated):
                try:
                    self.close_handle(handle)
                except OSError as error:
                    cleanup_errors.append(str(error))
            if cleanup_errors:
                raise OSError("Isolated process creation cleanup failed: "+"; ".join(cleanup_errors))

    def poll(self, process):
        result = self.kernel.WaitForSingleObject(process, 0)
        if result == WAIT_TIMEOUT:
            return None
        if result != WAIT_OBJECT_0:
            raise _error("WaitForSingleObject")
        code = DWORD()
        if not self.kernel.GetExitCodeProcess(process, ctypes.byref(code)):
            raise _error("GetExitCodeProcess")
        return code.value

    def wait(self, process, timeout):
        result = self.kernel.WaitForSingleObject(process, max(0, min(int(timeout*1000), 15000)))
        if result == WAIT_TIMEOUT:
            raise subprocess.TimeoutExpired("owned isolated desktop probe", timeout)
        if result != WAIT_OBJECT_0:
            raise _error("WaitForSingleObject")
        return self.poll(process)

    def kill(self, process):
        if not self.kernel.TerminateProcess(process, 1):
            if self.poll(process) is None:
                raise _error("TerminateProcess")


class IsolatedProcess:
    """Popen-shaped ownership of one process and one private desktop handle."""
    def __init__(self, args, *, stdout, stderr, env, api=None):
        self.api = api or WindowsApi()
        self.desktop_name = "PceProbe_"+uuid.uuid4().hex
        self.desktop = self.api.create_desktop(self.desktop_name)
        self.process, self.pid, self.closed = None, None, False
        try:
            self.process, self.pid = self.api.spawn(args, env, self.desktop_name, stdout, stderr)
        except BaseException:
            self.api.close_desktop(self.desktop)
            self.closed = True
            raise

    def poll(self):
        return self.api.poll(self.process)

    def wait(self, timeout):
        return self.api.wait(self.process, timeout)

    def kill(self):
        self.api.kill(self.process)

    def close(self):
        if self.closed:
            return
        if self.process is not None:
            if self.poll() is None:
                raise OSError("Cannot close desktop ownership while probe is running")
            self.api.close_handle(self.process)
            self.process = None
        if self.desktop is not None:
            self.api.close_desktop(self.desktop)
            self.desktop = None
        self.closed = True

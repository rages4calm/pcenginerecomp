# Bounded display probes and Windows diagnostics

`scripts/gpu_probe.py` runs one authored `pce-display-probe` executable and
retains the exact executable/DLL hashes, command, stdout, stderr, frame and
receipt in a new private directory. It never launches game media, changes driver
settings, modifies Event Viewer logs or stops another application.

Build the toolkit's optional SDL desktop targets first. The default probe uses
SDL's CPU software renderer and dummy display. It does not exercise GPU shaders.

```powershell
python scripts/gpu_probe.py build/pce-display-probe.exe --out .local/display-software
```

Physical GPU work requires an explicit backend and authorization flag. These
examples are separate alternatives, not a stress-test loop. Run one, review its
receipt, and stop if it fails.

```powershell
python scripts/gpu_probe.py build/pce-display-probe.exe --backend direct3d12 --shader crt --allow-hardware --isolated-desktop --out .local/display-d3d12
python scripts/gpu_probe.py build/pce-display-probe.exe --backend vulkan --shader sharp --allow-hardware --isolated-desktop --out .local/display-vulkan
```

The authored executable owns its hidden window and finite rendering scope.
The wrapper starts only one rendering child, uses an eight-second execution deadline by
default, and accepts `--timeout` only within 1–15 seconds. A deadline, graphics
event or lost event monitoring terminates only that owned process. No backend
fallback or automatic retry occurs. Lifecycle JSONL records are flushed to disk
before proceeding. The receipt records whether the process was closed.
Before launch, `launch.json` durably records the intended command and exact
executable/DLL hashes. A wrapper interruption may leave only this manifest and
the flushed lifecycle prefix. They establish intent and partial observations,
not successful execution. Diagnostic queries each have their own finite timeout;
the rendering deadline does not include preflight or post-run diagnostics.

On Windows, bounded read-only PowerShell queries collect video-controller
identity, driver version and any running WoW processes before the test. A running
WoW process skips physical testing. Unavailable or truncated preflight telemetry
blocks physical testing. Other GPU-heavy applications are not automatically
identified; close them or use CPU testing when stability is uncertain.

System Display, NVIDIA/AMD driver and selected DxgKrnl events are retained along
with Application Error/Hang and Windows Error Reporting events. The wrapper
samples events during longer child execution and waits two seconds after exit
for promptly recorded errors. New driver errors, display-reset reports or
graphics-related WER reports fail the run even when rendering returned success.
Raw before/during/after reports preserve the event provider, record ID, timestamp
and message. Missing telemetry is reported as unavailable, never an empty clean
event log. Software probes can pass without Windows telemetry and explicitly
record that limitation.

This is a correlation aid, not a crash-proof sandbox. Hidden windows still use
the system graphics stack during hardware tests. A driver reset can affect the
desktop, and a watchdog cannot guarantee recovery from a kernel or desktop hang.
Delayed events may arrive after the observation window. Driver identity and
nearby errors do not establish which application or driver defect caused them.
Physical-driver qualification requires physical testing; SDL software rendering
does not establish GPU or shader compatibility. A separate test machine provides
stronger isolation from the owner's desktop.

## Separate Windows desktop

`--isolated-desktop` uses a unique, private Win32 desktop for this one probe.
It does not switch the input desktop or change the owner's active desktop.
The process receives that desktop through `STARTUPINFOEX.lpDesktop`. Only
explicitly duplicated stdin/stdout/stderr handles are inherited; the wrapper
does not make its original file handles inheritable. It creates the child
suspended until temporary inheritance state is released, then resumes exactly
that primary thread. Its process handle owns timeout and termination, and the
desktop handle is closed after the process exits. Desktop-closure failures
remain failed receipts. No renderer/backend fallback is allowed if desktop
creation fails.

This keeps test windows and focus separate from the visible desktop. It does
**not** isolate the physical graphics adapter, Windows graphics kernel or driver
from other programs. The WoW guard and graphics-event monitoring still apply.
The implementation is independent and follows Microsoft's
[desktop creation](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-createdesktopw),
[process creation](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw)
and [explicit handle-list](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)
contracts. The launcher remains unchanged.

All logs and images stay private under `.local/`. Preserve failed receipts as
failed. Do not publish personal process identifiers, paths or driver reports.

# Legacy media process bounds and cancellation

The renderer, metadata probing, review-frame extraction and per-frame mask audit
now share a bounded pipe transport. Both stdout and stderr are drained in parallel.
Stdout is checked before forwarding each chunk to a consumer or retaining it.
Its caller-specified cap is unchanged (2 MiB by default; PNG uses 16 MiB).
Diagnostics have a 64 KiB limit and any stderr still rejects a nominally successful
media process. Diagnostic contents are never returned. Per-frame audit no longer
writes decoder diagnostics to an unbounded temporary file. RGB decode is limited
to exactly `width * height * 3 * frame_count` bytes and retains one frame plus
bounded transport chunks, not a whole decoded video. Nonblack mask pixels still
raise `MaskMismatch` with the same location and CLI exit code 3.

The transport queue contains at most eight 64 KiB chunks. Each reader and the
consumer can additionally hold a chunk; the stdout return buffer and current RGB
frame have their separate explicit caps. Pipe/kernel buffers and decoder memory
are not included. This is **not a memory or filesystem sandbox** for FFmpeg.
A trusted local FFmpeg installation remains required.

The 120-second wall-clock deadline includes process execution and pipe drainage;
closing pipes while continuing to run does not disable it. Cleanup additionally
allows up to two seconds for direct-child reaping and two seconds for readers.
Cancellation scopes stay active through legacy workflow scratch-directory cleanup.
Main-thread workflows install cancellation handlers. Background callers retain
bounded transport and exception cleanup, but do not install signal handlers;
Python delivers signals to the main thread, so callers must not assume a signal
synchronously cancels background work. CLI behavior is unchanged.

## POSIX

Tools start in a new session. Timeout, overflow, a sink exception, SIGINT/SIGTERM,
and normal completion kill the owned process group and reap the direct child.
The spawn/ownership transition defers catchable cancellation. A descendant that
intentionally escapes the group/session is not contained. SIGKILL, machine loss,
or an uninterruptible kernel operation cannot promise cleanup.

## Windows boundary

Legacy media operation is not disabled: the bounded reader-thread transport and
direct-child terminate/reap path are portable. **No Windows Job Object is installed.**
Descendant-tree termination is not guaranteed. If a tool spawns a descendant that
retains pipe handles, the deadline still returns an error and direct-child cleanup
is bounded, but daemon readers and descendant processes can outlive the operation.
This may also prevent Windows scratch deletion. Do not treat this as safe execution
of untrusted binaries or as verified whole-tree cleanup. Existing POSIX-only OCR
restrictions are unchanged. Native Windows execution has not been verified here;
a Linux test of the Windows code branch is only a control-flow check, not Windows QA.

## Validation

Only synthetic media and finite synthetic subprocesses are used. The baseline
transport was observed to retain 4 MiB stdout and 1 MiB stderr before rejecting a
stdout limit of 8 bytes. Regression tests now cover exact/overflow output, finite
stderr floods, process failure, close-pipes-then-sleep timeout, exception identity,
spawn-time cancellation, POSIX descendants, and existing real FFmpeg mask checks.

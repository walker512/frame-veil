# Resumable bounded multi-batch OCR (0.7.0)

This workflow removes the **24-frame single-invocation ceiling** by scanning an
explicit interval as multiple independently verified chunks. It does **not**
remove the existing source limits: local H.264 MP4/MOV, square pixels, no rotation,
at most 64 MiB and 1,800 frames. At 30 fps, 1,800 frames is only one minute.
This is not unrestricted long-video ingestion, automatic tracking, mask merging,
a GUI, or complete anonymization.

## Reproduce without private recordings or API keys

```sh
python -m examples.batch_text_synthetic batch-demo

# Read-only cost estimate. No OCR or output directory is created.
python -m frame_veil.batch_ocr estimate batch-demo/synthetic.mp4 --terms batch-demo/terms.json --regions batch-demo/regions.json --start 0 --end 32

python -m frame_veil.batch_ocr init batch-demo/synthetic.mp4 --terms batch-demo/terms.json --regions batch-demo/regions.json --start 0 --end 32 --out batch-evidence
python -m frame_veil.batch_ocr run batch-demo/synthetic.mp4 batch-evidence --max-chunks 2
python -m frame_veil.batch_ocr status batch-evidence
# A later process resumes; already verified chunks are not OCR'd again.
python -m frame_veil.batch_ocr run batch-demo/synthetic.mp4 batch-evidence --max-chunks 2
python -m frame_veil.batch_ocr status batch-evidence
```

The fixture is 32 frames / 16 seconds at 2 fps, with fictional notices only on
frames 1 and 25. Four 8-frame chunks retain real images, TSV and candidates.
This tests crossing a chunk boundary, not performance on hours of footage.
The source is never stored inside the evidence directory, and no network service
or model download is involved.

## Explicit budgets

- `--start` and `--end` are required half-open absolute decoded-frame bounds.
- `--chunk-size` defaults to 8, accepts 1–24; at most 256 chunks.
- Each chunk keeps the existing 64-call, RGB, derived-pixel, TSV and candidate
  limits. `--pair-unthresholded` expands regions **before** calculating bounds.
  Large/upscaled crops can require a smaller explicit chunk size.
- `--max-disk-bytes` defaults to 1 GiB; the hard ceiling is 32 GiB. Run
  `estimate` first. It reports a conservative upper bound, including worst-case
  per-call TSV and bounded JSON, and whether the requested budget is sufficient.
  The estimate probes metadata but does not run OCR. No automatic budget increase
  or disk reservation occurs.
- Initialization refuses a configuration whose estimated complete retained
  evidence exceeds the chosen budget. Before each chunk, actual retained bytes
  (including abandoned attempts) plus that chunk's upper bound are checked again.
  Private transient source/decoder snapshots outside the evidence directory are
  not included in this retained-evidence budget. Filesystem free space may still
  run out; a byte budget is not a quota or guarantee of available space.
- A `run` processes at most `--max-chunks` (default 1, allowed 1–8), then
  returns. Invoke it again deliberately; there is no background infinite loop.
  Per-process media/OCR deadlines remain in force. These are not hard wall-clock
  guarantees against uninterruptible operating-system or filesystem operations.
- Each chunk reopens and decodes the source. Late chunks may repeat considerable
  decoding work; this favors bounded/resumable evidence over high-throughput
  streaming. No benchmark against competing video tools is claimed.

## Resume and failure semantics

The plan binds the source SHA-256, dimensions/frame count, immutable retained
term/config bytes, explicit chunk intervals and budget. Every resume rereads the
source and revalidates **all completed chunks** against the plan. Changed source,
changed configuration, corrupt completed evidence or unexpected final members
fail closed. Restoring the same bytes is not a cryptographic provenance guarantee.

A POSIX file lock prevents simultaneous cooperating runners. Each chunk is built
in a private attempt directory, then independently validated before same-filesystem
rename to its final `chunks/chunk-NNNN` directory. A normal failure preserves
earlier successful chunks; a subsequent invocation retries only missing chunks.
Catchable SIGINT/SIGTERM now trigger controlled exception unwinding on the main
thread: the active OCR/media process group is stopped and the direct child waited
for, then private temporary contexts are cleaned up before returning failure.
Previously completed chunks remain valid and missing chunks can be resumed.
SIGKILL or a crashed process cannot execute that cleanup. Its kernel lock is
released, but child tools and private scratch/partial attempts may remain:
`status` reports `abandoned_attempts`, does not treat it as completed, and
`run` includes its bytes in budget checks. The tool does not silently delete
files or trust partial output. Inspect any abandoned attempt locally and decide
whether to retain it; a new attempt may be needed. A corrupt final chunk is not
automatically deleted or overwritten.

This is catchable-signal/process-interruption recovery on a trusted local POSIX filesystem, not
power-loss durability, distributed locking, protection from a malicious same-user
process/hostile parent-directory replacement or Windows ACL support. Output
directories are created 0700 and files 0600. Status counts and intervals can be
sensitive; do not publish private evidence or search configuration.

## Actual review boundary

`status` separates verified completed ranges, pending ranges and ranges outside
the user's request. `all_requested_frames_scanned` only means all requested
frames have internally consistent OCR evidence. It does not mean text was
recognized correctly, all risks were requested, masks were applied, or anyone
watched the video. `privacy_complete` remains false.

Each completed chunk is a normal region scan:
```sh
python -m frame_veil.region_ocr coverage batch-evidence/chunks/chunk-0000
python -m frame_veil.region_ocr prepare batch-evidence/chunks/chunk-0000 --out chunk-0000-decisions.json
```
Inspect actual frames/TSV, supply explicit human decisions and use the existing
source-bound plan/render/audit workflow. The batch runner does not infer durations,
merge masks from different chunks or certify combined output. A whole-source
reviewed masking plan must be prepared separately and audited. Until then this is
a **resumable evidence-collection workflow**, not end-to-end long-video redaction.

The synthetic tests check two-stage resume without redoing completed OCR, actual
OS-process termination and lock release, retained completed evidence after failure,
source/config/evidence tampering, budget rejection, private permissions, read-only
estimate, and offline status. No real private media or full-video privacy
certification is involved.

Executed local validation after cancellation hardening: 137 tests passed, zero
skips, including 10 batch tests and 5 cancellation tests; compileall passed. The real process-termination test completes its first
8-frame chunk, terminates the runner during the next attempt, verifies the first
chunk remains valid and the next remains pending, then resumes in another run.
These results cover this local POSIX/synthetic setup only.

### Active-tool cancellation validation

The cancellable OCR, region and batch workflows require Python's main thread;
worker-thread calls are rejected before launching tools. SIGINT/SIGTERM handlers
are scoped, nested scopes share the same cancellation state, and prior handlers
are restored. Delivery during process creation is deferred until the child is
owned by a cleanup block, without blocking signals in the tool itself. A second
catchable signal does not interrupt cleanup once cancellation has begun.

The added tests observe actual FFmpeg alive before SIGTERM and actual Tesseract
alive before SIGINT, then verify process termination and private image/scratch
removal. A separate batch test cancels a real running controlled tool process
and its same-group child during a genuine second-chunk OCR workflow, checks that
source/config/frame temporary directories and the unpublished attempt are gone,
retains the first verified chunk, and successfully resumes the pending chunk.
This controlled process-tree test is not a claim about arbitrary Tesseract
descendants or tools that deliberately detach into new process groups.

SIGKILL, power loss, uninterruptible kernel operations, filesystem cleanup errors
and hostile tools remain outside this cleanup guarantee. Do not assume secure
disk erasure or that an abruptly killed runner has stopped every external
process. Inspect retained attempts/processes before continuing after such events.

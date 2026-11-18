# Frame Veil historical development notes

These are historical capability and validation notes preserved from the README at public commit `a87372409dfaa58d3eea0607c9ef1a3c45fd8ed6`. Test totals describe their individual stages, not separate current suites or new test runs. Version labels do not establish package-registry releases. See [README](README.md) for current usage, limits and the latest recorded validation. No unpublished interface is included here.

## Earlier manual rendering and pixel audit

The original workflow provided explicit frame-bound masking, silent FFV1 output, source-hash binding and decoded review frames. The 0.1.1 pixel-audit increment recorded 33 Linux synthetic tests, including declared-mask tampering, frame boundaries and decoder-failure handling. These checks did not certify complete privacy removal or authenticity.

## Optional selective audio muting (0.2.0)

[Selective audio](docs/SELECTIVE_AUDIO.md) binds manual sample intervals to the same source as the frame masks, preserves normalized PCM outside those intervals, and produces a listenable WAV plus the combined recording. Its verifier checks the final audio samples and the actual combined video masks. Default all-audio removal remains unchanged. Real synthetic mono/stereo tests exercise the whole flow; unmarked speech remains private until you review it.

## Human review before export (0.2.1)

The optional `review-prepare` → `review-decide` → `review-export` CLI workflow requires explicit decisions for every output video segment (text, faces, notifications/other) and retained audio segment. It binds all bundle bytes, rejects stale/missing/blocked decisions, and re-audits the actual media before exporting that exact snapshot. See [the complete local workflow and limits](docs/HUMAN_REVIEW.md). It records declarations, **not proof of viewing, privacy safety or publication consent**; existing render commands remain available. Playback is external, not an accepted interactive workstation.

Local validation for this increment: the public suite includes actual synthetic-media review/export and failure-path tests. No new browser or cross-platform run is claimed.

## Optional explicit-word OCR candidates (0.3.0)

[Local OCR candidates](docs/OCR_CANDIDATES.md) decode explicitly selected frames, run installed English Tesseract, retain private image/TSV evidence, and require explicit human decisions before generating an existing mask plan. Zero matches and unselected frames are never privacy clearance. Full intermediate frames and recognized text are sensitive; nothing is uploaded. The original render/audio/review code and policies remain unchanged. This increment is a CLI workflow, not accepted screenshot/GUI editing or whole-recording recognition.

0.3.0 verification: **88 tests passed, zero skips**, Linux/Python 3.12 with FFmpeg 7.1.5 and Tesseract 5.5.0/English. The original 64 tests and core/audio/review modules are unchanged. A separate real synthetic CLI run detected fictional names, generated explicit one-frame masks, rendered/audited 13,312 rectangle pixels and prepared a still-pending human review. It also missed a notification-like box, as disclosed in the OCR guide. No real student footage, Chinese or GUI acceptance is claimed.

## Explicit-region OCR (0.4.0)

Explicit regions, crop/resize evidence, optional raw-crop controls and coverage reporting extended selected-frame OCR. The notification example motivated a bounded second pass; zero matches did not clear privacy and no GUI or whole-recording detection was claimed. See [region OCR](docs/REGION_OCR.md).

### OCR artifact permissions (0.4.1)

Both selected-frame and explicit-region OCR now create scan and plan directories
with owner-only POSIX permissions (0700), and their evidence, decision, plan and
receipt files with 0600 from creation, even under umask 022 or 000. Existing
artifacts are never overwritten or automatically chmodded. Private scratch images
also use owner-only file creation. This does not fix copies previously generated
with broader permissions: keep those in an owner-only directory and review their
permissions before reuse. These are POSIX mode guarantees, not Windows ACL,
hostile-parent-directory, administrator-access or complete-video privacy guarantees.
That 0.4.1 change covered OCR only. The 0.7.1 hardening below also covers manual media and human-review outputs.

## Resumable multi-batch evidence collection (0.7.0)

The [batch workflow](docs/BATCH_OCR.md) can scan an explicit interval in bounded,
resumable chunks, with read-only disk estimates, source/config binding, verified
completed/pending ranges and process-interruption recovery. It crosses the
single-scan 24-frame limit but **retains the source limits of 64 MiB / 1,800
frames**. It is evidence collection, not automatic mask merging or unrestricted
long-video redaction. Each run is explicitly bounded and human review remains
required.

## Private media and human-review outputs (0.7.1)

Manual render bundles, PNG previews, selective-audio bundles (including nested
video, WAV and combined MKV), human review/decision JSON and reviewed exports now
use owner-only POSIX directories (0700) and files (0600) from creation. They share
the same exclusive private-file writer as OCR. Audio publication copies only the
known bounded file set with private creation, rather than relying on permissions
being corrected after a directory tree copy. FFmpeg/ffprobe launched through the
manual media runner get a child-only umask 077, so their scratch output files are
also private without changing the parent process's umask.

Existing input/output permissions are not automatically changed, and existing
output leaves are not overwritten. Previously created copies may still have
broader permissions: review them locally before reuse or sharing. This is a POSIX
access-mode improvement, not Windows ACL validation, encryption, secure erasure,
protection from administrators/hostile parent directories, or proof that the
recording is free of unmarked private content. Even a reviewed export remains
private by default and is not publication authorization.

Local 0.7.1 validation: 140 tests passed, zero skips. Three new tests exercise
real render/preview/audio/review/export outputs under umask 022 and 000, check
tool-created scratch media permissions, preserve the parent umask, and refuse
existing/symlink review output leaves. Existing decoded-pixel/sample audits and
all OCR cancellation/resume regressions remain passing. No real private media was
used; no Windows ACL or broader security certification is claimed.

## Compose reviewed batch plans (0.8.0)

Finishing a batch scan is not the same as producing a complete redacted video.
Use the new explicit composition step when you have several **region OCR** plans
already created from accepted/dismissed human decisions. It revalidates the scan
artifacts, binds each plan to the exact source hash, and reconstructs each plan
and receipt from its decisions before combining the masks. It never accepts a
pending decision or auto-extends a rectangle/time interval. Overlapping masks
are kept in input order, not silently deduplicated or geometrically merged.

Create a local `selection.json` listing the scan and corresponding reviewed plan
directories. Relative paths resolve from the selection file's directory:

```json
[
  {"scan":"batch/chunks/chunk-0000","plan":"reviewed-plan-0000"},
  {"scan":"batch/chunks/chunk-0003","plan":"reviewed-plan-0003"}
]
```

```sh
python -m frame_veil.merge_plans create source.mp4 selection.json --out combined
python -m frame_veil.merge_plans verify source.mp4 selection.json combined
python -m frame_veil render source.mp4 combined/plan.json --out redacted
python -m frame_veil audit-masks redacted
```

Then use the existing human-review workflow to watch the complete output before
sharing. The command does not automatically run rendering or approve the result.
Installed users can also invoke `frame-veil-merge`.

The combined directory contains the render-compatible `plan.json`, exact copies
of selected plans/decisions/receipts, and `merge-receipt.json`. The receipt lists
input hashes, source binding, mask index ranges, frames not observed by the
**selected scans**, and frames without any declared mask. Ranges are zero-based,
start-inclusive/end-exclusive. A missing-range list is not a list of sensitive
frames, and an empty list is not a privacy clearance. Observing one region or one
term does not establish the safety of the rest of a frame.

You explicitly choose the inputs: the command cannot infer that every batch was
included. A scan with no accepted candidates has no mask plan and is not silently
counted as safe. All selected candidates must have explicit accept/dismiss
records, but that does not prove a human actually viewed them. Composition
verification needs the source and selected scan/plan directories; it rereads and
validates artifacts without rerunning OCR or authenticating historical execution.
Keep those local inputs if you need to reproduce the check.

Limits remain explicit: 1–16 selected plans, at most 100 combined masks, source
at most 64 MiB and 1,800 frames. Exceeding bounds fails rather than dropping masks.
New artifacts use POSIX 0700/0600 permissions, no existing destination is replaced,
and failed writes may leave private incomplete output which will not verify.
No automatic tracking, unknown-text detection, arbitrary-length processing,
Windows ACL assurance or privacy certification is added.

### Media subprocess safety update

Legacy rendering and frame auditing now bound both pipe streams while running,
with cancellation-safe direct-child ownership and POSIX process-group cleanup.
See [process limits and Windows boundaries](docs/PROCESS_LIMITS.md). Windows legacy
media paths remain available, but native Windows QA and descendant-tree termination
are not claimed. Signal-managed cancellation requires the main thread; no decoder sandbox is implied.

## Optional staged publication for silent renders

`render ... --staged` prepares and verifies a complete private sibling bundle
before no-replace publication. `publish-render STAGED_BUNDLE --out FINAL` retries
a complete stage without rendering again. Partial stages are retained and require
fresh rendering; nothing is recursively cleaned up. **Default output commands
remain nontransactional**, including audio and review export. See
[staging, platform capabilities and recovery limits](docs/STAGED_PUBLICATION.md).
This is not power-loss durability, hostile same-account isolation or privacy
certification. Windows native behavior and ACLs remain untested for this addition.

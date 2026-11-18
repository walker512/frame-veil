# Frame Veil

**Create a separately reviewable recording copy with frame-bound opaque masks and explicit audio handling.**

Frame Veil is a local CLI for recordings you are authorized to process. Bind a manual mask plan to the exact source, render a new copy, inspect the result, and record human review before an optional guarded export. The original recording is never overwritten or included in the result bundle.

**This is not automatic privacy clearance or an interactive editing workstation.** There is no built-in video player, box-drawing UI or motion tracker. Use a trusted external player to watch and listen to the entire processed recording. Successful commands, OCR results and completed checklists do not grant publication consent.

## Current capabilities

| Workflow | What it does | Boundary |
| --- | --- | --- |
| Manual masking | Opaque black rectangles over exact decoded-frame intervals; lossless video output | Unmarked pixels remain visible; no blur or automatic tracking |
| Audio handling | Default render removes all audio; optional sample-range muting preserves reviewed narration | Unmarked speech can remain sensitive |
| Mask/sample audit | Decodes actual output to check declared masks and mute intervals | Checks the plan, not whether all private material was identified |
| OCR assistance | Explicit words, selected frames, regions and optional crop/resize controls | Installed English Tesseract; missed text and unsampled frames are not clearance |
| Bounded batch collection | Resume source-bound OCR chunks and compose explicitly reviewed region plans | No automatic mask-duration extension or unlimited-length video |
| Human-review CLI | Pending/reviewed/blocked checks bound to exact bundle bytes; guarded local export | Declarations, not proof of watching or authenticated approval |
| Staged silent render | Verify a complete stage before no-replace publication; retry a complete stage without re-encoding | Opt-in, platform-dependent; not audio/review staging or power-loss durability |

See [historical changes](CHANGELOG.md) for the development sequence and older test counts. These are cumulative capabilities of the public source, not separate package-registry release claims.

## Requirements

- Python **3.11+**, with trusted local `ffmpeg` and `ffprobe` on `PATH`.
- Optional OCR: trusted local Tesseract with English data. No binary, font, model or third-party media is bundled.
- Source: local MP4/MOV, exactly one H.264 video, square pixels, no nonzero rotation metadata, at most 64 total streams.
- Limits: 64 MiB source, dimensions 2–1920 × 2–1080, and 1–1,800 decoded frames. Individual OCR operations have additional bounds documented below.
- Default output: FFV1/BGR0 video in Matroska (`.mkv`), at most 256 MiB. Use a compatible local player; browser-compatible MP4 playback is not promised.

From a source checkout, commands can run with `python -m frame_veil`. Optional installation:

```sh
python -m pip install .
```

This installs `frame-veil`, `frame-veil-regions` and `frame-veil-merge`. Building requires setuptools and may access your configured package source. Processing itself makes no network requests. FFmpeg/codecs and Tesseract retain their own licensing requirements.

## First run: synthetic media only

From the source checkout, using fresh output paths:

```sh
python -m examples.synthetic demo
python -m frame_veil inspect demo/synthetic.mp4
python -m frame_veil render demo/synthetic.mp4 demo/plan.json --out redacted-demo
python -m frame_veil verify redacted-demo
python -m frame_veil audit-masks redacted-demo
python -m frame_veil frame redacted-demo --index 4 --out frame-review
```

The original example generates a two-second red video and a 440 Hz tone. Rendering preserves ten frames, masks two rectangles over different intervals and removes the audio. Inspect `frame-review/review-frame.png`, then watch `redacted-demo/redacted.mkv` in a compatible player. The example generator is available from the checkout, not as an installed command.

## Your recording: inspect → plan → render → review

1. Keep a private backup and run `inspect SOURCE.mp4` to obtain its SHA-256, dimensions and decoded-frame count.
2. In a trusted external viewer, identify the exact rectangles and frame intervals. Write a plan:

```json
{
  "schema": 1,
  "source_sha256": "REPLACE_WITH_THE_64_LOWERCASE_HEX_DIGITS_FROM_INSPECT",
  "width": 96,
  "height": 64,
  "frames": 10,
  "masks": [
    {"start_frame": 2, "end_frame": 6, "x": 8, "y": 8, "width": 24, "height": 16}
  ]
}
```

The placeholder is intentionally invalid. Replace all source properties with the inspected values. Frames are zero-based decoded-frame indices, **not timestamps**. Intervals include the start and exclude the end. Coordinates are integer source pixels; 1–100 masks are accepted and overlap is allowed. Changing source bytes requires a new source-bound plan.

3. Render into a new directory, then verify and audit:

```sh
frame-veil render SOURCE.mp4 PLAN.json --out NEW_BUNDLE
frame-veil verify NEW_BUNDLE
frame-veil audit-masks NEW_BUNDLE
```

Default render removes audio, subtitles, data/attachment streams and chapters. Its bundle contains `redacted.mkv`, the exact `plan.json` and `receipt.json`; it does not copy the original recording. Metadata copying is disabled, but technical encoder/container metadata may remain. This is not forensic metadata-erasure certification.

`verify` checks structure, hashes and decoded media properties; `audit-masks` checks pixels inside declared masks. Neither establishes complete privacy removal or source authenticity. Even a wholly black video can pass a narrow mask check. Variable-frame-rate/edit-list timing has not been separately validated; frame intervals are not fixed-duration playback segments.

4. Watch the entire output, including unmasked areas and every boundary. For narrated recordings, follow [selective audio muting](docs/SELECTIVE_AUDIO.md), then listen to all retained audio as well.
5. Optionally use the [human-review and guarded-export CLI](docs/HUMAN_REVIEW.md). It creates all-pending segment checks, requires every category to be reviewed, rejects stale/blocked/missing decisions, and re-audits the exact media before export. It is not access control; files can still be copied outside this workflow. Obtain publication permission separately.

The original inspect/render/verify/frame commands return 0 for operation completion and 2 for invalid input or operational failure. Other commands have their own documented failure semantics. **Exit 0 is never permission to publish.**

## Workflow guides

- [Selected-frame, explicit-word OCR](docs/OCR_CANDIDATES.md): generate candidates and require human decisions.
- [Region OCR and coverage](docs/REGION_OCR.md): crop/resize evidence, optional raw control, bounded frame intervals and visible sampling gaps.
- [Resumable batch OCR](docs/BATCH_OCR.md): explicit source/config binding and completed/pending chunks, retaining the source limits above.
- [Selective audio](docs/SELECTIVE_AUDIO.md): manual sample intervals, normalized PCM preservation and combined-media verification.
- [Human review](docs/HUMAN_REVIEW.md): exact decision categories, segment bounds and guarded export.
- [Staged publication](docs/STAGED_PUBLICATION.md): silent-render no-replace output and complete-stage retry.
- [Process limits](docs/PROCESS_LIMITS.md): bounded subprocess output, deadlines, cancellation and Windows limitations.

To compose already-reviewed **region OCR** plans, write a selection JSON containing `scan` and `plan` directory pairs, then use:

```sh
frame-veil-merge create SOURCE.mp4 selection.json --out combined
frame-veil-merge verify SOURCE.mp4 selection.json combined
frame-veil render SOURCE.mp4 combined/plan.json --out redacted
```

Composition accepts 1–16 plans and at most 100 masks. It checks their source/decision bindings, retains explicit intervals and lists gaps; it does not select all batches for you, infer safe frames or approve privacy.

## Privacy, failures and platform boundaries

- Use only authorized media and trusted, updated local tools. No application API key, telemetry or upload is used. This is **not a decoder or OS sandbox**.
- Inputs use bounded regular-file reads and strict plan validation. URLs, leaf symlinks, special files and arbitrary FFmpeg expressions are not accepted as source/plan substitutes. Hostile parent-directory replacement and same-account attackers are outside the protection boundary.
- New media, OCR and review artifacts use POSIX 0700 directories and 0600 files. Existing outputs are never overwritten or silently chmodded. These mode bits do not establish Windows ACL privacy.
- Output media, OCR images/recognized text, hashes and review records may still be sensitive. Keep them private. Temporary cleanup is not secure erasure.
- Default final writes are not transactional: interrupted writes may leave partial folders. Verify before use and retry with fresh paths. Silent `render --staged` is a separate opt-in; retained stages require deliberate inspection and cleanup, even after success. It does not cover audio or review export.
- Staged publication supports a no-replace operation on supported Linux filesystems and a Windows path; other platforms reject that optional mode. Windows native behavior has not been validated. Legacy media functionality is not globally disabled on Windows.
- Media subprocesses have deadlines and bounded pipe capture. Cancellation cleanup and descendant handling vary by platform; Windows direct-child handling is not complete process-tree termination. Limits do not bound decoder memory or guarantee cleanup after SIGKILL, power loss or uninterruptible OS calls.

## Validation and comparison

The latest recorded public-source regression for commit `a87372409dfaa58d3eea0607c9ef1a3c45fd8ed6` was **175 tests passed, zero skips**, on Linux with synthetic media. This README reorganization does not constitute a new test run. Historical runs used Python 3.12, FFmpeg/ffprobe 7.1.5 and, for OCR, Tesseract 5.5.0/English; they do not establish a wider supported tool-version matrix.

Coverage includes real synthetic decoding/rendering, mask/sample checks, strict evidence validation, OCR decisions, batch interruption/recovery, plan composition, private output creation, process cancellation and staged-publication failures/races. Cross-device failure injection is not a real mounted cross-device test.

No current Windows/macOS native, Windows ACL, real private classroom, Chinese OCR, full-video detection or accepted interactive GUI validation is claimed. No new hosted-CI claim is made. Distribution metadata is currently `0.8.0`; the core module identifier remains `0.7.1`. These existing identifiers describe different surfaces and were not changed by this documentation edit; neither is evidence of a registry release.

[OpenScrub](https://github.com/austinmabry/OpenScrub) offers a broader visual review workflow; [simple-redact-video-tool](https://github.com/cclawton/simple-redact-video-tool) focuses on visual region/time editing; [deface](https://github.com/ORB-HD/deface) focuses on face anonymization. Consult their current documentation for scope. Frame Veil does not claim superior detection, usability, speed or privacy guarantees. Its narrower deliverable is explicit frame/sample plans, inspectable evidence and deterministic checks around human review.

MIT licensed. Public maintainer identity: **walker512**.

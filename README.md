# Frame Veil

**Make a separately reviewable recording copy with exact frame-bound opaque masks. All audio is removed.**

For an authorized screen recording, bind a manual rectangle plan to the source hash, render real lossless video, check frame/stream properties and export a decoded review frame. The original recording is never overwritten or included in the result bundle.

This is a manual privacy-editing CLI, not automatic detection or a complete visual editing workbench. It does not find names, passwords, faces, spoken information, notifications or unmarked privacy risks. **Human review of the whole output remains mandatory.**

## Requirements and supported media

- Python 3.11+ and a trusted local `ffmpeg`/`ffprobe` installation on `PATH`.
- Source: a local MP4/MOV container with exactly one **H.264** video, square pixels and no nonzero rotation metadata. At most **64 total streams** are accepted, including the video and every audio/subtitle/data/attachment stream; inspect, render and receipt verification use the same bound.
- Source file up to 64 MiB; width 2–1920, height 2–1080; 1–1,800 decoded video frames. Dimensions are pixel coordinates, not screen CSS coordinates.
- Output: lossless **FFV1, BGR0, Matroska `.mkv`**, up to 256 MiB. Use a player/editor that supports FFV1, such as a suitable local media application. This is not a browser-compatible MP4 export guarantee.
- Every subprocess has a 120-second deadline. Large or difficult media may exceed it and fail. The input-size limit is not a decoder memory sandbox.

No FFmpeg binary or third-party codec library is bundled. FFmpeg and its enabled codecs have their own licenses. This release has been exercised with FFmpeg 7.1.5 on Linux; no broader version/platform matrix is claimed.

## Try an entirely synthetic example

From the source checkout:

```sh
python -m examples.synthetic demo
python -m frame_veil inspect demo/synthetic.mp4
python -m frame_veil render demo/synthetic.mp4 demo/plan.json --out redacted-demo
python -m frame_veil verify redacted-demo
python -m frame_veil frame redacted-demo --index 4 --out frame-review
python -m unittest discover -s tests -v
```

The generator creates an original two-second red video and a 440 Hz tone. Its plan masks two overlapping rectangles at different frame intervals. The real render preserves ten frames and removes the audio track. Open `frame-review/review-frame.png` to inspect the two black rectangles on frame 4.

All output directories must be new. You can install the package with `python -m pip install .`, then use `frame-veil` instead of `python -m frame_veil`. Setuptools is required for the build. The `examples` module is run from the source checkout, not installed as a command. No package-registry release is implied.

## Work on your own authorized recording

1. Keep the original private and backed up. Use this only on media you are authorized to process.
2. Run `inspect SOURCE.mp4`. It returns width, height, decoded frame count and SHA-256, not source tags or filenames.
3. Using your own trusted video viewer/editor, identify the exact decoded frame ranges and pixel rectangles. There is no built-in box-drawing UI or face/OCR tracker. Do not assume a secret stays at a fixed location after scrolling or animation.
4. Write a plan using the exact hash and dimensions from inspect:

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

The placeholder hash deliberately is not valid; do not use it unchanged. A plan for any other source bytes is rejected. Changing a recording, even metadata, requires inspecting and reviewing a new plan.

5. Run `render SOURCE.mp4 PLAN.json --out NEW_DIRECTORY`. This makes a **new video copy**, never changes the source, and removes **all** audio, subtitles, data/attachment streams and chapters from the output mapping. There is no selective audio muting or retain-audio option in this release. For teaching material where narration is essential, this scope is not a complete solution.
6. Verify the result, then manually watch the entire redacted copy in a supporting player. Inspect frames around every mask boundary. `frame RESULT --index N --out NEW_DIRECTORY` extracts only from the processed copy, not the original.

`inspect`, `render`, `verify` and `frame` exit 0 on their documented operation completing, 2 on invalid/unsupported input, mismatch, timeout, unavailable tools or I/O failure. **Exit 0 does not mean the video is safe to publish.**

## Exact mask semantics

- Frames are indexed from zero in decoded video order. `[start_frame, end_frame)` includes the start and excludes the end. These numbers are **not timestamps, milliseconds or seconds**.
- Rectangles use integer pixels: `[x, x + width)` by `[y, y + height)` within the encoded, unrotated square-pixel frame.
- There may be 1–100 masks. Overlap is allowed; the union becomes opaque black. No blur, mosaic or transparency is used.
- All interpolated filter values are strictly validated integers. Plans cannot supply FFmpeg expressions, commands, URLs, file references or arbitrary filters.
- The renderer resets the first output video timestamp to zero and requests passthrough frame timing. It checks decoded frame count and dimensions after encoding. It does not claim timestamp identity with every source/container convention; variable-frame-rate and unusual edit-list playback have not been separately validated.
- Rotated media and non-square-pixel media must be normalized using a separate trusted workflow **before** inspect/plan creation. Do not reuse coordinates from an earlier version.

There is no automatic padding or motion tracking. Choose an appropriately generous region and frame interval, then verify it visually. Sensitive pixels outside your rectangles are intentionally preserved and may remain visible. Anything inside unmasked frames remains visible. A black rectangle is not automatic identity anonymization.

## Output and verification

A successful result directory contains exactly:

- `redacted.mkv`: rendered lossless video with one video stream and no audio.
- `plan.json`: the supplied plan bytes.
- `receipt.json`: source/plan/output hashes, numerical input/output properties, stream-type summary and explicit manual-review requirement.

No source video, original audio, user filename/path or copied source metadata text is included. Global and video-stream metadata copying are disabled, as are chapters; FFmpeg/Matroska may create technical encoder/container metadata of its own. This is not a forensic metadata-erasure certification.

`verify` checks the receipt structure and hashes, actually decodes/counts output video frames, confirms expected dimensions/codec and a single video-only stream, and revalidates the bound plan. It **does not** reopen the original source or rerender the masks, nor prove that the rectangles are adequate or actually match every intended private region. The test suite validates the renderer on synthetic pixels; bundle verification itself is a consistency check, not independent pixel-level privacy certification. A coordinated replacement of plan, video and receipt can pass; use a trusted external signature/hash when provenance matters.

## Local-processing safety

No network request, upload, telemetry or application credential is used. The media is read from an explicitly supplied bounded regular file into a private temporary snapshot. Source URLs, symlink leaves and special files are rejected. FFmpeg is restricted to explicit MOV/Matroska demuxers with `file,pipe` protocols; MOV external data references and absolute-path aliases are disabled. Do not treat this as a sandbox for a malicious FFmpeg build, hostile parent-directory replacement or untrusted decoder vulnerabilities. Keep FFmpeg updated and process untrusted media in an appropriate isolated environment.

Plans are bounded UTF-8 JSON; duplicate keys, excessive depth, malformed Unicode, floats, booleans as integers, out-of-frame rectangles and mismatched source hashes are rejected. Media-tool error text is not echoed, because it could include private paths or metadata. Every render/probe must exit successfully without error-level diagnostics. Generated outputs are checked before result publication; an I/O failure while writing the final directory can still leave a partial result. A partial directory is not a completed render. Existing output directories are not overwritten.

Temporary snapshots are cleaned up by the temporary-directory mechanism after use; this is not a secure disk wipe guarantee. The resulting video and preview frames may **still contain unmarked private material**. Keep them local until reviewed. Source hashes and mask positions can also be sensitive. No private vulnerability-reporting destination is designated; do not put private recordings or secrets into public issues.

## Existing tools and honest scope

- [OpenScrub](https://github.com/austinmabry/OpenScrub) documents a considerably broader visual workflow, face/text detection, manual box editing and audio spans. Prefer it when those capabilities are needed.
- [simple-redact-video-tool](https://github.com/cclawton/simple-redact-video-tool) provides a local visual region/time-range editing workflow with FFmpeg.
- [deface](https://github.com/ORB-HD/deface) focuses on detected-face anonymization and audio removal.
- [FFmpeg filters](https://www.ffmpeg.org/ffmpeg-filters.html) provide the underlying opaque drawing/timeline machinery; this is not a new redaction algorithm.

Primary documentation was reviewed; those product runtimes were not compared. There is no claim of novelty, better detection, superior editing UX or privacy certification. The delivered value is a source-bound, explicit frame-mask plan, real lossless render, default all-audio removal and testable artifact-check workflow. It is a narrow manual processing core, not a replacement for those full workbenches.

## Validation

24 public tests executed on Linux/Python 3.12 with FFmpeg 7.1.5. The real-media tests generate original synthetic video+tone, render it, decode all ten source and output frames to RGB, and compare **every pixel** against the expected union of masks. Unmasked pixels remain equal in this fixture. Actual audio removal, source-title/stream-tag removal, PNG extraction, source-binding failure, receipt/file tampering and CLI calls are also tested. Real 64-stream input (one video plus 63 AAC tracks) renders and self-verifies; 65-stream input is rejected by inspect and render before output creation.

No Windows/macOS, hosted CI, browser playback, real lecture recording, HDR/color-managed workflow, variable-frame-rate corpus or adversarial decoder corpus was tested. Real-media tests explicitly skip if FFmpeg is unavailable; skips are not passes. The synthetic preview frame was inspected locally; that is not validation of a user's recording.

MIT license, original code and synthetic generator by walker512. No real course footage, student data, personal voice recording or upstream competitor source is included.

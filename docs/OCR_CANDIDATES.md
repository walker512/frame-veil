# Explicit English OCR candidates (introduced in 0.3.0)

The original fixed full-frame workflow remains supported. Version 0.4 adds an optional [explicit-region workflow](REGION_OCR.md) for targeted missed areas; it preserves baseline evidence and does not remove the limitations below.

This optional local workflow identifies **the exact words you ask for on the decoded frames you explicitly select**, then requires human decisions before producing an ordinary Frame Veil mask plan. It does not identify every student's name, classify private text, detect faces or spoken names, track notifications, or certify a recording safe to share. False positives and missed text are expected. Human review of the entire final output remains mandatory.

## Requirements and an original example

Python 3.11+, POSIX, trusted local FFmpeg/ffprobe and Tesseract with installed `eng` language data. The tested environment has FFmpeg/ffprobe 7.1.5, Tesseract 5.5.0 and Leptonica 1.84.1, with `eng` and `osd` installed. This module fixes **`eng --oem 1 --psm 6`**; it does not use `osd`, download models, install language packs or claim Chinese recognition. No binaries, language data or fonts are bundled. Tesseract is an external Apache-2.0 project; FFmpeg and its codecs have separate licensing. The [official Tesseract command-line documentation](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html) describes TSV output and page segmentation modes.

```sh
python -m examples.ocr_synthetic new-ocr-example
python -m frame_veil.ocr scan new-ocr-example/synthetic.mp4 \
  --terms new-ocr-example/terms.json --frames new-ocr-example/frames.json \
  --out private-scan
python -m frame_veil.ocr verify private-scan
python -m frame_veil.ocr prepare private-scan --out decisions.json
```

The generator uses an existing DejaVu Sans system font at the documented Linux path, without copying or distributing it. It creates a fictional `Student ALICE SAMPLE` name and a `NOTICE DEMO ONLY` notification-like box, not real student information. The example requests frames `[0,3]` from six frames. The fixed recognizer detected the name in both sampled frames in the actual local run, but **missed the separate gray notification box**. This concrete miss is a reason to use the full human-review workflow, not evidence that the notice was absent or harmless. OCR settings are intentionally fixed and this release does not claim broad layout/accuracy validation.

For your own authorized recording, create a UTF-8 JSON list of 1..20 phrases and a separate sorted list of 1..24 unique zero-based decoded frame indexes. These are **not timestamps**. Examples:

```json
["ALICE SAMPLE", "PRIVATE NOTICE"]
```

```json
[0, 30, 60]
```

Source support retains the old bounded local H.264-in-MOV/MP4 rules: up to 64 MiB, exactly one video, at most 64 streams, square pixels, no nonzero rotation, up to 1920×1080 and 1,800 decoded frames. Other streams are not analyzed. A changed source, even only metadata, requires a fresh bound scan. No source URL, playlist, external-data reference, link crawl, audio transcription or upload is performed.

## What the scan preserves

The source is read into a private snapshot. A bounded local probe determines decoded frame count/dimensions. FFmpeg decodes the explicitly selected frame indexes with no scaling or frame-rate resampling. Each retained frame is stored as an exact generated binary RGB PPM image (`P6`, fixed header, no arbitrary image parsing). OCR runs on these images individually. The original video is not copied into the scan output.

Every complete scan contains exactly:

- Original `terms.json` and `frames.json` bytes.
- `frame-NNNN.ppm` for every selected frame: **the entire unredacted selected frame**, not just matched text.
- `frame-NNNN.tsv`: **all recognized TSV words** on that frame, not only your search terms.
- `candidates.json`: matched term index, decoded frame index, recognized words, each word's pixel rectangle and raw confidence, plus their union rectangle.
- `manifest.json`: source hash, geometry/frame count, exact sample indexes, fixed configuration, reported tool versions, diagnostic-prefix hashes/lengths and SHA-256 of every other artifact.

**These artifacts can contain sensitive student names, notifications, credentials, unrelated text or other private pixels. Keep the whole scan private.** Hashes, coordinates, search phrases and diagnostic metadata can also be sensitive. There is no redaction of this intermediate evidence, encryption, secure deletion or automatic sharing. A supporting local image viewer can open the PPM files; no browser/UI rendering acceptance is claimed. Terminal output reports counts/status only, not recognized text or local paths.

The scan publishes only after all selected frames decode and all OCR outputs parse successfully. Failure is an error, not an empty successful result; no new completed scan is published. Never treat a previously successful directory as the output of a later failed command. Existing output directories are refused. A final filesystem-write failure can leave an incomplete directory, which `verify` rejects. No unexpected files are deleted or overwritten.

## Matching, evidence and misses

TSV fields are parsed as the documented level/page/block/paragraph/line/word identifiers, integer coordinates, confidence and text. Word boxes must fit the actual frame. A phrase matches **consecutive complete word tokens in the same page/block/paragraph/line**, using Unicode `casefold` and whitespace splitting of the supplied phrase. No cross-line concatenation, fuzzy matching, substring matching, punctuation stripping, semantic name recognition or movement tracking occurs. `Sample` and `Sample.` differ; an OCR spelling error can cause a miss. A term being English-like does not prove it belongs to a person or is private.

All finite valid word confidences are retained, including low values; there is no automatic confidence threshold. These numbers are engine scores, not calibrated probabilities or privacy assurances. Candidate boxes are geometric unions of recognized word boxes, not guarantees that all glyphs/shadows were captured. Human padding can be necessary.

Only the listed frames were sampled. Unsampled frames, pixels outside recognized words, moving text, faces, spoken content and notification animations remain unexamined. **Zero candidates means no exact requested-token matches were produced on those selected frames, never “no sensitive material.”** Different layouts, small text, language, compression and contrast can cause additional misses. There is no automatic interval extrapolation from a single hit.

## Human decision → ordinary mask plan

`prepare` first verifies the complete scan and generates one pending row per candidate. Edit a copy in a trusted local text editor. Each candidate must retain its exact ID/order and become either:

- `dismiss`, with an explicit reason and `mask: null`; or
- `accept`, with an explicit reason and a complete integer mask:

```json
{
  "id": "KEEP_THE_GENERATED_ID",
  "decision": "accept",
  "note": "Human reason for this rectangle and explicitly selected interval",
  "mask": {
    "start_frame": 0,
    "end_frame": 1,
    "x": 180,
    "y": 55,
    "width": 280,
    "height": 40
  }
}
```

This is only an illustrative row, not a valid decision file or a recommended rectangle for a private recording. The full generated decision document also binds the source and exact scan-manifest bytes. An accepted interval uses the old `[start_frame,end_frame)` semantics and must include the sampled hit frame. Its rectangle must cover the candidate union box and stay within the frame. You may deliberately add padding or choose a longer interval after examining that area; the program **does not claim to have examined additional frames**. There is no default accepted interval, automatic temporal tracking or “viewed=true” certification. A note/decision records a human declaration, not proof of viewing, consent or complete redaction.

```sh
python -m frame_veil.ocr plan SOURCE.mp4 private-scan decisions.json --out explicit-plan
python -m frame_veil render SOURCE.mp4 explicit-plan/plan.json --out redacted-copy
python -m frame_veil verify redacted-copy
python -m frame_veil audit-masks redacted-copy
python -m frame_veil review-prepare redacted-copy --kind silent --out human-review.json
```

For the existing review CLI's precise arguments and all review/decide/export steps, see [HUMAN_REVIEW.md](HUMAN_REVIEW.md); keep using its whole-output visual/audio checks. The standard default renderer removes all audio; the separate reviewed selective-audio workflow remains opt-in. No OCR operation changes these policies.

`plan` rereads and verifies the complete scan, candidates, source hash and decision binding before creating `plan.json`, the supplied `decisions.json`, and a binding `receipt.json`. All candidates must be explicitly decided; at least one accepted mask is required. No accepted masks or no candidates means the command refuses an empty “privacy cleared” plan. You can instead use the old manual masking workflow to mark other risks. If you manually change the generated plan, its OCR binding receipt no longer describes it; retain it as a separately reviewed manual plan. Original render only needs its existing exact source-hash binding, not OCR data.

The generated plan contains only accepted OCR-related masks. It does **not** incorporate all other risks you may find while viewing; account for those through the existing manual plan and full-output review. A successful mask pixel audit establishes opaque declared masks, not adequacy of their location or duration.

## Verification and trust

`verify`, `prepare` and `plan` verify the exact expected artifact set, canonical manifest, all file hashes, strict PPM layout, frame coverage, TSV structure and deterministically recomputed candidate list. A changed candidate cannot be hidden merely by updating its file hash while leaving incompatible TSV evidence. Generated decisions bind the entire scan manifest and source hash; stale decisions are rejected.

Verification **does not rerun OCR or reopen/decode the original source** (plan separately checks its exact source bytes). It cannot prove the retained samples came from that source, that an honest Tesseract produced the TSV, or that OCR found all matching text. A coordinated rewrite of source hashes, sample/TSV content and manifests can create another internally consistent record. Tool versions and diagnostic hashes are recorded claims, not signed attestations. Diagnostic text is omitted and nonempty diagnostic hashes cannot be recomputed from the bundle. No source provenance or legal/publication clearance is certified.

## Resource and subprocess limits

The new OCR path uses its own incremental bounded subprocess reader for probe, selected RGB decode, tool version checks and OCR, rather than claiming that the old renderer's subprocess implementation has changed. POSIX process groups are terminated on errors/timeouts and ordinary same-group children are cleaned up. No shell is used. Only a default PATH/LANG and `OMP_THREAD_LIMIT=1` are passed. FFmpeg decode threads and output threads are set to one, with explicit MOV demuxing, file/pipe protocols and disabled MOV external references. Local trusted Tesseract reads only the explicit generated PPM argument; it is not a network scanner.

Aggregate retained RGB sample bytes are prechecked at **64 MiB** using dimensions × 3 × sample count. Each TSV is at most 1 MiB/10,000 rows, each tool's stderr at most 64 KiB; candidate count is capped at 100 and candidate/manifest/decision JSON uses existing 1 MiB bounds. Overflow fails rather than silently truncating candidates. Probe and selected-frame decode each have a 120-second deadline; each OCR invocation/version/language check has a 30-second deadline. At 24 samples the sum of nominal subprocess budgets is 1,080 seconds, plus up to 60 seconds of cleanup waits across 30 processes. These are **not hard wall-clock guarantees** against process creation or uninterruptible kernel/filesystem operations. OCR output warnings may be nonfatal when the process exits zero and valid TSV is produced; FFmpeg error-level diagnostics are failures.

These checks are not an OS sandbox, hard CPU/memory/disk quotas, protection from vulnerable decoders or a malicious tool installation, or a security boundary against hostile parent-directory replacement. A bounded compressed video may still be expensive to decode. Use trusted maintained tools and an appropriate external isolation environment for untrusted media. Temporary files are cleaned normally, not securely wiped.

Exit 0 means the requested scan/consistency/decision preparation/plan operation completed. It never means “safe to publish”. Exit 2 means invalid input/artifact/decision, unsupported tools/media, limit, timeout or I/O failure. The old renderer/auditor exit semantics remain unchanged.

## Executed validation

**88 tests passed on Linux/Python 3.12, zero skips**: the original 64 tests and core/audio/review code remain byte-for-byte unchanged; 24 new OCR tests cover actual local decoding/Tesseract recognition, exact selected-frame RGB equality, source/scan/decision binding, independent mask audit, unselected-frame pixel preservation, pending whole-output human review, zero matches, complete candidate decisions, explicit longer intervals, bounds/timeout/output/TSV failures, special files, malformed-manifest controlled CLI errors, artifact tampering and no-process offline verification.

The final CLI example separately ran generator → scan → verify → prepare → explicit synthetic decisions → plan → render → `audit-masks` → `review-prepare`. Both selected frames contained detected fictional name candidates. The actual six-frame output had two declared masked frames and 13,312 rectangle-pixel checks, all opaque. The notification-like text was missed as disclosed above. The final whole-output human review remains pending, not falsely approved by these commands. The regression test also independently compared actual selected source RGB bytes and verified unselected output frames remain unchanged in this fixture.

No real lecture/student recording, Chinese OCR, GUI/screenshot workflow, Windows/macOS, competitor runtime or adversarial-media corpus was tested. Real-media/OCR tests explicitly skip when required local tools/font are missing; skips are not passes. No third-party video, font file, language model, private scan artifacts or binary tool is distributed in the source package.

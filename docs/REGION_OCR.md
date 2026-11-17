# Explicit region OCR (0.4.0)

This workflow addresses a concrete 0.3 limitation: the public synthetic gray
notification was missed by full-frame English OCR. The new path lets you specify
rectangular areas and optional preprocessing, while **preserving every baseline
candidate and its original evidence**. It is not automatic notification detection,
a general privacy classifier, or proof that a recording is safe to publish.

## Run locally

Requires the same trusted local POSIX FFmpeg/ffprobe and Tesseract `eng` installation
as [baseline OCR](OCR_CANDIDATES.md). No download, API key, remote service, model,
font or binary is included. Examples require an existing Linux DejaVu Sans font.

```sh
python -m examples.region_ocr_synthetic demo-regions
python -m frame_veil.region_ocr scan demo-regions/synthetic.mp4 \
  --terms demo-regions/terms.json --frames demo-regions/frames.json \
  --regions demo-regions/regions.json --out private-region-scan
python -m frame_veil.region_ocr verify private-region-scan
python -m frame_veil.region_ocr prepare private-region-scan --out decisions.json
```

Installed console command: `frame-veil-regions`. Examples are source-checkout
modules, not installed console commands. Region configuration is a JSON array:

```json
[{"id":"notice","x":20,"y":180,"width":600,"height":70,"scale":2,"threshold":null}]
```

Coordinates describe the **original decoded frame**, not timestamps or CSS pixels.
Every region applies to every explicitly selected frame. IDs must be unique ASCII
letters followed by letters/digits/underscore/hyphen (maximum 40 characters).
All seven fields are required; unknown fields and booleans in integer fields are
rejected. Rectangles must fit the actual decoded dimensions. Scale is an integer
1..3. Threshold is `null` (default/example preserves RGB), or integer 0..255.
No arbitrary filters, commands or executable paths are accepted as configuration.

The transform crops original RGB pixels, repeats each pixel/row `scale` times
(nearest neighbor), and optionally binarizes with integer luma
`(299*R + 587*G + 114*B + 500)//1000`: luma >= threshold becomes white, otherwise
black. Binarization is applied to the source pixel before repetition, with the
same result as after repetition. There is no interpolation or implicit contrast
optimization. **A threshold can destroy text contrast and increase misses.**

OCR remains fixed to `eng --oem 1 --psm 6`. Phrase matching follows baseline
casefold/consecutive-whole-token rules. Full-frame matches use `base-` IDs;
region matches use `region-REGION_ID-` IDs. Overlapping regions and baseline hits
can produce duplicate-looking candidates. They are intentionally retained with
separate identities and must each be decided, not silently deduplicated.

## Coordinates, evidence and verification

A candidate and each word retain `derived_box` in cropped/enlarged coordinates.
Their `box` coordinates are mapped back to the original frame: divide left/top
by scale rounding down, divide right/bottom rounding up, then add crop origin.
This conservatively covers fractional edge pixels. The candidate union and word
boxes use the same mapping. Human padding may still be needed around glyphs.

A scan keeps the entire old bundle under `base-*` names: original full RGB sample
frames, baseline TSV/candidates/terms/frame indexes and manifest. It additionally
keeps exact region configuration, every derived RGB PPM, every region TSV, combined
candidates, diagnostics hashes, and a canonical manifest binding all files.
`verify` first validates the restored baseline format, then independently recreates
all derived pixels from full-frame samples and configuration, reparses the TSV,
and recomputes coordinate mappings and merged candidates. It checks exact file
sets, bounds, hashes, configuration, coverage, and canonical generated records.

Offline verification starts **no tool**, does not decode the source, and does not
rerun Tesseract. It proves internal consistency, not source authenticity or honest
OCR execution. A coordinated rewrite of retained samples/TSV/manifests can be
internally consistent. Tool version/diagnostic claims are not signed attestations;
nonempty stderr content is not retained for independent recomputation. The plan
step separately rehashes the full original video, including metadata, to reject a
different source. A source hash is not proof that the sample pixels were decoded
from those bytes.

## Explicit decisions and actual masking

`prepare` creates **pending** rows for all combined candidates. Edit a private copy
using the same explicit `accept`/`dismiss`, reason, and mask structure documented
in [OCR_CANDIDATES.md](OCR_CANDIDATES.md). Every candidate ID and order must remain;
accepted mask rectangles must include the full mapped candidate box and its
sampled frame. Intervals are manually chosen, never extrapolated from OCR hits.
Zero accepted masks, zero candidates and pending decisions refuse plan creation.
No automatic `viewed` or consent declaration is made.

```sh
# Only after actually making explicit decisions:
python -m frame_veil.region_ocr plan demo-regions/synthetic.mp4 \
  private-region-scan decisions.json --out explicit-plan
python -m frame_veil render demo-regions/synthetic.mp4 explicit-plan/plan.json --out redacted
python -m frame_veil audit-masks redacted
python -m frame_veil review-prepare redacted --kind silent --out human-review.json
```

Plan creation uses the original validated manual-plan rules and binds source,
region manifest, decision bytes and output plan. Default rendering still removes
ALL audio. The human full-output review remains pending until the person actually
reviews it. Mask pixel audit checks opaque declared pixels, not the adequacy of
location/duration or coverage of other privacy risks. See [HUMAN_REVIEW.md](HUMAN_REVIEW.md).

## Bounded operation and privacy

- 1..8 regions, 1..24 selected frames; **baseline plus region OCR <=64 invocations**.
- Original RGB samples <=64 MiB; total derived RGB samples <=64 MiB, prechecked
  before region preprocessing. Each TSV <=1 MiB; aggregate baseline+region TSV
  <=32 MiB. Combined candidates <=100; structured JSON <=1 MiB.
- Whole bundle <=168 MiB (two 64 MiB RGB budgets +32 MiB TSV +8 MiB headers/JSON).
- Source and format limits remain baseline's 64 MiB bounded H.264 MOV/MP4, square
  pixels, no nonzero rotation, up to 1920x1080 and 1,800 frames.
- The implementation first runs a full baseline scan in a private temporary
  directory. This adds deliberate work/storage and retains baseline misses;
  invalid actual-frame region bounds or derived-pixel budget may be rejected
  **after** baseline OCR, but before region OCR. Invocation-count bounds are
  checked before baseline work.
- Probe/decode deadlines are 120 seconds each, each OCR/version/language command
  30 seconds; up to 64 OCR calls plus four version/language calls means nominal
  subprocess deadlines can total 2,280 seconds, plus cleanup/validation time.
  This is not a hard end-to-end deadline or memory/CPU sandbox.
- Fixed tools use the bounded POSIX process-group runner. No shell/network is
  used by this workflow; trusted tools and hostile media still require external
  isolation. Parent directory replacement and malicious tool installations are
  outside its security guarantees.

Scans contain **unredacted pixels and recognized private text**. Keep them private.
New region scan and plan directories use POSIX mode 0700 even under umask 022;
files inherit that directory protection, not encryption. New `prepare` decision files use POSIX mode 0600; keep their parent
directory private too. Temporary cleanup is not secure deletion. This workflow never uploads
artifacts. Do not publish a scan just because `verify` passed.

Tool or validation failures occur before publishing output. Final filesystem write
failure can leave a partial directory, which verification rejects; publication
is not atomic. Existing outputs are refused and no user files are overwritten or
silently deleted. Exit 0 means the selected operation completed, **never privacy
clearance**. Exit 2 means invalid/unsupported data, pending decisions, bound,
processing or I/O failure. Zero hits are not an error and not a clearance.

## Validation boundary

The original synthetic gray box is detected with region crop +2x nearest resize;
threshold 64/110 also detects it, while threshold 180 loses the notice. The original
full-frame name candidates remain in every case. Additional original synthetic
right-side, white-on-dark and low-contrast layouts exercise the same generic
transform, including deliberately destructive threshold cases. No word or box
location is hardcoded into the algorithm.

Tests cover exact pixel transformations and threshold boundary values, conservative
word/union mapping, complete baseline preservation, duplicate-region identities,
real process OCR, strict configuration, original/derived evidence tampering,
rehashed incompatible artifacts, source/manifest/decision binding, offline no-tool
verification, pending/all-dismissed/zero-hit rejection, output permissions, tool
failure without publication, actual plan -> render -> independent mask pixel
audit, and still-pending human whole-output review. Missing tools/font explicitly
skip the real tests, never count as a pass.

No real private videos, GUI, Chinese recognition, Windows/macOS, malicious-media
corpus, temporal tracking, general recall benchmark, competitor superiority or
production security certification is claimed. This is a targeted local workflow
improvement, not complete automatic anonymization.

### Executed local checks

Linux/Python 3.12 with FFmpeg/ffprobe 7.1.5 and Tesseract 5.5.0:
**108 tests passed, zero skips** (88 existing +20 region tests). The documented CLI
example independently produced 2 baseline name and 2 region notice candidates,
then 4 declared masks on 2 of 6 decoded frames. The actual output pixel audit
checked 26,424 rectangle pixels including overlap and found all declared pixels
opaque. The whole-output human review record remained pending. These are synthetic
fixture observations, not real-world recall measurements or publication consent.

## Paired threshold controls and sampling coverage (0.5.0)

Opt in when trying a threshold on an explicitly selected crop:

```sh
python -m frame_veil.region_ocr scan demo/synthetic.mp4 --terms demo/terms.json --frames demo/frames.json --regions demo/regions.json --pair-unthresholded --out paired-scan
python -m frame_veil.region_ocr coverage paired-scan
# Legacy selected-frame scan bundles also support:
python -m frame_veil.ocr coverage original-scan
```

For each thresholded region, `--pair-unthresholded` retains the configured variant
and adds an unthresholded crop at the **same coordinates and scale**, unless such
a control already exists. Generated controls have unique `control-N` IDs. It
does not infer new areas, frame intervals, language, text or masks. The expanded
`regions.json` retains every requested variant's values and identifies the
controls; the input config is not modified. Each variant's actual derived PPM,
TSV and candidate evidence is stored and independently revalidated by the existing
offline verifier. Matching controls are reused; duplicated-looking actual matches
are retained with origin IDs, not silently merged.

The same 8-region, 64-execution and pixel/TSV budgets still apply **after**
expansion. If controls exceed a budget, the workflow rejects the request, rather
than omitting evidence. This opt-in costs additional OCR calls and storage.
Existing scan behavior without the flag is unchanged.

In the original fictional gray-notice fixture, threshold 180 erases the notice:
both selected frames have no notice matches in the threshold-only path. Paired
controls recover the requested notice on those two frames while retaining the
original name hits and failed-threshold evidence. This is one measured
failure-mode mitigation, **not a real-world recall benchmark**. It cannot recover
text absent from the original pixels, unrequested words, unselected frames,
unsupported language or all other OCR misses. No new OCR model is downloaded.

`coverage` first verifies the entire stored bundle without rerunning OCR, then
reports sampled frame indices, unsampled half-open ranges and, for each requested
term index, sampled frames with and without an exact match. Region output
separates baseline and each region variant. It deliberately omits raw search
phrases, OCR text and file paths from stdout; sampling indices and counts may
still be sensitive. This is sampling coverage, **not a privacy-detection score**.
Even every frame sampled with matches is not a safety certificate. Frames without
a match can contain missed text; every frame still needs human review.

Local validation of this increment: 116 tests passed, zero skips; after expanding
the low-contrast fixture assertion, the final 24 region tests passed again. The
paired path also recovered the requested notice in the separate pale-background,
gray-text fixture that threshold 110 alone lost. Both observations use fictional
English text, installed Tesseract and real decoded pixels. The prior known-negative
threshold-only tests remain, rather than being removed to inflate success.

## Explicit short-interval second pass (0.6.0)

Sparse sampling can miss a transient notice completely. After checking
`coverage`, choose a short interval in a trusted viewer and rescan **every**
frame in it, without manually constructing an index JSON file:

```sh
python -m examples.moving_text_synthetic moving-demo
python -m frame_veil.region_ocr scan moving-demo/synthetic.mp4 --terms moving-demo/terms.json --frames moving-demo/frames.json --regions moving-demo/regions.json --out moving-sparse
python -m frame_veil.region_ocr coverage moving-sparse
python -m frame_veil.region_ocr scan moving-demo/synthetic.mp4 --terms moving-demo/terms.json --frame-range 0 6 --regions moving-demo/regions.json --out moving-dense
python -m frame_veil.region_ocr coverage moving-dense
python -m frame_veil.region_ocr prepare moving-dense --out moving-decisions.json
```

The legacy `frame_veil.ocr scan` supports the same `--frame-range START END`
alternative. The end index is excluded. Choose **either** `--frames` or
`--frame-range`, never both. This is an easier explicit dense-sampling workflow,
not a more capable OCR model or automatic motion tracking.

The interval must contain 1–24 frames and fit the actual source. For region
scans, frame count × (1 + expanded region count) must be at most 64. Thus 24
frames with one region use 48 OCR calls, while 24 frames with a thresholded
region plus its paired control would require 72 and are rejected before media
tools start. Choose a smaller explicit interval/configuration; nothing is silently
subsampled. Existing decoded RGB, derived-pixel, TSV and candidate limits still
apply and may reject even a valid frame count. This is not an unbounded batch
runner: use separately reviewed new output directories for additional intervals.

Each frame gets its own actual image/TSV/candidate evidence in the existing
verifiable bundle. The normal source-bound pending-decision workflow remains.
After inspecting the images, explicitly set each accepted mask's spatial box
and duration; a one-frame observation is not extended automatically. Do not reuse
decisions from a different scan. Render, run the mask pixel audit, then perform
the required human full-output review. The sampled union does not merge plans
from different scans automatically.

The original six-frame moving fixture has fictional text only on frames 1, 2
and 4 at three different horizontal positions. Sparse samples [0, 3] miss all
three. The interval [0, 6) finds the requested text on all three observed frames,
retains all six sampled-frame images, and supports manually confirmed one-frame
masks that pass the existing pixel audit. The resulting human review record is
still pending. This demonstrates fixing a **sampling omission in this fixture**,
not universal moving-text recall or full-video privacy. Blurred/occluded text,
text outside the configured region, other words/languages and events outside the
interval can still be missed. Even no unsampled ranges does not mean no leaks.

Coverage output includes user-supplied region IDs, which can themselves contain
sensitive identifiers. Do not publish it without checking those IDs as well as
the sampling indices/counts.

Local 0.6.0 validation: 122 tests passed, zero skips, including six new interval
schema, CLI exclusivity, umask-000 permission, source/end/call-bound,
moving-text recovery and pending-review render/audit tests. These are local
synthetic checks, not independent certification or proof of human viewing.

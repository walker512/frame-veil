# Human review and guarded export

This is a CLI checklist for the existing local renders, **not an interactive classroom review workstation**. Use a trusted local player to inspect the complete output before marking its checks. The software cannot tell whether you watched or listened. A record is a human declaration, not an identity signature, proof of consent, or privacy certification.

## Workflow

1. Render with the existing `render` (all audio removed) or `audio-render` (explicit sample muting) commands.
2. Create an all-pending checklist:

```sh
frame-veil review-prepare audio-bundle --kind audio --out review-01.json
# For an ordinary all-audio-removed bundle, use --kind silent instead.
```

Preparation audits the actual output's declared black rectangles and, for audio bundles, declared silent intervals. It snapshots and binds **every expected bundle file**. Invalid output does not receive a record.

3. Play `audio-bundle/review.mkv`, not its silent fallback, in your trusted local player. Inspect *all* video and audio, not only marked areas. The record partitions every video frame into consecutive, exclusive-end groups of up to 60 frames and every decoded audio sample into groups of up to 10 seconds. Audio tail padding is included. Video frame groups are not fixed-time intervals, particularly for variable frame rate. Do not infer word boundaries or exact audiovisual timing from these indices. For silent bundles inspect `redacted.mkv`.
4. Record each category separately, only after actual human inspection:

```sh
frame-veil review-decide audio-bundle review-01.json --item video-0 --check names_and_text --decision reviewed --out review-02.json
frame-veil review-decide audio-bundle review-02.json --item video-0 --check faces_and_avatars --decision reviewed --out review-03.json
```

Other video checks are `notifications_and_other`; audio items such as `audio-0` have `speech_and_other_audio`. IDs and bounds are in the JSON record. `pending`, `reviewed` and `blocked` are the only states. Each command writes a **new** record and never overwrites the prior one. Review JSON may also be edited locally; this is intentionally not tamper-proof authorization. There is no bulk-confirm CLI. Changing item coverage, IDs, range boundaries or bundle bindings is rejected.

If any sensitive material remains or a segment is unclear, mark it `blocked`, fix the masking/muting plan, render again, and prepare a new all-pending record. Any byte change to any bound file, even a formatting-only plan change, invalidates old confirmations. Do not manually transplant confirmations to a new render.

5. Only when *every* category is reviewed:

```sh
frame-veil review-export audio-bundle final-review.json --acknowledge-human-review --out local-reviewed-export
```

This re-audits a private snapshot, validates complete coverage and all decisions, and exports those **same audited media bytes** as `reviewed.mkv`, plus `human-review.json` and `SCOPE.txt`. Pending or blocked items, missing acknowledgment, stale records, or invalid media stop before output-directory creation. Existing output is never overwritten. A filesystem failure during final writing can leave a partial directory; remove it only after inspecting it and retry into a different new directory.

## Boundaries and privacy

- The new export command is an optional workflow gate, **not access control**. Existing render commands and files remain accessible; people can copy them or manufacture matching declarations. There is no authentication, timestamped sign-off service, or evidence that a human actually reviewed the media.
- Checks are broad prompts, not a complete list of possible disclosures. An entire black/silent recording can satisfy automatic mask/mute checks. Unmarked personal information, speech, metadata values introduced by tools, contextual identities, copyright and consent still require human judgment.
- No consent is granted by `--acknowledge-human-review`. Successful output explicitly says `privacy_certified=false` and `publication_authorized=false`. Obtain all required permissions separately before sharing.
- The exported media retains everything not removed by the chosen plans. Treat it as private. The record contains sample counts, ranges, categories and file digests, not original source paths or reviewer names. No free-text private notes are copied by this workflow. Hashes are consistency bindings, not proof of authenticity.
- Temporary files contain media and are cleaned up normally, **not securely erased**. Parent directory symlinks and concurrent local filesystem attackers are outside this tool's isolation guarantees. Use a private trusted working directory and trusted up-to-date FFmpeg.
- Real FFmpeg tests exercise synthetic video and tones. They do not establish successful review of actual students or sensitive speech, a usable playback UI, Windows/macOS compatibility, or superiority over video editors.

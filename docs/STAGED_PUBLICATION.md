# Optional staged silent-render publication

The existing default `render`, `audio-render`, review export and other commands
retain their existing behavior and platform support. Their final directory writes
are **not transactional**: a failure may leave partial output; do not treat a
directory's existence as completion. This addition is opt-in for silent `render`
only, and does not claim to fix every output path.

```
python -m frame_veil render source.mp4 plan.json --out final --staged
```

Use trusted, stable parent directories on a local filesystem. The parent must
already exist. Rendering writes a private sibling `.frame-veil-stage-*/bundle`,
then the existing bundle verifier runs before no-replace directory publication.
On supported Linux filesystems this uses `renameat2(RENAME_NOREPLACE)`. On Windows
it uses the non-overwriting `os.rename` behavior. An existing file, directory,
empty directory or link is never intentionally replaced. No copy/delete or
check-then-overwriting-rename fallback is used. A destination precheck avoids
obvious wasted work; the no-replace operation, not the precheck, handles competing
publishers. If the filesystem rejects the operation, publication fails closed.
Other platforms reject this optional mode before rendering; default commands are
unchanged. Native Windows/ACL tests have not been run for this increment.

No staging is automatically deleted, including on failure, cancellation or success.
A successful move leaves an empty private wrapper. A failed operation can leave
large sensitive media in staging, and repeated attempts consume additional disk.
Inspect and remove your own abandoned staging manually; do not blindly recursively
remove matches. A signal/crash can interrupt at any point, including after the
move but before a success response. Inspect and verify the final destination before
retrying. This is namespace publication, **not fsync/power-loss durability**, not
an immutable snapshot, and not isolation against another process with access to
the same account or writable parent. POSIX staging is created with mode 0700;
member writes use 0600. These modes do not certify Windows ACL protection.

A complete retained staging bundle can be published without re-encoding:

```
python -m frame_veil verify /trusted/parent/.frame-veil-stage-CHOSEN/bundle
python -m frame_veil publish-render /trusted/parent/.frame-veil-stage-CHOSEN/bundle --out /trusted/parent/final
```

Choose the exact retained directory yourself. `publish-render` verifies again,
then **moves** it; it does not copy it. Partial, malformed or extra-file bundles
fail verification. Cross-device moves fail with no fallback or removal. A partial
stage cannot be resumed by this command: rerun `render --staged` to a free final
path, retaining the old partial stage for manual inspection. Verification binds
receipt hashes/media properties, not authenticity, complete privacy removal or
human approval; use the existing mask audit and human-review workflow. Another
same-account writer can change a stage during verification: such hostile or
unstable sources/parents are unsupported. Existing legacy bundles still verify
and may be explicitly moved with `publish-render` under the same limitations.

Validation: real synthetic FFmpeg rendering and mask auditing, injected member
write/publication/interrupt failures, no-replace destination races, four real
concurrent processes, explicit cross-device error injection (not an actual mounted
cross-device run), legacy bundle verification and no-render complete-stage retry.
Linux only; no hosted CI, Windows or macOS validation claimed.

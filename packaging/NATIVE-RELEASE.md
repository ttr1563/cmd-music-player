# Native preview and publication gates

Maintainers build on each destination OS with Python 3.12:
`python scripts/build_native.py`. Users need none of the build tools.
Supported build targets are macOS arm64/x86_64, native Windows x64 and Linux x64.
Linux builds run locally; no Linux Actions job is configured. Linux distribution
compatibility depends on glibc and native dependencies and needs separate checks.
The existing Mac shell entry point delegates to this same script.

Each build installs locked dependencies, runs the applicable tests, freezes the
app, records native library paths/checksums in `dist/*.native.json`, then unpacks
the distributable and exercises doctor/config/purge/resolver/Deno and the spawned
audio worker. The frozen worker also decodes synthetic AAC/Opus through a real
miniaudio NULL callback, exercising pause/volume/seek/EOF/stop and process cleanup.
The probe stays in the test harness; no test mode or NULL fallback ships in fest.
These checks use no account, network playback or physical audio.
The Mac shell-installer harness is POSIX-only and is skipped on Windows.

## One candidate, three serial jobs

Before requesting external execution, record owner-wide billing/quota/budget
evidence and approval where required. Do not infer approval from a label existing.
Create an owner-controlled `release/*` PR and a **draft** release with tag
`native-preview-pr-<PR number>` and `targetCommitish` equal to the full PR head SHA.
After reviewing the candidate, add `build-native-preview` once. The workflow only
accepts same-repository release PRs in a public repository. It builds on standard
macos-15, macos-15-intel and windows-2022 runners sequentially, at most 20 minutes
per target. No Actions cache or uploaded Actions artifact is used; outputs attach
only to the existing matching draft. Existing assets are never overwritten.

A failed target stops later targets. Review the failure before approving any
repeat. Pushes alone do not start builds. A new candidate SHA needs an updated
draft target and separately reviewed execution; previous assets must be retained
under a different draft before reuse. Do not publish this preview tag directly:
use the normal versioned release PR, annotated tag and develop back-merge.

## Public binary release remains gated

Python package metadata alone does not establish the bundled FFmpeg/dependency
licenses. PyAV wheels can include x264/x265; upstream discusses the distinction
between source and wheel terms in
[PyAV issue 2270](https://github.com/PyAV-Org/PyAV/issues/2270).
Use each exact wheel/native hash to identify its matching
[vendor build tree](https://github.com/PyAV-Org/pyav-ffmpeg), patches, dependency
sources and license notices. Do not assume commercial exception rights.
The inventory is evidence for this work, not an SBOM or a completed audit.
PyAV v19.0.1's `scripts/ffmpeg-latest.json` selects vendor release
[`9.0.2-1`](https://github.com/PyAV-Org/pyav-ffmpeg/tree/9.0.2-1).
This is a provenance starting point; repaired wheel contents still need matching.

Before public distribution, retain applicable license texts and the complete
corresponding sources/build materials required by the chosen license route,
including repaired/copied native runtimes. Check every destination separately.
Do not mark the native binary cleared merely because PyAV's source is BSD or the
app is MIT. Signing/notarization status must also be stated accurately.

Finally verify login/account selection, search/playback, pause/seek/quit and actual
speaker output on user machines. Credentials stay on those machines. None of
these real-device checks has been completed by the hosted build smoke test.

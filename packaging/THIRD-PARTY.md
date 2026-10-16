# Bundled software

This distribution contains Python, PyAV/FFmpeg, miniaudio, yt-dlp, yt-dlp-ejs,
Deno and other Python dependencies. Package metadata under `_internal` includes
the upstream license files; Deno's MIT license is in `notices/DENO-LICENSE.txt`.
`DEPENDENCIES.lock` records the package versions.
The application license does not replace the licenses of bundled components.

Upstream source and build information:

- Python: https://github.com/python/cpython
- PyInstaller bootloader (GPL with distribution exception): https://pyinstaller.org/en/stable/license.html
- PyAV and its FFmpeg wheel builds: https://github.com/PyAV-Org/PyAV/tree/v19.0.1
- FFmpeg (consult the bundled wheel notices for its build license): https://ffmpeg.org/legal.html
- miniaudio: https://github.com/irmen/pyminiaudio/tree/v1.71
- yt-dlp: https://github.com/yt-dlp/yt-dlp/tree/2026.08.19
- yt-dlp-ejs: https://github.com/yt-dlp/ejs/tree/0.8.0
- Deno: https://github.com/denoland/deno/tree/v2.9.7

Keep this notice and the bundled metadata/licenses when copying the application.
Before a public binary release, verify the actual collected native-library
licenses and corresponding source/relinking requirements for that target build.
No signed/notarized or publicly released binary is produced by the build script.

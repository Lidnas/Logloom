# Asset Attributions

## Audio

All audio is synthesized at build time by `scripts/make-audio.sh` using only
FFmpeg built-in source filters (`sine`, `anoisesrc`) and effects filters
(`tremolo`, `bandpass`, `afade`, `amix`, `acompressor`, `alimiter`).

- `assets/music.m4a` — layered A-minor drone bed with slow tremolo, 56.5 s.
  Generated, no external samples. Placed in the public domain as part of this
  project (MIT, same as the rest of the repo).
- `assets/whoosh.mp3` — pink-noise band-passed burst used as transition SFX.
  Generated, no external samples.

No third-party music, no copyrighted recordings, no sample packs.

## Fonts

Rendered glyph text uses system font stacks resolved by the Chromium canvas:

- `"Segoe UI", system-ui, sans-serif` — Windows system font (Microsoft,
  licensed with Windows). No font file is redistributed by this project.
- `"Consolas", "Cascadia Mono", "Courier New", monospace` — Windows system
  monospace fonts, same licensing situation.

If you regenerate on another OS the stacks fall back to that system's default
sans/mono faces; no font binaries are committed here.

## Log content

Failure lines shown in scenes 2 and 4 are excerpted from
`examples/failed-build.log` in the Logloom repository
(https://github.com/Lidnas/Logloom), MIT licensed. The terminal summary line is
Logloom's own stderr output.

## Third-party npm dependencies (build-time only, not shipped in the MP4)

- `@napi-rs/canvas` — Apache-2.0 / MIT per upstream.
- `playwright-core` — Apache-2.0.

Neither is embedded in or required by the delivered video file.

# Logloom Promo Video

Rendered programmatic promotional video for
[Logloom](https://github.com/Lidnas/Logloom) — "Turn terminal chaos into a
debugging report."

**Final output:** `renders/logloom-promo.mp4`
(1920×1080, 30 fps, H.264 High + AAC stereo, 56 s, ~11 MB).

## Preview

Open `renders/logloom-promo.mp4` in any player.

## Structure

| Scene | Time | Content |
| --- | --- | --- |
| 1 | 0–6 s | Hook: tumbling 2,000-line counter, red scan sweep, "Where is the actual error?" |
| 2 | 6–13 s | Raw build/test failure lines scrolling past (authentic fixture text) |
| 3 | 13–21 s | Brand reveal: woven logo mark, tagline, feature chips, install command |
| 4 | 21–40 s | Demo: terminal runs the real `logloom analyze` command on the real fixture, then the report UI builds itself with the real CLI summary numbers |
| 5 | 40–49 s | Benefits: local-first, no AI, one HTML file, privacy-aware; open-source card with repo URL |
| 6 | 49–56 s | Final brand reveal, "Explore Logloom on GitHub", repo + install + tagline |

Everything on screen is drawn with Canvas 2D at render time — no screenshots,
no slide assembly, no fabricated UI.

## Regenerate

Prerequisites: Node.js 18+, ffmpeg on PATH.

```bash
npm install       # gets @napi-rs/canvas
node render.js 0 56 ./frames          # renders 1681 PNGs into frames/
bash scripts/make-audio.sh            # synth music bed + whoosh SFX
bash scripts/render-video.sh          # x264 + AAC premux
```

Sample-render a few seconds without the full sequence:

```bash
node render.js 13 14 ./qa-check             # one second of scene 3
```

## Layout

```
scripts/
  make-audio.sh      ffmpeg filter-graph synth (music bed + whooshes)
  render-video.sh    frame encode (x264) + audio premux (AAC)
src/
  main.js            frameAt(t) compositor, scene routing
  render.js          frame-dump driver (node-canvas)
  lib/ui.js          palette, background, logo mark, header/CTA
  lib/easing.js      easing curves and interpolation
  lib/draw.js        card/drawing primitives
  lib/typing.js      type-on helpers
  lib/scenes/s1..s6.js  one file per scene
assets/
  ATTRIBUTIONS.md    asset sources and licenses
qa/
  f<time>s.png       frames extracted from the final MP4 for QC
renders/
  logloom-promo.mp4  final deliverable
```

## Content policy

Every statement, number, command and UI element reproduces the real project:
real CLI name (`logloom analyze`), real fixture (`examples/failed-build.log`),
real CLI summary values (73 lines, 16 findings, 9 folded), real install string
(`python -m pip install logloom`), real MIT badge. No invented capabilities,
statistics or testimonials. Anything the report doesn't show is not shown.

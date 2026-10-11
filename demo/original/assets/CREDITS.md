# Image credits for the live suite

Every image in this folder has a row below, added in the same commit as the
image. `tests/test_original_suite_static.py` fails if a file here has no row.

| File | Page | Licence |
|---|---|---|
| `radcliffe-night-stars.jpeg` | `index.html`, `baseline.html` | No licence on record; shipped at the owner's direction on 2026-10-10 |
| `st-andrews-quad.jpg` | `students.html`, `../landing.html` | No licence on record; shipped at the owner's direction on 2026-10-10 |
| `radcliffe-observatory-watercolour.jpg` | `writing-state.html` | No licence on record; shipped at the owner's direction on 2026-10-10 |
| `radcliffe-interior.avif` | `submissions.html`, `../landing.html` | No licence on record; shipped at the owner's direction on 2026-10-10 |
| `gonville-caius-facade.jpg` | `reports.html` | No licence on record; shipped at the owner's direction on 2026-10-10 |
| `all-souls-engraving-wide.jpg` | `voice.html`, `../landing.html` | No licence on record; shipped at the owner's direction on 2026-10-10 |
| `white-stag.jpg` | `my-work.html` | No licence on record; shipped at the owner's direction on 2026-10-10 |
| `codrington-library.jpeg` | `bluebook.html` | No licence on record; shipped at the owner's direction on 2026-10-10 |

The public landing page (`demo/landing.html`) uses three of these files at the owner's direction on
2026-10-11, under the same terms: no credit or licence text is shown, and `all-souls-engraving-wide.jpg`
has an empty `alt` there too. The watermarked `radcliffe-night-stars.jpeg` is not used on the landing
page while the photographer's permission is pending.

`st-andrews-quad.jpg` is the handoff photograph (3173 x 2068, 2.3 MB) re-encoded as a JPEG at quality 75 with its
longest side at 1600 px (`sips`), same framing, so it fits the 700 KB commit limit.

`radcliffe-interior.avif` is the handoff file as it came (257 KB), copied without re-encoding.
`gonville-caius-facade.jpg` is the handoff photograph (`gonville-caius-facade.png`, 1920 x 1280, 3.4 MB) re-encoded as a
JPEG at quality 75 with its longest side at 1600 px (`sips`), same framing, so it fits the 700 KB commit limit.

`radcliffe-night-stars.jpeg` carries a caption printed in the photograph itself, recorded here verbatim as observed:
"Sarah Savić Kallesøe | Oxford by Night". The owner is asking her for permission to use the photograph. There is no
other credit text, and none is shown on the page.

`radcliffe-observatory-watercolour.jpg` is the handoff file copied unchanged (966 x 992, 165 KB). It is a signed
watercolour, not a photograph. A handwritten inscription sits at the bottom left; as far as it can be read it gives a
date in July 1953, "Oxford", and a signature that appears to read "Methuen". No other credit text is known, and none
is shown on the page.

`all-souls-engraving-wide.jpg` is the handoff image (`all-souls-engraving-wide.png`, 1983 x 793, 3.2 MB) re-encoded as a
JPEG at quality 75 with its longest side at 1600 px (`sips`), same framing, so it fits the 700 KB commit limit. The
handoff calls it an engraving of All Souls College, but it appears to be AI-generated in an engraving style (the
credits file of #237 observed the same). It is shipped at the owner's direction, with no source or licence on record. It
is never described on the page as a historical engraving: the image carries an empty `alt`, so it is decoration only.

`white-stag.jpg` is the handoff image (`white-stag.png`, 1448 x 1086, 3.1 MB) re-encoded as a JPEG at quality 75
with its longest side at 1600 px (`sips`), same framing, so it fits the 700 KB commit limit. Its origin is unknown
(it looks like a photograph with a painterly effect applied). No credit text is known, and none is shown on the page.

`codrington-library.jpeg` is the handoff file copied unchanged (643 x 476, 55 KB). It is byte-identical to
`demo/assets/codrington-library.jpeg`, which the Bluebook teacher screens already use. It shows a library interior
with no caption printed in it. No credit text is known, and none is shown on the page.

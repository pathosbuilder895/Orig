# Image credits for the navy demo suite

NORTH_STAR: no unlicensed images, and no AI-generated images credited as
historical art. An image is added to this folder only in the same commit as
its row in **Credited** below. `tests/test_teacher_demo_site.py` fails if any
file in this folder lacks a row with a source and a licence.

Until an image is credited, its page shows the design's navy gradient instead.

## Credited

| File | Source | Licence | Credit line shown on the page |
|---|---|---|---|

## Pending (from the 2026-10-08 design handoff)

None of these has a source or licence on file. To add one: put the file here,
add its row above, then restore the CSS or markup listed for it.

| File | Page | Restore |
|---|---|---|
| `codrington-library.jpeg` | `original-bluebook-teacher.html` | frame photo, rule A with `url('assets/codrington-library.jpeg') center 42%/cover no-repeat`, opacity `.78` |
| `radcliffe-interior.avif` | `original-review.html` | frame photo, rule A with `url('assets/radcliffe-interior.avif') center 34%/cover no-repeat`, tint `0.55`, brightness `.54` |
| `radcliffe-observatory-watercolour.jpg` | `original-quantum.html` | frame photo, rule A with `url('assets/radcliffe-observatory-watercolour.jpg') center 38%/cover no-repeat`, saturate `.6`, brightness `.5`, opacity `.72` |
| `st-andrews-quad.jpg` | `original-students.html` | frame photo, rule A with `url('assets/st-andrews-quad.jpg') center 58%/cover no-repeat`, tint `0.54`, saturate `.58`, brightness `.5` |
| `gonville-caius-facade.png` | `original-reports.html` | frame photo, rule A with `url('assets/gonville-caius-facade.png') center 46%/cover no-repeat`, tint `0.52`, saturate `.6` |
| `radcliffe-night-stars.jpeg` | `original-dashboard.html`, `original-baseline-voice.html` | in `.hero-photo`, replace the `radial-gradient(...)` background with `url('assets/radcliffe-night-stars.jpeg') center 62%/cover no-repeat` |
| `white-stag.png` | `original-my-work.html` | add rule B |
| `long-room-library.png` | `original-library.html` | add `<img src="assets/long-room-library.png" alt="The Long Room library" />` as the first child of `.band`, plus rule C |
| `all-souls-engraving-wide.png` | `original-voice.html` | add `<img src="assets/all-souls-engraving-wide.png" alt="..." />` inside `.hero-bg`. This one looks AI-generated in an engraving style: replace it with a genuine public-domain scan, credited as what it is. |

Rule A (framed pages; the values above override the defaults shown):

```css
.frame::before{content:'';position:absolute;inset:0;z-index:0;pointer-events:none;background:linear-gradient(rgba(22,36,79,0.5),rgba(22,36,79,0.5)),URL_HERE;background-blend-mode:color,normal;filter:saturate(.55) brightness(.52) contrast(1.12) hue-rotate(184deg);opacity:.78;}
```

Rule B (`original-my-work.html`):

```css
body::before{content:'';position:fixed;inset:0;z-index:-2;background:url('assets/white-stag.png') center 30%/cover no-repeat;filter:saturate(.5) brightness(.5) contrast(1.02);}
```

Rule C (`original-library.html`):

```css
.band img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:50% 44%;filter:saturate(.72) brightness(.96);}
```

# Navy demo suite (fictional)

A static, clickable demonstration of the navy teacher and student design
(Claude Design handoff, 2026-10-08), cleaned to NORTH_STAR before it shipped.
Everything here is invented: no API calls, no accounts, no student data.

- **Open it locally:** `python run.py --demo --frontend-dir demo/`, then
  `/prototypes/navy/`. The whole `/prototypes` tree returns 404 on real
  deploys (`original/api.py`, `_DEMO_ONLY_STATIC_PREFIXES`).
- **Published:** `scripts/build_teacher_demo_site.sh` copies this folder to
  `prototypes/navy/` on the `bluebook-teacher-demo` static site, whose front
  page opens `index.html` here.
- **Rules the tests hold** (`tests/test_teacher_demo_site.py`): every page
  carries the fictional banner; every page that shows an Original result
  carries the testing-phase notice; no third-party hosts; none of the removed
  claims (keystroke collection, AI-authorship labels, made-up feature counts,
  writer-similarity percentages) come back; every link resolves; every image
  is credited in `assets/CREDITS.md`; `js/feature-data.js` lists exactly the
  97 active features with the product's tier names.
- **Not the live product.** The live teacher and student UI is
  `demo/bluebook/` and `demo/professor.html` / `demo/student.html`. Porting
  this look into those, with real data, is separate work.

# Teacher dashboard and professor demonstration

Design source: https://claude.ai/design/p/019e2463-71f4-7e31-9385-3aef7323dd72?file=original-bluebook-teacher.html

The selected Claude Design HTML and its codrington-library.jpeg asset were downloaded through the project's Files interface on September 30, 2026. The layout has been ported to React rather than embedding the disconnected prototype.

## Entry points

- `/bluebook/teacher-demo.html`: fictional professor walkthrough, with local-in-memory sessions, a student writing preview, a submission reader and an explanatory report page. Reset or refresh clears the preview. It does not call API methods, write browser storage, impersonate a signed-in account, or compute an analysis score. Fonts may load from Google Fonts, matching the existing application; serif fallbacks work offline.
- `/bluebook/`: normal login/invitation/student entry. Signed-in teachers reach the new three-step session setup. The existing staff API supplies classes and exams; creating an exam writes through the existing authenticated client. Students retain their existing application flow.

`TeacherWorkspace.jsx` supplies the shared frame and session form. `teacher-demo.jsx` provides fixtures without switching the global API client or modifying authentication state. API failures in live mode do not fall back to demo records. The two pages have separate bundles but share the same React source for their layout and setup controls.

## Changes to prototype claims

No typing-rhythm collection claims; no automatic conversion of every submission into an authenticated baseline; no fixed number of sessions claimed to establish authorship; no fake join code. The live save receipt points teachers to existing session management and tells rostered students to use My exams. Only a successful server response clears questions. Additional questions are numbered in the backend's existing single prompt field. Bluebook-only workspaces receive no baseline/analysis promises.

## Build and verification

`npm ci && npm run build` builds both entries plus their CSS. Commit both main bundle files, both CSS files and the standalone demo bundle. The application server does not need Node at runtime.

Verified September 30:
- Build succeeded.
- 147 selected Python tests passed: test_bluebook_self_serve.py, test_bluebook_crud.py, security/test_static_tree.py, excluding blocker/certification.
- Browser demonstration journey: create fictional session, preview booklet, submit example prose, read it, reset.
- Real local API/UI journey in a separate disposable SQLite database: sign in, load course, create published exam with two questions, open management, verify stored prompt/course/duration/status through API.
- Desktop two-column layout inspected and no demo console errors observed. A requested narrow viewport override did not take effect in the browser tool; phone-width visual verification remains outstanding.

Existing broader institutional privacy, model-validity, deletion and token-revocation gaps are unchanged. The Original analysis pages themselves are not fully redesigned by this change; the shared frame currently surrounds Bluebook teacher tools. No deployment or production student data was used.

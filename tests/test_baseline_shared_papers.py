"""Voice Baseline's "Papers students shared" actions (2026-11, four-paper alpha).

A teacher can read a shared paper's text without adding it (so a paper kept
aside as the held-out paper can still be read and copied into Writing State),
and can undo an approval, which takes the paper back out of the baseline and
leaves it waiting again. The page's own script is run under node against
stubbed endpoints, reusing the Voice Baseline harness's DOM stubs.
"""

from __future__ import annotations

import json
import shutil
import subprocess

from tests.test_original_suite_static import BASELINE_HARNESS, SUITE, _baseline_page, needs_node

PAPER_TEXT = "My grandmother kept bees. <b>Not markup</b> & the hives hummed all summer."

_ROUTES = r"""
  if (path === '/bluebook/past-papers' && method === 'GET') return [200, { papers: shared }];
  if (path === '/bluebook/past-papers/p1' && method === 'GET') return [200, { paper_id: 'p1', student_id: 's1', title: 'Bees', status: 'pending', text: sc.paperText }];
  if (path === '/bluebook/past-papers/p2/unapprove' && method === 'POST') { shared[1].status = 'pending'; return [200, { paper_id: 'p2', status: 'pending', removed: 1 }]; }
  return [404, {}];
}
const shared = [
  { paper_id: 'p1', student_id: 's1', student: 'Ada', title: 'Bees', word_count: 300, status: 'pending', shared_at: '2026-11-01', baseline_source: 'independent' },
  { paper_id: 'p2', student_id: 's1', student: 'Ada', title: 'Rivers', word_count: 320, status: 'approved', shared_at: '2026-11-02', baseline_source: 'independent' },
  { paper_id: 'p3', student_id: 's2', student: 'Ben', title: 'Not Ada', word_count: 310, status: 'pending', shared_at: '2026-11-03', baseline_source: 'independent' },
];
"""

_MAIN = r"""
(async () => {
  const list = el('shared-list');
  const textBox = makeEl('text-box');
  list.querySelector = () => textBox;
  const press = async (act, id) => {
    const btn = { disabled: false, getAttribute: (k) => ({ 'data-sact': act, 'data-id': id })[k] };
    for (const fn of list.handlers.click || []) await fn({ target: { closest: () => btn } });
  };
  for (let i = 0; i < 300 && !list.innerHTML.includes('data-sact="read"'); i++) await sleep(10);
  const out = { first: list.innerHTML };
  await press('read', 'p1');
  out.read = { html: list.innerHTML, text: textBox.textContent };
  const posts = () => calls.filter((c) => c.startsWith('POST'));
  out.postsAfterRead = posts();
  await press('read', 'p1');
  out.hidden = list.innerHTML;
  const before = calls.filter((c) => c === 'GET /students/s1').length;
  await press('unapprove', 'p2');
  for (let i = 0; i < 100 && !list.innerHTML.includes('Taken back out'); i++) await sleep(10);
  out.undone = list.innerHTML;
  out.posts = posts();
  out.refetched = calls.filter((c) => c === 'GET /students/s1').length > before;
  process.stdout.write(JSON.stringify(out));
  process.exit(0);
})();
"""


def _harness() -> str:
    head, sep, _ = BASELINE_HARNESS.partition("(async () => {")
    assert sep, "the Voice Baseline harness changed shape"
    marker = "  return [404, {}];\n}\n"
    assert marker in head
    return head.replace(marker, _ROUTES, 1) + _MAIN


def _run() -> dict:
    run = subprocess.run(
        [shutil.which("node"), "-e", _harness()],
        input=json.dumps(
            {
                "live": str(SUITE / "live.js"),
                "page": str(SUITE / "baseline.html"),
                "features": str(SUITE / "js" / "feature-data.js"),
                "paperText": PAPER_TEXT,
            }
        ),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout, "the page never finished loading"
    return json.loads(run.stdout)


@needs_node
def test_read_shows_the_text_as_text_without_writing_anything():
    out = _run()
    first = out["first"]
    # Only the chosen student's papers; every row can be read.
    assert "Bees" in first and "Rivers" in first and "Not Ada" not in first
    assert first.count('data-sact="read"') == 2
    # A pending paper offers Approve and Decline, never Undo; an approved one offers Undo only.
    assert 'data-sact="approve" data-id="p1"' in first and 'data-sact="unapprove" data-id="p1"' not in first
    assert 'data-sact="unapprove" data-id="p2"' in first and 'data-sact="approve" data-id="p2"' not in first
    assert 'data-sact="decline" data-id="p2"' not in first
    read = out["read"]
    assert 'aria-expanded="true"' in read["html"] and "Hide paper" in read["html"]
    assert 'href="writing-state.html?student=s1"' in read["html"]
    assert "Open Writing State for Ada" in read["html"] and "Copy text" in read["html"]
    assert "does not add it to the baseline" in read["html"]
    # The words are put in as text, never as markup.
    assert read["text"] == PAPER_TEXT
    assert "<b>Not markup</b>" not in read["html"]
    # Reading wrote nothing.
    assert out["postsAfterRead"] == []
    # Pressing it again hides the paper.
    assert "sh-read" not in out["hidden"] and "Read this paper" in out["hidden"]


@needs_node
def test_undo_posts_once_shows_the_paper_waiting_again_and_rereads_the_student():
    out = _run()
    assert out["posts"] == ["POST /bluebook/past-papers/p2/unapprove"]
    undone = out["undone"]
    assert "Taken back out of the baseline. It is waiting for your approval again." in undone
    assert 'data-sact="approve" data-id="p2"' in undone
    assert out["refetched"] is True


def test_the_page_reads_and_undoes_only_through_the_past_paper_routes():
    page = _baseline_page()
    assert "Live.api('/bluebook/past-papers/'+enc(id))" in page
    assert "'/bluebook/past-papers/'+enc(id)+'/'+act,{method:'POST'}" in page
    assert "box.textContent=" in page
    # The Text setting applies here as on every other page.
    assert '<link rel="stylesheet" href="../assets/type.css" />' in page
    assert '<script src="../assets/display-prefs.js" data-float></script>' in page
    for word in ("ai detection", "cheating", "authorship verification"):
        assert word not in page.lower()

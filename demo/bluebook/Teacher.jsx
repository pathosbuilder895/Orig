import React from 'react';
import { createPortal, flushSync } from 'react-dom';
import { BB_API } from './components.jsx';
import {
  Badge, Btn, ErrorText, Field, LinkBtn, Notice, Page, Panel, Section, Select, Stat, Table, TextArea,
  absoluteLink, copyText, csvCell, downloadText, fromLocalInput, questionsOf, toLocalInput, when,
} from './forms.jsx';
import { ProctorScreen } from './ProctorTiles.jsx';

// ════════════════════════════════════════════════════════════════
//  BLUEBOOK — Teacher screens (inside TeacherFrame)
//  Examinations · Manage exam (grading, release, export) · Courses ·
//  Roster & invitations · Students · Submissions · Proctor (live)
// ════════════════════════════════════════════════════════════════
const { useState, useEffect, useLayoutEffect, useRef } = React;

const WARNING_LABEL = {
  focus_lost: 'Left the window',
  tab_hidden: 'Hid the tab',
  fullscreen_exit: 'Left full-screen',
  print_or_save: 'Tried to print or save',
  paste_blocked: 'Tried to paste',
  other: 'Other',
};

// The session notes on one line: "Left the window × 2 · Tried to paste × 1".
function notesSummary(warnings) {
  const counts = {};
  (warnings || []).forEach(w => { const t = (w && w.type) || 'other'; counts[t] = (counts[t] || 0) + 1; });
  const parts = Object.entries(counts).map(([t, n]) => `${WARNING_LABEL[t] || t} × ${n}`);
  return parts.length ? parts.join(' · ') : 'none';
}

// "13 Oct 2026, 09:30 · 412 words · 47 min · after the deadline"
function submittedLine(sub) {
  return [
    sub.created_at ? when(sub.created_at) : null,
    sub.words != null ? `${sub.words} words` : null,
    sub.timeMin != null ? `${sub.timeMin} min` : null,
    sub.late ? 'after the deadline' : null,
  ].filter(Boolean).join(' · ');
}

// One sealed submission as plain text, for the reader's "Download as text".
// Only what the stored record holds and the reader shows: never a score.
export function submissionAsText(sub) {
  const s = sub || {};
  const lines = [s.exam || 'Examination', '', `Student: ${s.student || 'Student'}`];
  if (s.course) lines.push(`Course: ${s.course}`);
  const submitted = submittedLine(s);
  if (submitted) lines.push(`Submitted: ${submitted}`);
  lines.push(`Session notes: ${notesSummary(s.warnings)}`);
  if (s.mark) lines.push(`Mark: ${s.mark}`);
  if (s.feedback) lines.push(`Feedback: ${s.feedback}`);
  const answers = Array.isArray(s.answers) && s.answers.length ? s.answers : null;
  const questions = s.questions || [];
  if (answers) {
    answers.forEach((a, i) => {
      lines.push('', `Question ${i + 1}${questions[i] ? `: ${questions[i]}` : ''}`, a || '(No answer.)');
    });
  } else {
    lines.push('', s.text || 'The text of this submission is not available.');
  }
  return lines.join('\n') + '\n';
}

const fileSlug = v => String(v || '').replace(/[^A-Za-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60);

export function submissionFilename(sub) {
  const s = sub || {};
  const parts = [fileSlug(s.exam), fileSlug(s.student) || (fileSlug(s.exam) ? 'submission' : '')].filter(Boolean);
  return (parts.join('-') || 'submission') + '.txt';
}

// The printed copy of the open submission. It lives outside the app root
// (a portal on <body>), so print CSS can show it alone: no navigation, no
// form fields, no dark page. It is on the page only while printing (see
// usePrinting), so the screen never holds a second copy of the text.
function PrintSheet({ sub }) {
  const [host] = useState(() => {
    const d = document.createElement('div');
    d.className = 'bb-print-root';
    return d;
  });
  // Layout effect: in place before the browser lays out the printed page.
  useLayoutEffect(() => {
    document.body.appendChild(host);
    document.body.classList.add('bb-has-print-sheet');
    return () => { host.remove(); document.body.classList.remove('bb-has-print-sheet'); };
  }, []);
  const answers = Array.isArray(sub.answers) && sub.answers.length ? sub.answers : null;
  const questions = sub.questions || [];
  return createPortal(
    <article className="bb-print-sheet">
      <p className="bb-print-kicker">Collections · sealed submission</p>
      <h1>{sub.exam || 'Examination'}</h1>
      <dl>
        <dt>Student</dt><dd>{sub.student || 'Student'}</dd>
        {sub.course && <><dt>Course</dt><dd>{sub.course}</dd></>}
        <dt>Submitted</dt><dd>{submittedLine(sub) || 'Not recorded'}</dd>
        <dt>Session notes</dt><dd>{notesSummary(sub.warnings)}</dd>
        {sub.mark && <><dt>Mark</dt><dd>{sub.mark}</dd></>}
        {sub.feedback && <><dt>Feedback</dt><dd className="bb-print-text">{sub.feedback}</dd></>}
      </dl>
      {answers ? answers.map((a, i) => (
        <section key={i}>
          <h2>Question {i + 1}</h2>
          {questions[i] && <p className="bb-print-q">{questions[i]}</p>}
          <div className="bb-print-text">{a || 'No answer.'}</div>
        </section>
      )) : <div className="bb-print-text">{sub.text || 'The text of this submission is not available.'}</div>}
      <p className="bb-print-foot">Session notes are context, not evidence.</p>
    </article>,
    host,
  );
}

export function examState(e) {
  const status = String(e.status || 'DRAFT').toUpperCase();
  if (status === 'DRAFT') return 'draft';
  if (status === 'CLOSED' || status === 'ARCHIVED') return 'closed';
  const now = Date.now();
  if (e.opens_at && now < Date.parse(e.opens_at)) return 'upcoming';
  if (e.closes_at && now >= Date.parse(e.closes_at)) return 'closed';
  return 'open';
}

export function openManageExam(examId, onNavigate) {
  window.BB_MANAGE_EXAM = examId;
  onNavigate('manage-exam');
}

export function openRoster(course, onNavigate) {
  window.BB_ROSTER_COURSE = course;
  onNavigate('roster');
}

// Professor-approved writing baselines (plan Phase 7). Only a workspace that
// holds Original sees these controls; a sealed exam enters a student's
// baseline only when a professor adds it here or in bulk.
const BASELINE_MESSAGE = {
  added: name => `Added to ${name}'s baseline.`,
  already_in_baseline: () => 'Already in the baseline.',
  removed: name => `Removed from ${name}'s baseline.`,
  not_in_baseline: () => 'It was not in the baseline.',
};

// An unknown future status must not throw inside a handler.
const baselineMessage = (status, name) => (BASELINE_MESSAGE[status] ? BASELINE_MESSAGE[status](name) : 'Done.');

export function baselineSummary(r) {
  const parts = [
    `${r.added} added`,
    `${r.already_in_baseline} already in baseline`,
    `${r.held} not added (differ strongly from earlier samples)`,
  ];
  if (r.needs_review) parts.push(`${r.needs_review} set aside for your review (late or with lockdown warnings)`);
  if (r.nothing_written) parts.push(`${r.nothing_written} with nothing written`);
  if (r.errors) parts.push(`${r.errors} could not be added`);
  const rows = r.results || [];
  const held = rows.filter(x => x.status === 'held').map(x => x.student).filter(Boolean);
  const setAside = rows.filter(x => x.status === 'needs_review')
    .map(x => `${x.student || 'Candidate'} (${x.detail})`);
  let text = parts.join(' · ') + '.';
  if (held.length) text += ` Not added: ${held.join(', ')}.`;
  if (setAside.length) text += ` Set aside: ${setAside.join(', ')}.`;
  return text;
}

function BaselineControl({ sub }) {
  const [inBaseline, setInBaseline] = useState(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  // After a held result the Add button stays hidden until the reader is
  // reopened: approval cannot override the check, and every retry would
  // only advance the drift counter.
  const [held, setHeld] = useState(false);
  const name = sub.student || 'the student';

  // `isLive` lets the effect drop a late answer after unmount; Try again
  // always applies its own result.
  function loadStatus(isLive = () => true) {
    setLoadFailed(false); setError('');
    return BB_API.examBaselineStatus(sub.exam_id).then(d => {
      if (!isLive()) return;
      const row = (d.submissions || []).find(r => r.submission_id === sub.id);
      setInBaseline(row ? !!row.in_baseline : false);
    }).catch(err => {
      if (!isLive()) return;
      setLoadFailed(true);
      setError(err.message || 'Could not load the baseline status.');
    });
  }

  useEffect(() => {
    let live = true;
    setHeld(false); setMessage('');
    if (!sub.exam_id) return undefined;
    loadStatus(() => live);
    return () => { live = false; };
  }, [sub.id, sub.exam_id]);

  async function add() {
    setBusy(true); setError(''); setMessage('');
    try {
      const r = await BB_API.addToBaseline(sub.id);
      if (r.status === 'held') { setHeld(true); setMessage(r.detail); }
      else {
        if (r.status === 'added' || r.status === 'already_in_baseline') setInBaseline(true);
        setMessage(baselineMessage(r.status, name));
      }
    } catch (err) { setError(err.message || 'Could not add to the baseline.'); }
    setBusy(false);
  }

  async function remove() {
    if (!confirm(`Remove this exam from ${name}'s baseline? Their profile is recomputed from the remaining samples.`)) return;
    setBusy(true); setError(''); setMessage('');
    try {
      const r = await BB_API.removeFromBaseline(sub.id);
      if (r.status === 'removed' || r.status === 'not_in_baseline') setInBaseline(false);
      setMessage(baselineMessage(r.status, name));
    } catch (err) { setError(err.message || 'Could not remove from the baseline.'); }
    setBusy(false);
  }

  if (!sub.exam_id) return null;
  return (
    <div className="bb-baseline" style={{ margin: '1rem 0' }}>
      <p style={{ margin: '0 0 .4rem' }}>
        <strong>Writing baseline:</strong>{' '}
        {loadFailed ? 'unavailable' : inBaseline === null ? 'checking…' : inBaseline ? 'In baseline' : 'Not in baseline'}
      </p>
      <p className="bb-hint" style={{ margin: '0 0 .6rem' }}>
        The baseline is {name}'s own reference writing. Sealed exams join it only when you add them.
      </p>
      {loadFailed && <Btn onClick={() => loadStatus()}>Try again</Btn>}
      {inBaseline === true && <Btn onClick={remove} disabled={busy}>Remove from baseline</Btn>}
      {inBaseline === false && !held && <Btn onClick={add} disabled={busy}>Add to baseline</Btn>}
      <Notice>{message}</Notice>
      <ErrorText>{error}</ErrorText>
    </div>
  );
}

// ─── Reading one submission (with grading) ───────────────────────────────────
// Whether the page is being printed. The browser's own Print fires
// beforeprint, and the change is flushed at once so the sheet is in place
// before the page is laid out for printing; print() asks the same way.
function usePrinting() {
  const [printing, setPrinting] = useState(false);
  useEffect(() => {
    const before = () => flushSync(() => setPrinting(true));
    const after = () => setPrinting(false);
    window.addEventListener('beforeprint', before);
    window.addEventListener('afterprint', after);
    return () => {
      window.removeEventListener('beforeprint', before);
      window.removeEventListener('afterprint', after);
    };
  }, []);
  const print = () => {
    flushSync(() => setPrinting(true));
    try { window.print(); } finally { setPrinting(false); }
  };
  return [printing, print];
}

export function SubmissionReader({ submissionId, onClose, onSaved }) {
  const [printing, print] = usePrinting();
  const [sub, setSub] = useState(null);
  const [error, setError] = useState('');
  const [loadError, setLoadError] = useState(null);   // null: no failure
  const [attempt, setAttempt] = useState(0);
  const [mark, setMark] = useState('');
  const [feedback, setFeedback] = useState('');
  const [saved, setSaved] = useState('');
  const [busy, setBusy] = useState(false);
  const headingRef = useRef(null);

  useEffect(() => {
    let live = true;
    setSub(null); setError(''); setLoadError(null); setSaved('');
    BB_API.getSubmission(submissionId).then(s => {
      if (!live) return;
      setSub(s); setMark(s.mark || ''); setFeedback(s.feedback || '');
      setTimeout(() => headingRef.current && headingRef.current.focus(), 0);
    }).catch(err => { if (live) setLoadError((err && err.message) || ''); });
    return () => { live = false; };
  }, [submissionId, attempt]);

  async function save(e) {
    e.preventDefault();
    setBusy(true); setError(''); setSaved('');
    try {
      const s = await BB_API.saveFeedback(submissionId, { mark, feedback });
      setSub(prev => ({ ...prev, ...s }));
      setSaved('Saved. Students see it once you release results for this exam.');
      onSaved && onSaved();
    } catch (err) { setError(err.message || 'Could not save.'); }
    setBusy(false);
  }

  const answers = (sub && sub.answers && sub.answers.length) ? sub.answers : null;
  const questions = (sub && sub.questions) || [];

  return (
    <Panel className="bb-reader">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <h2 ref={headingRef} tabIndex={-1}>{sub ? (sub.student || 'Candidate') : 'Submission'}</h2>
          {sub && <p className="bb-meta">{submittedLine(sub)}</p>}
        </div>
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'baseline' }}>
          {sub && <LinkBtn onClick={print}>Print</LinkBtn>}
          {sub && <LinkBtn onClick={() => downloadText(submissionFilename(sub), submissionAsText(sub), 'text/plain')}>Download as text</LinkBtn>}
          <LinkBtn muted onClick={onClose}>Close</LinkBtn>
        </div>
      </div>
      {!sub && loadError === null && <p role="status" className="bb-meta">Loading the submission…</p>}
      {!sub && loadError !== null && (
        <div>
          <ErrorText>{`We could not load this submission. ${loadError}`.trim()}</ErrorText>
          <Btn onClick={() => setAttempt(n => n + 1)}>Try again</Btn>
        </div>
      )}
      <ErrorText>{error}</ErrorText>
      {sub && (
        <>
          {printing && <PrintSheet sub={sub} />}
          <p style={{ margin: '1rem 0 .3rem' }}>
            <strong>Session notes ({(sub.warnings || []).length}):</strong>{' '}
            {(sub.warnings || []).length === 0 ? 'none.' : notesSummary(sub.warnings)}
          </p>
          <p className="bb-hint" style={{ marginBottom: '1rem' }}>Notes are context, not evidence. A student may leave full screen by accident.</p>
          <div className="bb-paper">
            {answers ? answers.map((a, i) => (
              <div key={i} className="bb-answer">
                <h3>Question {i + 1}{questions[i] ? ` — ${questions[i].slice(0, 120)}${questions[i].length > 120 ? '…' : ''}` : ''}</h3>
                <div>{a || <em>No answer.</em>}</div>
              </div>
            )) : (sub.text || 'The text of this submission was not stored (it was sealed before text storage existed).')}
          </div>
          {BB_API.hasOriginal() && <BaselineControl sub={sub} />}
          <form onSubmit={save} style={{ marginTop: '1.2rem' }}>
            <div className="bb-grid cols-3">
              <Field id={`mark-${submissionId}`} label="Mark (optional)" value={mark} onChange={setMark}
                required={false} maxLength={20} placeholder="e.g. 18/20 or B+" />
            </div>
            <TextArea id={`feedback-${submissionId}`} label="Feedback for the student (optional)" value={feedback}
              onChange={setFeedback} rows={4} maxLength={5000} />
            <Notice>{saved}</Notice>
            <Btn primary type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save mark and feedback'}</Btn>
          </form>
        </>
      )}
    </Panel>
  );
}

// ─── Submissions table (shared) ──────────────────────────────────────────────
export function SubmissionsTable({ subs, showExam = false, empty = 'No sealed exams yet. They appear here as students submit them.', onChanged }) {
  const [open, setOpen] = useState('');
  const columns = [
    { key: 'student', label: 'Student', lead: true, render: s => <>{s.student}{s.late ? <> <Badge tone="bad">late</Badge></> : null}</> },
    showExam && { key: 'exam', label: 'Examination' },
    { key: 'created_at', label: 'Submitted', render: s => when(s.created_at) },
    { key: 'words', label: 'Words', num: true },
    { key: 'warnings', label: 'Notes', num: true, render: s => (s.warnings || []).length },
    { key: 'mark', label: 'Mark', render: s => s.mark || '—' },
    { key: 'read', label: 'Read', actions: true, render: s => (
      <LinkBtn onClick={() => setOpen(open === s.id ? '' : s.id)} aria-expanded={open === s.id}>
        {open === s.id ? 'Hide' : 'Read & mark'}
      </LinkBtn>
    ) },
  ].filter(Boolean);
  // null: the list has not arrived yet, which is not the same as empty.
  if (subs === null) return <p role="status" className="bb-empty">Loading submissions…</p>;
  return (
    <>
      <Table columns={columns} rows={subs} rowKey={s => s.id} empty={empty} caption="Submissions" />
      {open && <div style={{ marginTop: '1rem' }}><SubmissionReader submissionId={open} onClose={() => setOpen('')} onSaved={onChanged} /></div>}
    </>
  );
}

export function AllSubmissionsScreen() {
  const [subs, setSubs] = useState(null);
  const [error, setError] = useState('');
  const load = () => {
    setError('');
    return BB_API.listSubmissions().then(setSubs).catch(err => setError(err.message || 'Could not load submissions.'));
  };
  useEffect(() => { load(); }, []);
  return (
    <Page eyebrow="Your workspace" title="Submissions" meta={error ? 'Submissions unavailable' : subs === null ? 'Loading…' : `${subs.length} sealed`}>
      <ErrorText>{error}</ErrorText>
      {error ? <Btn onClick={load}>Try again</Btn> : subs === null ? <p role="status">Loading submissions…</p> : <SubmissionsTable subs={subs} showExam onChanged={load} />}
    </Page>
  );
}

// ─── Examinations list ───────────────────────────────────────────────────────
export function ExamsListScreen({ onNavigate }) {
  const [exams, setExams] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    BB_API._json('GET', '/bluebook/exams').then(d => setExams(d.exams || []))
      .catch(err => { setError(err.message || 'Could not load examinations.'); setExams([]); });
  }, []);
  const columns = [
    { key: 'title', label: 'Examination', lead: true, render: e => (
      <LinkBtn onClick={() => openManageExam(e.id, onNavigate)} style={{ textAlign: 'left', padding: 0 }}>{e.title}</LinkBtn>
    ) },
    { key: 'course', label: 'Course', render: e => e.course || '—' },
    { key: 'state', label: 'Status', render: e => <Badge>{examState(e)}</Badge> },
    { key: 'window', label: 'Closes', render: e => e.closes_at ? when(e.closes_at) : '—' },
    { key: 'duration', label: 'Minutes', num: true },
    { key: 'submissions', label: 'Submitted', num: true },
    { key: 'released', label: 'Results', render: e => e.results_released_at ? <Badge>released</Badge> : '—' },
  ];
  return (
    <Page eyebrow="Your workspace" title="Examinations"
      meta={exams === null ? 'Loading…' : `${exams.length} examination${exams.length === 1 ? '' : 's'}`}
      actions={<>
        <Btn onClick={() => onNavigate('sessions')}>Quick session</Btn>
        <Btn primary onClick={() => onNavigate('new-exam')}>+ New examination</Btn>
      </>}>
      <ErrorText>{error}</ErrorText>
      <Table columns={columns} rows={exams || []} rowKey={e => e.id} caption="Examinations"
        empty="No examinations yet. Start a quick session or create a full examination." />
    </Page>
  );
}

// ─── Manage one exam ─────────────────────────────────────────────────────────
export function ManageExamScreen({ onNavigate, onPreview }) {
  const examId = window.BB_MANAGE_EXAM;
  const [exam, setExam] = useState(null);
  const [subs, setSubs] = useState(null);   // null until the list arrives
  const [courses, setCourses] = useState([]);
  const [form, setForm] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);

  async function load() {
    setError('');
    try {
      const [e, all, cs] = await Promise.all([
        BB_API.getExam(examId), BB_API.listSubmissions(), BB_API.listCourses(),
      ]);
      setExam(e);
      setSubs((all || []).filter(s => s.exam_id === examId));
      setCourses(cs || []);
      setForm({
        title: e.title || '', status: (e.status || 'DRAFT').toUpperCase(),
        duration: e.duration || 90, course_id: e.course_id || '',
        opens: toLocalInput(e.opens_at), closes: toLocalInput(e.closes_at),
        questions: questionsOf(e).length ? questionsOf(e) : [''],
      });
    } catch (err) { setError(err.message || 'Could not load the exam.'); }
  }
  useEffect(() => { if (!examId) onNavigate('exams'); else load(); }, []);

  const setField = (k) => (v) => setForm(f => ({ ...f, [k]: v }));
  const setQuestion = (i, v) => setForm(f => ({ ...f, questions: f.questions.map((q, j) => j === i ? v : q) }));

  async function save() {
    setBusy(true); setError(''); setNotice('');
    const course = courses.find(c => c.id === form.course_id);
    try {
      await BB_API.updateExam(examId, {
        title: form.title, status: form.status, duration: Number(form.duration) || 90,
        questions: form.questions.map(q => q.trim()).filter(Boolean),
        course_id: form.course_id || null, course: course ? (course.code || course.name) : (exam.course || ''),
        opens_at: fromLocalInput(form.opens), closes_at: fromLocalInput(form.closes),
      });
      setNotice('Saved.');
      await load();
    } catch (err) { setError(err.message || 'Could not save.'); }
    setBusy(false);
  }

  async function toggleRelease() {
    setError(''); setNotice('');
    try {
      if (exam.results_released_at) await BB_API.unreleaseResults(examId);
      else await BB_API.releaseResults(examId);
      setNotice(exam.results_released_at ? 'Results hidden from students again.' : 'Results released. Students can now see their marks and feedback.');
      await load();
    } catch (err) { setError(err.message || 'Could not change release.'); }
  }

  async function remove() {
    if (!confirm('Delete this examination? This cannot be undone.')) return;
    try { await BB_API.deleteExam(examId); onNavigate('exams'); }
    catch (err) { setError(err.message || 'Could not delete.'); }
  }

  async function exportCsv() {
    setError('');
    try { await BB_API.downloadExport(examId, exam && exam.title); }
    catch (err) { setError(err.message || 'Export failed.'); }
  }

  async function addAllToBaselines() {
    if (!confirm('Add every sealed submission of this examination to the students’ writing baselines? Late sittings and sittings with lockdown warnings are set aside for you to review one at a time, and exams that differ strongly from a student’s existing samples are not added.')) return;
    setBulkBusy(true); setError(''); setNotice('');
    try { setNotice(baselineSummary(await BB_API.addExamToBaselines(examId))); }
    catch (err) { setError(err.message || 'Could not add to baselines.'); }
    finally { setBulkBusy(false); }
  }

  const subList = subs || [];
  const graded = subList.filter(s => s.mark || s.feedback).length;
  return (
    <Page
      eyebrow="Examination"
      title={exam ? exam.title : 'Examination'}
      meta={exam ? [exam.course, subs === null ? null : `${subList.length} submission${subList.length === 1 ? '' : 's'}`, subs === null ? null : `${graded} marked`].filter(Boolean).join(' · ') : 'Loading…'}
      actions={exam && <>
        <Btn onClick={() => onNavigate('exams')}>← Examinations</Btn>
        <Btn onClick={() => { window.BB_PROCTOR_EXAM = examId; onNavigate('proctor'); }}>Watch live</Btn>
        <Btn onClick={() => onPreview(exam)}>Preview</Btn>
        <Btn onClick={exportCsv}>Export CSV</Btn>
        {BB_API.hasOriginal() && (
          <Btn onClick={addAllToBaselines} disabled={bulkBusy}>
            {bulkBusy ? 'Adding…' : 'Add all sealed submissions to baselines'}
          </Btn>
        )}
      </>}
    >
      <ErrorText>{error}</ErrorText>
      <Notice>{notice}</Notice>
      {exam && (
        <Panel style={{ marginBottom: '1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
          <div>
            <h2 style={{ marginBottom: '.2rem' }}>Results</h2>
            <p className="bb-meta">{exam.results_released_at
              ? `Released ${when(exam.results_released_at)}. Students see their marks and feedback.`
              : 'Hidden. Students cannot see marks or feedback until you release them.'}</p>
          </div>
          <Btn primary={!exam.results_released_at} onClick={toggleRelease}>
            {exam.results_released_at ? 'Hide results' : 'Release results'}
          </Btn>
        </Panel>
      )}
      <Section title="Submissions">
        {subs === null && error
          ? <Btn onClick={load}>Try again</Btn>
          : <SubmissionsTable subs={subs} onChanged={load} empty="Nobody has submitted yet. Sealed exams appear here as students submit them." />}
      </Section>
      {form && (
        <Section title="Settings">
          <Panel>
            <div className="bb-grid cols-3">
              <Field id="meTitle" label="Title" value={form.title} onChange={setField('title')} />
              <Select id="meStatus" label="Status" value={form.status} onChange={setField('status')}>
                <option value="DRAFT">Draft (hidden from students)</option>
                <option value="ACTIVE">Published</option>
                <option value="CLOSED">Closed</option>
              </Select>
              <Field id="meDuration" label="Duration (minutes)" type="number" min="1" value={form.duration} onChange={setField('duration')} />
            </div>
            <div className="bb-grid cols-3">
              <Select id="meCourse" label="Course" value={form.course_id} onChange={setField('course_id')}>
                <option value="">Everyone in the workspace</option>
                {courses.map(c => <option key={c.id} value={c.id}>{c.code ? `${c.code} · ${c.name}` : c.name}</option>)}
              </Select>
              <Field id="meOpens" label="Opens (your local time)" type="datetime-local" required={false} value={form.opens} onChange={setField('opens')} />
              <Field id="meCloses" label="Closes (your local time)" type="datetime-local" required={false} value={form.closes} onChange={setField('closes')} />
            </div>
            {form.questions.map((q, i) => (
              <div key={i}>
                <TextArea id={`meQuestion${i}`} label={`Question ${i + 1}`} value={q} onChange={v => setQuestion(i, v)} rows={3} maxLength={8000} />
                {form.questions.length > 1 && (
                  <LinkBtn danger onClick={() => setForm(f => ({ ...f, questions: f.questions.filter((_, j) => j !== i) }))}>Remove question {i + 1}</LinkBtn>
                )}
              </div>
            ))}
            {form.questions.length < 20 && (
              <LinkBtn onClick={() => setForm(f => ({ ...f, questions: [...f.questions, ''] }))}>+ Add a question</LinkBtn>
            )}
            {subList.length > 0 && <p className="bb-hint">Students have already submitted. Changing questions now changes what later students see, not earlier answers.</p>}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem', flexWrap: 'wrap', marginTop: '1rem' }}>
              <LinkBtn danger onClick={remove} disabled={subs === null || subList.length > 0}>
                {subList.length > 0 ? 'Has submissions: close it instead of deleting' : 'Delete examination'}
              </LinkBtn>
              <Btn primary onClick={save} disabled={busy}>{busy ? 'Saving…' : 'Save changes'}</Btn>
            </div>
          </Panel>
        </Section>
      )}
    </Page>
  );
}

// ─── Courses ─────────────────────────────────────────────────────────────────
export function CoursesListScreen({ onNavigate }) {
  const [courses, setCourses] = useState(null);
  const [showNew, setShowNew] = useState(false);
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [term, setTerm] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const load = () => BB_API._json('GET', '/bluebook/courses').then(d => setCourses(d.courses || []))
    .catch(err => { setError(err.message || 'Could not load courses.'); setCourses([]); });
  useEffect(() => { load(); }, []);

  async function create(e) {
    e.preventDefault();
    setBusy(true); setError('');
    try {
      const c = await BB_API.createCourse({ code: code.trim(), name: name.trim(), term: term.trim(), status: 'ACTIVE' });
      setCode(''); setName(''); setTerm(''); setShowNew(false);
      openRoster(c, onNavigate);
    } catch (err) { setError(`The course was not created: ${err.message || 'unknown error'}.`); }
    setBusy(false);
  }

  const columns = [
    { key: 'name', label: 'Course', lead: true, render: c => (
      <LinkBtn onClick={() => openRoster(c, onNavigate)} style={{ textAlign: 'left', padding: 0 }}>
        {c.code ? `${c.code} · ${c.name}` : c.name}
      </LinkBtn>
    ) },
    { key: 'term', label: 'Term', render: c => c.term || '—' },
    { key: 'students', label: 'Students', num: true },
    { key: 'exams', label: 'Exams', num: true },
    { key: 'status', label: 'Status', render: c => <Badge>{c.active ? 'active' : 'closed'}</Badge> },
    { key: 'open', label: 'Roster', actions: true, render: c => <LinkBtn onClick={() => openRoster(c, onNavigate)}>Students & invitations →</LinkBtn> },
  ];
  return (
    <Page eyebrow="Your workspace" title="Courses" meta={courses === null ? 'Loading…' : `${courses.length} course${courses.length === 1 ? '' : 's'}`}
      actions={<Btn primary onClick={() => setShowNew(v => !v)} aria-expanded={showNew}>+ New course</Btn>}>
      <ErrorText>{error}</ErrorText>
      {showNew && (
        <Panel style={{ marginBottom: '1.5rem' }}>
          <form onSubmit={create}>
            <h2>New course</h2>
            <div className="bb-grid cols-3">
              <Field id="ncName" label="Course name" value={name} onChange={setName} placeholder="Introduction to Ethics" />
              <Field id="ncCode" label="Code (optional)" value={code} onChange={setCode} required={false} placeholder="ETH 101" />
              <Field id="ncTerm" label="Term (optional)" value={term} onChange={setTerm} required={false} placeholder="Fall 2026" />
            </div>
            <div className="bb-actions">
              <Btn primary type="submit" disabled={busy || !name.trim()}>{busy ? 'Creating…' : 'Create course'}</Btn>
              <LinkBtn muted onClick={() => setShowNew(false)}>Cancel</LinkBtn>
            </div>
          </form>
        </Panel>
      )}
      <Table columns={columns} rows={courses || []} rowKey={c => c.id} caption="Courses"
        empty="No courses yet. Create one, then add your students to it." />
    </Page>
  );
}

// ─── Roster & invitations ────────────────────────────────────────────────────
// "Ada Lovelace, ada@x.edu" / "ada@x.edu, Ada" / "ada@x.edu" — one per line.
// Lines with several addresses separated by commas or semicolons are split.
export function parseRosterInput(text) {
  const out = [];
  const seen = new Set();
  (text || '').split(/\n/).forEach(line => {
    const parts = line.split(/[;,\t]/).map(p => p.trim()).filter(Boolean);
    const emails = parts.filter(p => p.includes('@'));
    const names = parts.filter(p => !p.includes('@'));
    emails.forEach(raw => {
      const email = raw.replace(/^<|>$/g, '').toLowerCase();
      if (seen.has(email)) return;
      seen.add(email);
      out.push({ email, name: emails.length === 1 ? (names[0] || '') : '' });
    });
  });
  return out;
}

// "Copy all invite links": one line per student, name, email and link,
// separated by tabs, so the list reads as three columns when it is pasted
// into a spreadsheet and as one line per person anywhere else.
// Sorted by name, then email ("Volunteer 2" before "Volunteer 10"), so the
// list reads like the roster whatever order the server made the links in.
const byNameThenEmail = (a, b) => String(a.name || '').localeCompare(String(b.name || ''), undefined, { numeric: true, sensitivity: 'base' })
  || String(a.email || '').localeCompare(String(b.email || ''));
const withLinks = rows => rows.filter(r => r.invite_path).slice().sort(byNameThenEmail);

export function linksAsText(rows) {
  return withLinks(rows)
    .map(r => `${r.name || ''}\t${r.email || ''}\t${absoluteLink(r.invite_path)}`).join('\n');
}

export function linksAsCsv(rows) {
  const lines = [['name', 'email', 'invite_link', 'expires'].join(',')];
  withLinks(rows).forEach(r => lines.push([
    csvCell(r.name), csvCell(r.email), csvCell(absoluteLink(r.invite_path)), csvCell(r.invite_expires_at),
  ].join(',')));
  return lines.join('\n') + '\n';
}

function InviteLink({ path, expires, emailed }) {
  const [copied, setCopied] = useState(false);
  const url = absoluteLink(path);
  return (
    <div style={{ minWidth: 0, flex: 1 }}>
      <div className="bb-linkrow">
        <input readOnly value={url} onFocus={e => e.target.select()} aria-label="Invite link" className="bb-input" style={{ minHeight: 36, padding: '.35rem .6rem' }} />
        <LinkBtn onClick={async () => { setCopied(await copyText(url)); setTimeout(() => setCopied(false), 1500); }}>{copied ? 'Copied' : 'Copy'}</LinkBtn>
      </div>
      <p className="bb-hint">{emailed ? 'Emailed. ' : ''}Works once{expires ? `, until ${new Date(expires).toLocaleDateString()}` : ''}.</p>
    </div>
  );
}

export function RosterScreen({ onNavigate }) {
  const course = window.BB_ROSTER_COURSE;
  const [rows, setRows] = useState(null);
  const [text, setText] = useState('');
  const [links, setLinks] = useState({});   // student_id -> {invite_path, invite_expires_at, emailed, name, email}
  const [errors, setErrors] = useState([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [mail, setMail] = useState(false);
  const [sendEmail, setSendEmail] = useState(false);
  const [copied, setCopied] = useState(0);   // how many links the last copy put on the clipboard

  async function load() {
    try { setRows(await BB_API.rosterList(course.id)); }
    catch (err) { setError(err.message || 'Could not load the roster.'); setRows([]); }
  }
  useEffect(() => {
    if (!course) { onNavigate('courses'); return; }
    load();
    BB_API.authMe().then(me => { setMail(!!me.mail); setSendEmail(!!me.mail); }).catch(() => {});
  }, []);

  function keepLinks(result) {
    const fresh = {};
    result.forEach(r => { if (r.invite_path) fresh[r.student_id] = r; });
    setLinks(l => ({ ...l, ...fresh }));
    const sent = result.filter(r => r.emailed).length;
    const made = result.filter(r => r.invite_path).length;
    if (made) setNotice(sent ? `${sent} invitation email${sent === 1 ? '' : 's'} sent. Links are also below.` : `${made} invite link${made === 1 ? '' : 's'} ready. Copy them below or download them as a CSV.`);
  }

  async function add(e) {
    e.preventDefault();
    const students = parseRosterInput(text);
    if (!students.length) { setError('Paste at least one email address.'); return; }
    setBusy(true); setError(''); setNotice('');
    try {
      const res = await BB_API.rosterAdd(course.id, students, sendEmail);
      setErrors(res.filter(r => r.error));
      keepLinks(res);
      setText('');
      await load();
    } catch (err) { setError(err.message || 'Could not add students.'); }
    setBusy(false);
  }

  async function reissueAll() {
    if (!confirm('Issue a fresh link to every student who has not set a password yet? Their earlier links stop working.')) return;
    setBusy(true); setError(''); setNotice('');
    try { keepLinks(await BB_API.reissuePending(course.id, sendEmail)); await load(); }
    catch (err) { setError(err.message || 'Could not issue links.'); }
    setBusy(false);
  }

  async function reissue(sid) {
    setError(''); setNotice('');
    try {
      const r = await BB_API.rosterReissue(course.id, sid, sendEmail);
      const row = (rows || []).find(x => x.student_id === sid) || {};
      keepLinks([{ ...row, ...r, student_id: sid }]);
    } catch (err) { setError(err.message || 'Could not issue a new link.'); }
  }

  async function remove(sid, who) {
    if (!confirm(`Remove ${who} from this course? Their account and past work are kept.`)) return;
    try { await BB_API.rosterRemove(course.id, sid); await load(); }
    catch (err) { setError(err.message || 'Could not remove.'); }
  }

  async function erase(sid, who) {
    if (!confirm(`Permanently delete ${who} and all their work? This erases their account, `
      + 'every exam they sat, and their place on every course. It cannot be undone.')) return;
    setError('');
    try { await BB_API.eraseStudent(sid); await load(); }
    catch (err) { setError(err.message || 'Could not delete the student.'); }
  }

  async function deleteCourse() {
    if (!confirm('Delete this course and its roster? Students keep their accounts and past work.')) return;
    try { await BB_API.deleteCourse(course.id); onNavigate('courses'); }
    catch (err) { setError(err.message || 'Could not delete the course.'); }
  }

  async function copyAll() {
    const n = linkRows.filter(r => r.invite_path).length;
    if (await copyText(linksAsText(linkRows))) {
      setCopied(n);
      setNotice(`${n} invite link${n === 1 ? '' : 's'} copied: one line per student with their name, email and link.`);
      setTimeout(() => setCopied(0), 2500);
    } else {
      setNotice('Your browser did not allow copying. Use “Download links (CSV)” instead, or copy each link from the table below.');
    }
  }

  if (!course) return null;
  const linkRows = Object.values(links);
  const invited = (rows || []).filter(r => r.state === 'invited').length;
  const columns = [
    { key: 'name', label: 'Student', lead: true, render: r => <>{r.name || '—'}<span className="sub">{r.email || 'joined by launch link'}</span></> },
    { key: 'state', label: 'Status', render: r => <Badge>{r.state}</Badge> },
    { key: 'link', label: 'Invite link', render: r => links[r.student_id]
      ? <InviteLink path={links[r.student_id].invite_path} expires={links[r.student_id].invite_expires_at} emailed={links[r.student_id].emailed} />
      : (r.email ? <LinkBtn onClick={() => reissue(r.student_id)}>{r.state === 'active' ? 'Password reset link' : 'New invite link'}</LinkBtn> : '—') },
    { key: 'actions', label: 'Actions', actions: true, render: r => {
      const who = r.name || r.email || 'this student';
      return <><LinkBtn muted onClick={() => remove(r.student_id, who)}>Remove</LinkBtn><LinkBtn danger onClick={() => erase(r.student_id, who)}>Delete student</LinkBtn></>;
    } },
  ];

  return (
    <Page eyebrow="Course roster" title={course.name}
      meta={[course.code, rows ? `${rows.length} student${rows.length === 1 ? '' : 's'}` : 'Loading…', invited ? `${invited} waiting to set a password` : null].filter(Boolean).join(' · ')}
      actions={<Btn onClick={() => onNavigate('courses')}>← Courses</Btn>}>
      <ErrorText>{error}</ErrorText>
      <Notice>{notice}</Notice>
      <Panel style={{ marginBottom: '1.5rem' }}>
        <form onSubmit={add}>
          <TextArea id="rosterInput" label="Add students" value={text} onChange={setText} rows={4}
            placeholder={'ada@school.edu\nGrace Hopper, grace@school.edu'}
            hint="One per line, or paste a column from a spreadsheet. Each new student gets a one-time link to set a password." />
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
            <label className="bb-check">
              <input type="checkbox" checked={sendEmail} disabled={!mail} onChange={e => setSendEmail(e.target.checked)} />
              <span>{mail ? 'Email each student their invitation' : 'Email is not set up for this site yet, so copy or download the links instead'}</span>
            </label>
            <Btn primary type="submit" disabled={busy}>{busy ? 'Adding…' : 'Add students'}</Btn>
          </div>
        </form>
        {errors.map(r => <ErrorText key={r.email}>{r.email}: {r.error}</ErrorText>)}
      </Panel>

      {(linkRows.length > 0 || invited > 0) && (
        <Panel className="bb-invite-links" style={{ marginBottom: '1.5rem' }}>
          <h2>Invite links{linkRows.length > 0 ? ` (${linkRows.length})` : ''}</h2>
          {linkRows.length > 0 ? (
            <>
              <p className="bb-meta" style={{ marginBottom: '.8rem' }}>
                Each link works once and lasts 14 days. Links are shown only now, so copy or download them before you leave this page.
                Send each student their own link.
              </p>
              <div className="bb-actions">
                <Btn primary onClick={copyAll}>{copied ? `Copied ${copied} link${copied === 1 ? '' : 's'}` : 'Copy all invite links'}</Btn>
                <Btn onClick={() => downloadText(`${(course.code || course.name || 'course').replace(/[^A-Za-z0-9]+/g, '-')}-invites.csv`, linksAsCsv(linkRows))}>Download links (CSV)</Btn>
                {invited > 0 && <LinkBtn muted onClick={reissueAll} disabled={busy}>Fresh links for all {invited} waiting</LinkBtn>}
              </div>
              <p className="bb-hint" style={{ marginTop: '.6rem' }}>Copying gives one line per student: name, email and link, separated by tabs, so it also pastes into a spreadsheet as three columns.</p>
            </>
          ) : (
            <>
              <p className="bb-meta" style={{ marginBottom: '.8rem' }}>
                {invited} student{invited === 1 ? ' has' : 's have'} not set a password yet. Links are shown only once, when they are made, so
                to copy them all again, get fresh links. Each student’s earlier link then stops working.
              </p>
              <div className="bb-actions">
                <Btn primary onClick={reissueAll} disabled={busy}>{busy ? 'Making links…' : `Get fresh links for all ${invited} waiting`}</Btn>
              </div>
            </>
          )}
        </Panel>
      )}

      <Section title="Students">
        <Table columns={columns} rows={rows || []} rowKey={r => r.student_id} caption="Course roster" empty="No students on this course yet." />
      </Section>
      <div style={{ textAlign: 'right' }}><LinkBtn danger onClick={deleteCourse}>Delete course</LinkBtn></div>
    </Page>
  );
}

// ─── All students in the workspace ───────────────────────────────────────────
export function StudentsScreen({ onNavigate }) {
  const [rows, setRows] = useState(null);
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');
  const load = () => BB_API.listStudents().then(setRows).catch(err => { setError(err.message || 'Could not load students.'); setRows([]); });
  useEffect(() => { load(); }, []);

  async function erase(r) {
    const who = r.name || r.email || 'this student';
    if (!confirm(`Permanently delete ${who} and all their work? This erases their account, every exam they sat, and their place on every course. It cannot be undone.`)) return;
    try { await BB_API.eraseStudent(r.student_id); await load(); }
    catch (err) { setError(err.message || 'Could not delete the student.'); }
  }

  const q = query.trim().toLowerCase();
  const shown = (rows || []).filter(r => !q || `${r.name} ${r.email}`.toLowerCase().includes(q));
  const columns = [
    { key: 'name', label: 'Student', lead: true, render: r => <>{r.name || '—'}<span className="sub">{r.email || 'joined by launch link'}</span></> },
    { key: 'courses', label: 'Courses', render: r => (r.courses || []).map(c => (
      <LinkBtn key={c.course_id} onClick={() => openRoster({ id: c.course_id, name: c.name, code: c.code }, onNavigate)} style={{ padding: '0 .4rem 0 0' }}>{c.code || c.name}</LinkBtn>
    )) },
    { key: 'state', label: 'Status', render: r => <Badge>{r.state}</Badge> },
    { key: 'submissions', label: 'Submitted', num: true },
    { key: 'last', label: 'Last submission', render: r => when(r.last_submitted_at) },
    { key: 'actions', label: 'Actions', actions: true, render: r => <LinkBtn danger onClick={() => erase(r)}>Delete student</LinkBtn> },
  ];
  return (
    <Page eyebrow="Your workspace" title="Students"
      meta={rows === null ? 'Loading…' : `${rows.length} student${rows.length === 1 ? '' : 's'} across your courses`}
      actions={<Btn onClick={() => onNavigate('courses')}>Add students via a course</Btn>}>
      <ErrorText>{error}</ErrorText>
      <div style={{ maxWidth: 420 }}>
        <Field id="studentSearch" label="Search by name or email" value={query} onChange={setQuery} required={false} type="search" />
      </div>
      <Table columns={columns} rows={shown} rowKey={r => r.student_id} caption="Students"
        empty={q ? 'Nobody matches that search.' : 'No students yet. Add them to a course to invite them.'} />
    </Page>
  );
}

// ─── Proctor: live view of one exam ──────────────────────────────────────────
const LIVE_STATUS = { not_started: 'not started', writing: 'writing', submitted: 'submitted', time_up: 'time up' };

// Which open exam the live view opens on when none was chosen: the one with
// the most students writing now, then the one with the most still to start
// (the next sitting, during a break), then the first one the teacher set.
// `candidates` are [{ id, counts }] in the server's order (newest first).
export function chooseLiveExam(candidates) {
  const list = (candidates || []).map((c, i) => ({ ...c, i }));
  if (!list.length) return '';
  const n = (c, k) => Number((c.counts || {})[k]) || 0;
  list.sort((a, b) => (n(b, 'writing') - n(a, 'writing')) || (n(b, 'not_started') - n(a, 'not_started')) || (b.i - a.i));
  return list[0].id;
}

export function ProctorLiveScreen() {
  const [exams, setExams] = useState(null);
  const [examId, setExamId] = useState(window.BB_PROCTOR_EXAM || '');
  const [live, setLive] = useState(null);
  const [tab, setTab] = useState('live');
  const [error, setError] = useState('');

  // "Watch live" and a #live/<id> link name the exam once; the next visit
  // from the navigation chooses afresh (the exam being written now).
  useEffect(() => { window.BB_PROCTOR_EXAM = ''; }, []);
  const [tick, setTick] = useState(0);   // "Refresh now"
  // The tab, read by the exam choice below after its requests come back.
  const tabRef = useRef(tab);
  tabRef.current = tab;

  useEffect(() => {
    BB_API._json('GET', '/bluebook/exams').then(async d => {
      // Drafts are left out, except the exam this screen was opened for (a
      // deep link, deep-link.jsx), so the picker never shows another title.
      const list = (d.exams || []).filter(e => examState(e) !== 'draft' || e.id === examId);
      setExams(list);
      if (examId || !list.length) return;
      const open = list.filter(e => examState(e) === 'open').slice(0, 6);
      // At once, so the screen never waits on an exam: the first open one the
      // teacher set (or the newest exam when none is open).
      const first = open.length ? chooseLiveExam(open.map(e => ({ id: e.id }))) : list[0].id;
      setExamId(first);
      if (open.length < 2) return;
      // Several are open: look at each and move to the one being written, but
      // only if the teacher has not chosen an exam or opened the phone park
      // meanwhile (the park is kept per exam, so moving would close it).
      const counts = await Promise.all(open.map(e => BB_API.examLive(e.id).then(l => l.counts).catch(() => null)));
      const best = chooseLiveExam(open.map((e, i) => ({ id: e.id, counts: counts[i] })));
      setExamId(id => (id === first && tabRef.current === 'live' ? best : id));
    }).catch(err => { setError(err.message || 'Could not load examinations.'); setExams([]); });
  }, []);

  useEffect(() => {
    if (!examId) return undefined;
    let alive = true;
    const poll = () => BB_API.examLive(examId)
      .then(d => { if (alive) { setLive(d); setError(''); } })
      .catch(err => { if (alive) setError(err.message || 'Could not load the live view.'); });
    poll();
    const id = setInterval(poll, 15000);
    return () => { alive = false; clearInterval(id); };
  }, [examId, tick]);

  const counts = (live && live.counts) || {};
  const columns = [
    { key: 'name', label: 'Student', lead: true, render: r => <>{r.name || '—'}<span className="sub">{r.email || ''}</span></> },
    { key: 'status', label: 'Status', render: r => <Badge>{LIVE_STATUS[r.status] || r.status}</Badge> },
    { key: 'started', label: 'Started', render: r => r.started_at ? new Date(r.started_at).toLocaleTimeString() : '—' },
    { key: 'left', label: 'Minutes left', num: true, render: r => r.status === 'writing' ? r.minutes_left : '—' },
    { key: 'submitted', label: 'Submitted', render: r => r.submitted_at ? <>{new Date(r.submitted_at).toLocaleTimeString()}{r.late ? <> <Badge tone="bad">late</Badge></> : null}</> : '—' },
    { key: 'warnings', label: 'Warnings', num: true, render: r => r.status === 'submitted' ? r.warnings : '—' },
  ];
  if (tab === 'phones') window.BB_EXAM_CONFIG = { ...(window.BB_EXAM_CONFIG || {}), id: examId };
  return (
    <Page eyebrow="Proctor" title="Live examination"
      meta={live ? `Updated ${new Date(live.now).toLocaleTimeString()} · refreshes every 15 seconds` : (examId ? 'Loading the live view…' : 'Choose an examination to watch.')}
      actions={examId && <Btn onClick={() => setTick(t => t + 1)}>Refresh now</Btn>}>
      <ErrorText>{error}</ErrorText>
      <div className="bb-grid cols-2" style={{ alignItems: 'end' }}>
        <Select id="proctorExam" label="Examination" value={examId} onChange={v => { setLive(null); setExamId(v); }}>
          {!examId && <option value="">Choose…</option>}
          {(exams || []).map(e => <option key={e.id} value={e.id}>{e.title} ({examState(e)})</option>)}
        </Select>
        <div className="bb-actions" role="tablist" aria-label="Proctor views" style={{ marginBottom: '1rem' }}>
          <Btn primary={tab === 'live'} role="tab" aria-selected={tab === 'live'} onClick={() => setTab('live')}>Students</Btn>
          <Btn primary={tab === 'phones'} role="tab" aria-selected={tab === 'phones'} onClick={() => setTab('phones')}>Phone park</Btn>
        </div>
      </div>
      {tab === 'live' ? (
        <>
          <div className="bb-grid cols-4" style={{ marginBottom: '1.5rem' }}>
            <Stat value={counts.enrolled ?? '—'} label="On the roster" />
            <Stat value={counts.writing ?? '—'} label="Writing now" />
            <Stat value={counts.submitted ?? '—'} label="Submitted" note={counts.late ? `${counts.late} late` : undefined} />
            <Stat value={counts.not_started ?? '—'} label="Not started" />
          </div>
          <Table columns={columns} rows={(live && live.students) || []} rowKey={r => r.student_id} caption="Live sitting"
            empty={examId ? 'Nobody on the roster for this exam yet.' : 'Choose an examination above.'} />
          <p className="bb-hint">Warnings arrive when a student seals their exam, so they show for submitted students only.</p>
        </>
      ) : (
        <div key={examId} style={{ marginTop: '1rem' }}><ProctorScreen /></div>
      )}
    </Page>
  );
}

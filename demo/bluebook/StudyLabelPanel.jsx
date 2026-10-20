import React from 'react';
import { BB_API } from './components.jsx';
import { Btn, ErrorText, LinkBtn, Notice, Panel, Select } from './forms.jsx';

// ════════════════════════════════════════════════════════════════
//  Study label panel (research, staff only)
//  For the natural/shadow writing study (docs/research/STUDY_PROTOCOL_2026-10.md):
//  staff record whether each submission of this exam was written
//  "natural" (the student as themselves) or "shadow" (the student
//  imitating a named classmate). It reads nothing from Original and
//  shows no score. Labels go to
//    POST /bluebook/submissions/{id}/study-label
//    { study_label: "natural" | "shadow", imitated_student_id: string | null }
//  (imitated_student_id is null on a natural label). A server without the
//  route is said plainly and nothing is reported as saved; a 422 shows the
//  server's own reason.
//  The panel exists only for staff, and only on an exam that runs Original
//  (the same rule the server scores study submissions by): otherwise it is
//  not rendered at all.
// ════════════════════════════════════════════════════════════════
const { useEffect, useState } = React;

export const STUDY_PANEL_TITLE = 'Study label (research, staff only)';
export const STUDY_LABELS = ['natural', 'shadow'];
export const STUDY_ROUTE_MISSING =
  'Study labels cannot be saved on this server yet: it does not have the study-label route '
  + '(POST /bluebook/submissions/{id}/study-label). Nothing was saved.';

// Whether this exam runs Original: its stored conditions switch the
// authorship comparison on (NewExam.jsx "Authorship comparison (Original)").
// Strictly true, as the server checks it before scoring a study submission
// (original/study_scoring.py style_scoring_enabled): an exam saved without
// the condition is not an Original exam, whatever the sitting defaults to.
export function examHasOriginal(exam) {
  const c = exam && exam.conditions;
  return !!c && typeof c === 'object' && c.aiDetect === true;
}

// Who may see the panel: a signed-in staff member (a principal token, never a
// student session) in a workspace that holds Original, on an exam that runs
// Original, since the study measures Original's readings of that exam.
export function studyPanelVisible(exam, api = BB_API) {
  return api.isAuthed() && !api.isStudentAccount() && !api.isStudentLaunch()
    && api.hasOriginal() && examHasOriginal(exam);
}

// The classmates a shadow submission may imitate, once each, by name:
// everyone else who sat this exam, then the rest of the course roster. The
// roster matters because the study's shadow sitting is its own exam: a target
// who missed it never submitted to it, yet their imitator must name them.
// Two classmates with one name are told apart by email (or id), since a
// wrong pick silently mislabels the study row.
export function imitationChoices(subs, writerId, roster) {
  const seen = new Map();
  const email = new Map();
  (roster || []).forEach(r => { if (r && r.student_id && r.email) email.set(r.student_id, r.email); });
  (subs || []).forEach(s => {
    const id = s && s.student_id;
    if (id && id !== writerId && !seen.has(id)) seen.set(id, s.student || id);
  });
  (roster || []).forEach(r => {
    const id = r && r.student_id;
    if (id && id !== writerId && !seen.has(id)) seen.set(id, r.name || r.email || id);
  });
  const uses = new Map();
  seen.forEach(name => uses.set(name, (uses.get(name) || 0) + 1));
  return [...seen].map(([id, name]) => ({
    id, name: uses.get(name) > 1 ? `${name} (${email.get(id) || id})` : name,
  })).sort((a, b) => a.name.localeCompare(b.name) || a.id.localeCompare(b.id));
}

// Why a label cannot be saved as chosen, or '' when it can.
export function studyLabelProblem(sub, label, imitatedId) {
  if (!STUDY_LABELS.includes(label)) return 'Choose natural or shadow.';
  if (label === 'shadow') {
    if (!imitatedId) return 'Choose the classmate this shadow submission imitates.';
    if (sub && imitatedId === sub.student_id) return 'A shadow submission imitates someone else.';
  }
  return '';
}

export function studyLabelBody(label, imitatedId) {
  return { study_label: label, imitated_student_id: label === 'shadow' ? imitatedId : null };
}

// The server's reason, as text. A route's own refusal is a string; FastAPI's
// request validation (422) is a list of {loc, msg}, each named by its field.
export function detailText(detail) {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map(d => {
      if (typeof d === 'string') return d;
      if (!d || typeof d.msg !== 'string') return '';
      const loc = Array.isArray(d.loc) ? d.loc.filter(x => x !== 'body').join('.') : '';
      return loc ? `${loc}: ${d.msg}` : d.msg;
    }).filter(Boolean).join('; ');
  }
  if (detail && typeof detail.msg === 'string') return detail.msg;
  return '';
}

// FastAPI answers an unknown path with 404 {"detail": "Not Found"}; the
// Bluebook routes answer a missing submission with their own detail. Only the
// first means the route is not there.
export function isRouteMissing(status, detail) {
  if (status === 405 || status === 501) return true;
  return status === 404 && (!detail || detail === 'Not Found');
}

// → { ok: true } | { ok: false, missing: true, message } | { ok: false, message }
export async function saveStudyLabel(submissionId, label, imitatedId, api = BB_API) {
  let r;
  try {
    r = await fetch(`${api.base}/bluebook/submissions/${encodeURIComponent(submissionId)}/study-label`, {
      method: 'POST', headers: api._headers(), body: JSON.stringify(studyLabelBody(label, imitatedId)),
    });
  } catch (e) {
    return { ok: false, message: 'Could not reach the server. Nothing was saved.' };
  }
  if (r.ok) return { ok: true };
  let detail = '';
  try { detail = detailText((await r.json()).detail); } catch (e) {}
  if (isRouteMissing(r.status, detail)) return { ok: false, missing: true, message: STUDY_ROUTE_MISSING };
  if (r.status === 401) return { ok: false, message: 'Please sign out and sign in again.' };
  if (r.status === 403) return { ok: false, message: 'Only staff can record study labels.' };
  if (r.status === 422) {
    return { ok: false, message: detail ? `Not saved: ${detail}` : 'Not saved: the server refused this label (HTTP 422).' };
  }
  return { ok: false, message: detail || `Could not save the label (HTTP ${r.status}).` };
}

// The label a row starts from: one saved during this visit, else what the
// server sent with the submission, else none.
export function initialStudyLabel(sub, known) {
  if (known) return { label: known.label, imitated: known.imitated || '' };
  return { label: (sub && sub.study_label) || '', imitated: (sub && sub.imitated_student_id) || '' };
}

function StudyLabelRow({ sub, subs, roster, known, onSaved, onRouteMissing }) {
  const start = initialStudyLabel(sub, known);
  const [label, setLabel] = useState(start.label);
  const [imitated, setImitated] = useState(start.imitated);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState('');
  const [error, setError] = useState('');
  const choices = imitationChoices(subs, sub.student_id, roster);
  const problem = studyLabelProblem(sub, label, imitated);

  async function save() {
    setBusy(true); setSaved(''); setError('');
    const res = await saveStudyLabel(sub.id, label, imitated);
    setBusy(false);
    if (res.ok) { onSaved({ label, imitated: label === 'shadow' ? imitated : '' }); setSaved(`Saved: ${label}${label === 'shadow' ? `, imitating ${(choices.find(c => c.id === imitated) || {}).name || imitated}` : ''}.`); return; }
    if (res.missing) onRouteMissing();
    else setError(res.message);
  }

  return (
    <div className="bb-card" style={{ marginTop: '.8rem' }}>
      <p style={{ margin: 0 }}><strong>{sub.student || 'Candidate'}</strong> <span className="bb-hint">{(sub.words || 0).toLocaleString()} words</span></p>
      <div className="bb-grid cols-2">
        <Select id={`study-label-${sub.id}`} label="Written as" value={label} onChange={v => { setLabel(v); setSaved(''); setError(''); }}>
          <option value="">Not labelled</option>
          <option value="natural">Natural (as themselves)</option>
          <option value="shadow">Shadow (imitating a classmate)</option>
        </Select>
        {label === 'shadow' && (
          <Select id={`study-imitated-${sub.id}`} label="Imitating" value={imitated} onChange={v => { setImitated(v); setSaved(''); setError(''); }}>
            <option value="">Choose a classmate</option>
            {choices.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </Select>
        )}
      </div>
      {label && problem && <p className="bb-hint">{problem}</p>}
      <div style={{ marginTop: '.6rem' }}>
        <Btn onClick={save} disabled={busy || !!problem}>{busy ? 'Saving…' : 'Save label'}</Btn>
      </div>
      <Notice>{saved}</Notice>
      <ErrorText>{error}</ErrorText>
    </div>
  );
}

// `api` is for tests; the app always uses BB_API.
export function StudyLabelPanel({ exam, subs, api = BB_API }) {
  const [open, setOpen] = useState(false);
  const [routeMissing, setRouteMissing] = useState(false);
  // Labels saved during this visit. Rows unmount on Hide, and the submissions
  // list is not reloaded after a save, so without this a saved label would read
  // "Not labelled" on Show, where a second staff member checks the labels
  // (docs/research/STUDY_PROTOCOL_2026-10.md, step 7).
  const [savedLabels, setSavedLabels] = useState({});
  // The course roster, fetched the first time the panel opens. Without it
  // (no course, or the call fails) the picker offers this exam's submitters.
  const [roster, setRoster] = useState(null);
  const visible = studyPanelVisible(exam, api);
  const courseId = exam && exam.course_id;
  useEffect(() => {
    if (!open || roster !== null) return undefined;
    if (!visible || !courseId) { setRoster([]); return undefined; }
    let live = true;
    api.rosterList(courseId)
      .then(r => { if (live) setRoster(r || []); })
      .catch(() => { if (live) setRoster([]); });
    return () => { live = false; };
  }, [open, visible, courseId]);
  if (!visible) return null;
  const list = subs || [];
  return (
    <Panel style={{ marginTop: '1.5rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: '1rem', flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0 }}>{STUDY_PANEL_TITLE}</h2>
        <LinkBtn onClick={() => setOpen(!open)} aria-expanded={open} aria-label={open ? 'Hide study labels' : 'Show study labels'}>
          {open ? 'Hide' : 'Show'}
        </LinkBtn>
      </div>
      <p className="bb-hint">
        Only for the natural/shadow writing study. Record how each submission was written: natural
        (the student as themselves) or shadow (imitating a named classmate, on request). Students do not
        see this panel, and it shows no score.
      </p>
      {open && (
        <>
          {routeMissing && <p role="alert" className="bb-error">{STUDY_ROUTE_MISSING}</p>}
          {/* The exam view passes null until its submissions list loads (or
              when that load failed): not the same as nobody having submitted. */}
          {subs == null
            ? <p className="bb-hint">The submissions have not loaded, so there is nothing to label yet.</p>
            : list.length === 0
            ? <p className="bb-hint">Nobody has submitted yet.</p>
            : list.map(s => (
              <StudyLabelRow key={s.id} sub={s} subs={list} roster={roster || []} known={savedLabels[s.id]}
                onSaved={v => setSavedLabels(m => ({ ...m, [s.id]: v }))}
                onRouteMissing={() => setRouteMissing(true)} />
            ))}
        </>
      )}
    </Panel>
  );
}

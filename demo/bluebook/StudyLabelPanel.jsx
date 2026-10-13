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
//  which the backend may not have yet; a missing route is said plainly
//  and nothing is reported as saved.
// ════════════════════════════════════════════════════════════════
const { useState } = React;

export const STUDY_PANEL_TITLE = 'Study label (research, staff only)';
export const STUDY_LABELS = ['natural', 'shadow'];
export const STUDY_ROUTE_MISSING =
  'Study labels cannot be saved on this server yet: it does not have the study-label route '
  + '(POST /bluebook/submissions/{id}/study-label). Nothing was saved.';

// Who may see the panel: a signed-in staff member (a principal token, never a
// student session) in a workspace that holds Original, since the study
// measures Original's readings.
export function studyPanelVisible(api = BB_API) {
  return api.isAuthed() && !api.isStudentAccount() && !api.isStudentLaunch() && api.hasOriginal();
}

// The classmates a shadow submission may imitate: everyone else who sat this
// exam, once each, by name.
export function imitationChoices(subs, writerId) {
  const seen = new Map();
  (subs || []).forEach(s => {
    const id = s && s.student_id;
    if (id && id !== writerId && !seen.has(id)) seen.set(id, s.student || id);
  });
  return [...seen].map(([id, name]) => ({ id, name }))
    .sort((a, b) => a.name.localeCompare(b.name) || a.id.localeCompare(b.id));
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
  try { detail = (await r.json()).detail || ''; } catch (e) {}
  if (typeof detail !== 'string') detail = '';
  if (isRouteMissing(r.status, detail)) return { ok: false, missing: true, message: STUDY_ROUTE_MISSING };
  if (r.status === 401) return { ok: false, message: 'Please sign out and sign in again.' };
  if (r.status === 403) return { ok: false, message: 'Only staff can record study labels.' };
  return { ok: false, message: detail || `Could not save the label (HTTP ${r.status}).` };
}

function StudyLabelRow({ sub, subs, onRouteMissing }) {
  const [label, setLabel] = useState(sub.study_label || '');
  const [imitated, setImitated] = useState(sub.imitated_student_id || '');
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState('');
  const [error, setError] = useState('');
  const choices = imitationChoices(subs, sub.student_id);
  const problem = studyLabelProblem(sub, label, imitated);

  async function save() {
    setBusy(true); setSaved(''); setError('');
    const res = await saveStudyLabel(sub.id, label, imitated);
    setBusy(false);
    if (res.ok) { setSaved(`Saved: ${label}${label === 'shadow' ? `, imitating ${(choices.find(c => c.id === imitated) || {}).name || imitated}` : ''}.`); return; }
    if (res.missing) onRouteMissing();
    else setError(res.message);
  }

  return (
    <div className="bb-card" style={{ marginTop: '.8rem' }}>
      <p style={{ margin: 0 }}><strong>{sub.student || 'Candidate'}</strong> <span className="bb-hint">{(sub.words || 0).toLocaleString()} words</span></p>
      <div className="bb-grid cols-2">
        <Select id={`study-label-${sub.id}`} label="Written as" value={label} onChange={v => { setLabel(v); setSaved(''); }}>
          <option value="">Not labelled</option>
          <option value="natural">Natural (as themselves)</option>
          <option value="shadow">Shadow (imitating a classmate)</option>
        </Select>
        {label === 'shadow' && (
          <Select id={`study-imitated-${sub.id}`} label="Imitating" value={imitated} onChange={v => { setImitated(v); setSaved(''); }}>
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

export function StudyLabelPanel({ subs }) {
  const [open, setOpen] = useState(false);
  const [routeMissing, setRouteMissing] = useState(false);
  if (!studyPanelVisible()) return null;
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
          {list.length === 0
            ? <p className="bb-hint">Nobody has submitted yet.</p>
            : list.map(s => <StudyLabelRow key={s.id} sub={s} subs={list} onRouteMissing={() => setRouteMissing(true)} />)}
        </>
      )}
    </Panel>
  );
}

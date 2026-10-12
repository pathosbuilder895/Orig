import React from 'react';
import { BB_API } from './components.jsx';
import { Btn, ErrorText, Notice, Panel, Section } from './forms.jsx';

// ════════════════════════════════════════════════════════════════
//  COLLECTIONS — Student consent (university beta MVP)
//  Shown before the student home when GET /bluebook/me reports
//  consent_blocked. The server enforces it too (403 consent_required);
//  this screen only collects the answers. Texts come from the server
//  and are DRAFT — pending counsel review.
// ════════════════════════════════════════════════════════════════

const { useState, useEffect } = React;

export function ConsentPanel({ blocked, onDone }) {
  const [view, setView] = useState(null);
  const [name, setName] = useState('');
  const [over18, setOver18] = useState(false);
  const [classUse, setClassUse] = useState(false);
  const [consistency, setConsistency] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    BB_API._json('GET', '/bluebook/me/consent').then(setView)
      .catch(err => setError(err.message || 'Could not load the consent screen.'));
  }, []);

  if (blocked === 'age_blocked') {
    return <Notice>Collections is for students 18 or older. Please talk to your instructor.</Notice>;
  }
  if (blocked === 'alternative_assignment') {
    return (
      <Panel>
        <p>You chose not to use Collections for this course. Your instructor will arrange an alternative assignment, with no penalty.</p>
        <Btn onClick={() => { setClassUse(true); onDone && onDone('reopen'); }}>Change my answer</Btn>
      </Panel>
    );
  }
  if (!view) return <ErrorText>{error}</ErrorText>;
  const docs = Object.fromEntries((view.documents || []).map(d => [d.scope, d]));

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setError('');
    try {
      await BB_API._json('POST', '/bluebook/me/consent', {
        typed_name: name, over_18: over18, class_use: classUse, consistency,
      });
      onDone && onDone();
    } catch (err) { setError(err.message || 'Could not save your answers.'); }
    setBusy(false);
  }

  const doc = (scope, checked, set, label) => docs[scope] && (
    <Panel style={{ marginBottom: '1rem' }}>
      <h2>{docs[scope].title}</h2>
      <p style={{ whiteSpace: 'pre-wrap' }}>{docs[scope].body}</p>
      <label><input type="checkbox" checked={checked} onChange={e => set(e.target.checked)} /> {label}</label>
    </Panel>
  );

  return (
    <Section title="Before you start">
      <form onSubmit={submit}>
        {doc('age', over18, setOver18, 'I am 18 or older.')}
        {doc('class_use', classUse, setClassUse, 'I agree to use Collections for this course.')}
        {doc('consistency', consistency, setConsistency, 'Optional: turn on the writing-consistency feature (in testing).')}
        <label>Type your full name as your signature
          <input value={name} onChange={e => setName(e.target.value)} required maxLength={200} />
        </label>
        <ErrorText>{error}</ErrorText>
        <Btn primary type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save my answers'}</Btn>
      </form>
    </Section>
  );
}

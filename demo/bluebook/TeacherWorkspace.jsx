import React, { useEffect, useRef, useState } from 'react';
import { BB_API } from './components.jsx';
import { Badge, LinkBtn, Section, Stat, Table, when } from './forms.jsx';
import './teacher-workspace.css';

const dateLabel = value => value ? new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : '';

export function TeacherFrame({ demo = false, active = 'sessions', onNavigate, children }) {
  const identity = demo ? {name: 'Professor · demonstration'} : BB_API.identity();
  const initials = (identity.name || 'Teacher').split(/\s+/).slice(0, 2).map(n => n[0]).join('');
  const items = demo
    ? [['Overview','overview'],['Students','students'],['Submissions','submissions'],['Bluebook','sessions'],['Reports','reports']]
    : [['Overview','dashboard'],['Bluebook','sessions'],['Examinations','exams'],['Courses','courses'],['Students','students'],['Submissions','results'],['Proctor','proctor']];
  return <div className="teacher-ui"><div className="teacher-frame">
    <nav className="teacher-nav" aria-label="Teacher navigation">
      <div className="teacher-brand"><span aria-hidden="true">◆</span> {demo || BB_API.hasOriginal() ? 'Original' : 'Bluebook'}</div>
      <div className="teacher-pills">{items.map(([label,key]) => <button key={key} className={active===key?'on':''} aria-current={active===key?'page':undefined} onClick={()=>onNavigate(key)}>{label}</button>)}{!demo && BB_API.hasOriginal() && <button onClick={()=>{window.location.href='../professor.html';}}>Original Analysis ↗</button>}</div>
      <span className="teacher-avatar" title={identity.name} aria-label={identity.name}>{demo?'P':initials}</span>
    </nav>
    <div className={'teacher-mode '+(demo?'is-demo':'')}>
      <span>{demo ? 'DEMONSTRATION · FICTIONAL RECORDS · NO DATA IS SAVED' : (BB_API.hasOriginal() ? 'YOUR WORKSPACE · CONNECTED TO ORIGINAL' : 'YOUR BLUEBOOK WORKSPACE')}</span>
      {demo ? <button onClick={()=>onNavigate('reset')}>Reset demo</button> : <div>
        <button onClick={()=>onNavigate('account')}>Account</button>
        <button onClick={()=>{BB_API.logout();onNavigate('landing');}}>Sign out</button>
      </div>}
    </div>
    <main className="teacher-body">{children}</main>
  </div></div>;
}

export function SessionSetup({ courses, exams, loading, error, onRetry, onCreate, onOpen, onCourses, demo=false, hasOriginal=false }) {
  const [questions,setQuestions]=useState(['']);
  const [courseId,setCourseId]=useState('');
  const [duration,setDuration]=useState(50);
  const [busy,setBusy]=useState(false);
  const [saveError,setSaveError]=useState('');
  const saving=useRef(false);
  const selected=courses.find(c=>c.id===courseId)||courses[0];
  async function submit(event) {
    event.preventDefault();
    if(saving.current) return;
    if(!selected || questions.some(q=>!q.trim())) {setSaveError('Choose a class and write each question before opening the booklets.');return;}
    const list=questions.map(q=>q.trim());
    if(list.some(q=>q.length>8000)){setSaveError('Keep each question under 8,000 characters.');return;}
    saving.current=true;setBusy(true);setSaveError('');
    try {
      await onCreate({title:`${selected.code||selected.name||'Class'} · ${new Date().toLocaleDateString()}`,course:selected.code||selected.name,course_id:selected.id,duration,questions:list,status:'ACTIVE',minWords:0,maxWords:0,conditions:{}});
      setQuestions(['']);
    } catch(err) {setSaveError(err.message||'The session could not be saved. Your questions are still here.');}
    finally {saving.current=false;setBusy(false);}
  }
  return <>
    <header className="teacher-head"><div className="eyebrow">Bluebook sessions</div><h1>In-class writing, in their own hand.</h1><p>A quiet space for supervised writing. {hasOriginal ? 'Finished booklets can be reviewed for inclusion in each student’s writing baseline.' : 'Set a question, give your class time to think, and read their work in one place.'}</p></header>
    {error && <div role="alert" className="teacher-error">{error} <button onClick={onRetry}>Try again</button></div>}
    <div className="teacher-columns">
      <form className="teacher-card teacher-setup" onSubmit={submit}>
        <div className="setup-heading"><span className="book-mark" aria-hidden="true"/><div><h2>Start a new session</h2><p>Three questions. That’s the whole setup.</p></div></div>
        <div className="teacher-steps">
          <section className="teacher-step"><h3>What should they write about?</h3>
            {questions.map((q,i)=><div key={i} className="question-field"><label htmlFor={`teacher-question-${i}`}>Question {i+1}</label><textarea id={`teacher-question-${i}`} required maxLength={8000} disabled={busy} value={q} placeholder="e.g. Explain the difference between Luther’s and Calvin’s views of the Lord’s Supper — and which you find more persuasive, and why." onChange={e=>setQuestions(questions.map((v,j)=>j===i?e.target.value:v))}/>{i>0&&<button type="button" className="quiet-button" disabled={busy} onClick={()=>setQuestions(questions.filter((_,j)=>j!==i))}>Remove question {i+1}</button>}</div>)}
            <button type="button" className="add-question" disabled={busy||questions.length>=8} onClick={()=>setQuestions([...questions,''])}>+ Add {questions.length===1?'a second':'another'} question</button>
            <p className="hint">Write it the way you’d say it aloud. Students see exactly these words.</p>
          </section>
          <section className="teacher-step"><h3>Which class?</h3><div className="class-choices" aria-label="Choose a class">
            {loading?<p role="status">Loading your classes…</p>:courses.map(c=><button type="button" key={c.id} disabled={busy} aria-pressed={selected?.id===c.id} onClick={()=>setCourseId(c.id)}>{c.code||c.name} · {c.students??0} students</button>)}
          </div>{!loading&&!courses.length&&!error&&<p>No classes yet. <button type="button" className="quiet-button" onClick={onCourses}>Create your first course</button></p>}</section>
          <section className="teacher-step"><h3><label htmlFor="teacher-duration">How long do they get?</label></h3><div className="time-row"><input id="teacher-duration" aria-label="Session duration in minutes" type="range" min="15" max="120" step="5" value={duration} disabled={busy} onChange={e=>setDuration(Number(e.target.value))}/><output htmlFor="teacher-duration">{duration} min</output></div>
            <div className="quiet-note"><span aria-hidden="true">◇</span><p><strong>Space to concentrate.</strong> Drafts save on the student’s device while they write. Submission is confirmed once their work reaches the server. Only text and coarse session information are used; no keystroke biometrics, screen recording or camera capture.</p></div>
          </section>
        </div>
        {saveError&&<p className="teacher-error" role="alert">{saveError}</p>}
        <div className="launch-row"><button className="teacher-primary" disabled={busy||loading||!!error||!courses.length} type="submit">{busy?'Opening…':'▷ Open the booklets'}</button><span>{selected?.code||selected?.name||'Choose a class'} · {questions.length} question{questions.length>1?'s':''} · {duration} minutes</span></div>
      </form>
      <aside><section className="teacher-card session-history"><div className="section-title"><h2>Sessions</h2><span>{demo?'example term':'your workspace'}</span></div>
        {loading?<p role="status">Loading sessions…</p>:!exams.length?<p>No sessions yet. Your first one will appear here.</p>:exams.map(e=><button className="session-row" key={e.id} onClick={()=>onOpen(e)}><span className="small-book" aria-hidden="true"/><span className="session-title"><strong>{e.title}</strong><small>{e.course} {dateLabel(e.created_at)&&`· ${dateLabel(e.created_at)}`} · {e.duration} min</small></span><span className="session-badge"><span>{String(e.status||'DRAFT').toLowerCase()}</span><small>{e.submissions??0} submitted</small></span></button>)}
      </section><section className="teacher-card teacher-why"><h2>Why Bluebook matters</h2><p>Start with the writing itself. Give students a clear prompt, a dependable place to write, and a thoughtful reader. {hasOriginal&&'With Original, approved samples can support a report-only comparison with later work. Differences invite context, not accusations.'}</p></section></aside>
    </div>
  </>;
}

export function LiveTeacherSessions({onNavigate,overview=false}) {
  const [data,setData]=useState({courses:[],exams:[]});
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  const [retry,setRetry]=useState(0);
  const [created,setCreated]=useState(null);
  useEffect(()=>{
    let live=true;setLoading(true);setError('');
    // Strict reads: a failed request must never become an empty workspace or demo fixture.
    Promise.all([BB_API._json('GET','/bluebook/courses'),BB_API._json('GET','/bluebook/exams')])
      .then(([c,e])=>{if(live)setData({courses:c.courses||[],exams:e.exams||[]});})
      .catch(err=>{if(live)setError(err.message||'Could not load your workspace.');})
      .finally(()=>{if(live)setLoading(false);});
    return()=>{live=false;};
  },[retry]);
  const open=exam=>{window.BB_MANAGE_EXAM=exam.id;onNavigate('manage-exam');};
  if(overview) return <TeacherOverview onNavigate={onNavigate} courses={data.courses} exams={data.exams} loading={loading} error={error} onRetry={()=>setRetry(v=>v+1)}/>;
  return <>
    {created&&<div className="teacher-receipt" role="status"><strong>Your session is open.</strong> Rostered students can find it in My exams. <button onClick={()=>open(created)}>Manage session and read submissions →</button></div>}
    <SessionSetup {...data} loading={loading} error={error} onRetry={()=>setRetry(v=>v+1)} onCourses={()=>onNavigate('courses')} hasOriginal={BB_API.hasOriginal()} onOpen={open} onCreate={async payload=>{const e=await BB_API.createExam(payload);setData(d=>({...d,exams:[e,...d.exams]}));setCreated(e);}}/>
  </>;
}


// ─── Overview: what needs the teacher's attention ───────────────────────────
const stateOf = e => {
  const st = String(e.status || 'DRAFT').toUpperCase();
  if (st === 'DRAFT') return 'draft';
  if (st === 'CLOSED' || st === 'ARCHIVED') return 'closed';
  if (e.opens_at && Date.now() < Date.parse(e.opens_at)) return 'upcoming';
  if (e.closes_at && Date.now() >= Date.parse(e.closes_at)) return 'closed';
  return 'open';
};

export function TeacherOverview({ onNavigate, courses, exams, loading, error, onRetry }) {
  const [subs, setSubs] = useState(null);
  const [students, setStudents] = useState(null);
  const [detailError, setDetailError] = useState('');
  const loadDetails = () => {
    setDetailError('');
    return Promise.all([BB_API.listSubmissions(), BB_API.listStudents()])
      .then(([records, people]) => { setSubs(records); setStudents(people); })
      .catch(err => setDetailError(err.message || 'Could not load workspace records.'));
  };
  useEffect(() => { loadDetails(); }, []);
  const open = exams.filter(e => stateOf(e) === 'open');
  const unmarked = (subs || []).filter(s => !s.mark && !s.feedback);
  const unreleased = exams.filter(e => !e.results_released_at && (Number(e.submissions) || 0) > 0);
  const invited = (students || []).filter(s => s.state === 'invited').length;
  const manage = id => { window.BB_MANAGE_EXAM = id; onNavigate('manage-exam'); };
  const name = (BB_API.identity().name || '').trim();
  return <div className="bb-page">
    <header className="teacher-head"><div className="eyebrow">Your teaching workspace</div><h1>{name ? `Welcome back, ${name}.` : 'Begin with the writing.'}</h1><p>Set a session, invite your class, and give their words a thoughtful reading.</p></header>
    {error && <div role="alert" className="teacher-error">{error} <button onClick={onRetry}>Try again</button></div>}
    {detailError && !error && <div role="alert" className="teacher-error">{detailError} <button onClick={loadDetails}>Try again</button></div>}
    {loading ? <p role="status">Loading your workspace…</p> : !error && !detailError && <>
      <div className="bb-grid cols-4" style={{ marginBottom: '1.5rem' }}>
        <Stat value={open.length} label="Open now" note={open.length ? 'students can sit these' : undefined} />
        <Stat value={subs === null ? '…' : unmarked.length} label="Waiting to be marked" />
        <Stat value={unreleased.length} label="Results not yet released" />
        <Stat value={students === null ? '…' : (students.length - invited)} label="Students signed in" note={invited ? `${invited} still invited` : undefined} />
      </div>
      {!courses.length && <div className="teacher-card teacher-list" style={{ marginBottom: '1.5rem' }}>
        <h2>Start here</h2>
        <p style={{ margin: '.8rem 0' }}>Create a course, add your students by email, then open a session for them.</p>
        <button className="teacher-primary" onClick={() => onNavigate('courses')}>Create your first course →</button>
      </div>}
      {!!courses.length && <div className="bb-actions" style={{ marginBottom: '1.5rem' }}>
        <button className="teacher-primary" onClick={() => onNavigate('sessions')}>Start a Bluebook session →</button>
        <button className="quiet-button" onClick={() => onNavigate('courses')}>Manage courses and invitations</button>
      </div>}
      {unreleased.length > 0 && <Section title="Ready to release">
        <Table rowKey={e => e.id} rows={unreleased} caption="Exams with unreleased results" columns={[
          { key: 'title', label: 'Examination', lead: true },
          { key: 'submissions', label: 'Submitted', num: true },
          { key: 'go', label: 'Open', actions: true, render: e => <LinkBtn onClick={() => manage(e.id)}>Mark and release →</LinkBtn> },
        ]} />
      </Section>}
      <Section title="Recent submissions">
        <Table rowKey={s => s.id} rows={(subs || []).slice(0, 8)} caption="Recent submissions" empty={subs === null ? 'Loading…' : 'Nothing submitted yet.'} columns={[
          { key: 'student', label: 'Student', lead: true },
          { key: 'exam', label: 'Examination' },
          { key: 'created_at', label: 'Submitted', render: s => when(s.created_at) },
          { key: 'mark', label: 'Mark', render: s => s.mark ? s.mark : <Badge tone="warn">to mark</Badge> },
          { key: 'go', label: 'Open', actions: true, render: s => s.exam_id ? <LinkBtn onClick={() => manage(s.exam_id)}>Read →</LinkBtn> : '—' },
        ]} />
      </Section>
    </>}
  </div>;
}

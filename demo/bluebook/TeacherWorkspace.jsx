import React, { useEffect, useRef, useState } from 'react';
import { BB_API, MockupFonts } from './components.jsx';
import { Badge, LinkBtn, Section, Stat, Table, when } from './forms.jsx';
import './teacher-workspace.css';

const dateLabel = value => value ? new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : '';

// Line icons for the navigation pills, drawn in the navy design's stroke style.
const NAV_ICONS = {
  overview: <><path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/></>,
  students: <><circle cx="9" cy="8" r="3.2"/><path d="M3 20c0-3.3 2.7-5 6-5s6 1.7 6 5"/><path d="M16 5.2a3.2 3.2 0 010 5.8"/><path d="M21 20c0-2.4-1.4-4-3.6-4.7"/></>,
  submissions: <><rect x="3" y="4" width="18" height="14" rx="2"/><path d="M8 21h8"/></>,
  sessions: <><path d="M4 19.5A2.5 2.5 0 016.5 17H20V3H6.5A2.5 2.5 0 004 5.5z"/><path d="M4 19.5A2.5 2.5 0 006.5 22H20v-5"/></>,
  reports: <><line x1="6" y1="20" x2="6" y2="12"/><line x1="12" y1="20" x2="12" y2="5"/><line x1="18" y1="20" x2="18" y2="9"/></>,
  exams: <><path d="M6 3h9l4 4v14H6z"/><path d="M14 3v5h5"/><path d="M9 13h7M9 17h5"/></>,
  courses: <><path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/></>,
  proctor: <><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></>,
};
const NAV_ICON_KEY = { dashboard: 'overview', results: 'submissions' };
function NavIcon({ name }) {
  return <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">{NAV_ICONS[NAV_ICON_KEY[name] || name]}</svg>;
}

// On a phone the pill strip scrolls inside itself, and the pills past its edge are out of sight.
// This marks the strip with .fade-start / .fade-end while there are more pills past that edge
// (teacher-workspace.css draws the fade) and opens it with the current page's pill in view.
const PILL_FADE_SLACK = 4;
function usePillFade(ref, deps) {
  useEffect(() => {
    const strip = ref.current;
    if (!strip) return undefined;
    const update = () => {
      strip.classList.toggle('fade-start', strip.scrollLeft > PILL_FADE_SLACK);
      strip.classList.toggle('fade-end', strip.scrollWidth - strip.clientWidth - strip.scrollLeft > PILL_FADE_SLACK);
    };
    const here = strip.querySelector('[aria-current="page"]');
    if (here && strip.scrollWidth > strip.clientWidth) {
      strip.scrollLeft = Math.max(0, here.offsetLeft - strip.offsetLeft - (strip.clientWidth - here.offsetWidth) / 2);
    }
    update();
    strip.addEventListener('scroll', update);
    window.addEventListener('resize', update);
    return () => {
      strip.removeEventListener('scroll', update);
      window.removeEventListener('resize', update);
    };
  }, deps);
}

// The avatar's letters: the first letter of the first two words of the
// teacher's name, letters and digits only ("Andrew (Alpha test)" is "AA",
// never "A("). "T" when there is no name to read.
export function avatarInitials(name) {
  const words = String(name || '').split(/\s+/).map(w => w.replace(/[^\p{L}\p{N}]/gu, '')).filter(Boolean);
  return words.slice(0, 2).map(w => w[0].toUpperCase()).join('') || 'T';
}

// The way from Collections into Original, labelled as in testing wherever it
// is offered (NORTH_STAR rule 10).
export const ORIGINAL_NAV_LABEL = 'Original (in testing) ↗';

// Screens that belong to the one Collections area (nav key 'sessions').
export const COLLECTIONS_SCREENS = ['sessions', 'collections', 'exams', 'manage-exam', 'new-exam'];

// Each teacher screen shows the photograph its 2026-10 mockup used
// (demo/original/assets/CREDITS.md); the Collections screens keep the library.
const TEACHER_PHOTO = { overview: 'night', dashboard: 'night', students: 'quad', submissions: 'interior', results: 'interior', reports: 'caius' };

export function TeacherFrame({ demo = false, active = 'sessions', onNavigate, children }) {
  const pills = useRef(null);
  usePillFade(pills, [active, demo]);
  const identity = demo ? {name: 'Professor · demonstration'} : BB_API.identity();
  const initials = avatarInitials(identity.name);
  const items = demo
    ? [['Overview','overview'],['Students','students'],['Submissions','submissions'],['Collections','sessions'],['Reports','reports']]
    : [['Overview','dashboard'],['Collections','sessions'],['Courses','courses'],['Students','students'],['Submissions','results'],['Proctor','proctor']];
  // One Collections area: the old Examinations list, the exam pages and the
  // collection aliases all light the Collections pill.
  const here = COLLECTIONS_SCREENS.includes(active) ? 'sessions' : active;
  const withOriginal = !demo && BB_API.hasOriginal();
  return <div className="teacher-ui">{!demo && <MockupFonts />}<div className="teacher-frame" data-photo={TEACHER_PHOTO[here] || 'library'}>
    <nav className="teacher-nav" aria-label="Teacher navigation">
      {/* The app is Collections; Original is the link below when the workspace holds it. */}
      <div className="teacher-brand"><span className="mk" aria-hidden="true"/>{demo ? 'Original' : 'Collections'}</div>
      <div ref={pills} className={'teacher-pills'+(items.length + (withOriginal ? 1 : 0) > 6 ? ' dense' : '')}>
        {items.map(([label,key]) => <button key={key} className={here===key?'on':''} aria-current={here===key?'page':undefined} onClick={()=>onNavigate(key)}><NavIcon name={key}/>{label}</button>)}
        {withOriginal && <button title="Original is in its testing phase and is not yet validated on real student writing." onClick={()=>{window.location.href='../original/';}}><NavIcon name="reports"/>{ORIGINAL_NAV_LABEL}</button>}
      </div>
      <div className="teacher-nav-right">
        {!demo && <>
          <button className="quiet-link" onClick={()=>onNavigate('account')}>Account</button>
          <button className="quiet-link" onClick={()=>{BB_API.logout();onNavigate('landing');}}>Sign out</button>
        </>}
        <span className="teacher-avatar" title={identity.name} aria-label={identity.name}>{demo?'P':initials}</span>
      </div>
    </nav>
    {demo && <div className="teacher-mode is-demo">
      <span>DEMONSTRATION · FICTIONAL RECORDS · NO DATA IS SAVED</span>
      <button onClick={()=>onNavigate('reset')}>Reset demo</button>
    </div>}
    <main className="teacher-body">{children}</main>
  </div></div>;
}

// The demonstration's COMPLETED is a finished session, like CLOSED.
const sessionState = e => String(e.status || '').toUpperCase() === 'COMPLETED' ? 'closed' : stateOf(e);
const SESSION_TONE = { open: 'live', closed: 'done', upcoming: 'look', draft: '' };

export function SessionSetup({ courses, exams, loading, error, onRetry, onCreate, onOpen, onCourses, demo=false, hasOriginal=false, receipt=null, onManage }) {
  const [questions,setQuestions]=useState(['']);
  const [courseId,setCourseId]=useState('');
  const [duration,setDuration]=useState(50);
  const [busy,setBusy]=useState(false);
  const [saveError,setSaveError]=useState('');
  const saving=useRef(false);
  const chip=useRef(null);
  // Show the confirmation when a session opens, even if the form was scrolled.
  useEffect(()=>{if(receipt&&chip.current&&chip.current.scrollIntoView)chip.current.scrollIntoView({block:'nearest'});},[receipt]);
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
    <header className="teacher-head"><div>
      <div className="eyebrow">Collections Sessions</div>
      <h1>In-class writing, in their own hand.</h1>
      {hasOriginal
        ? <p className="sub">A Collections session is a supervised essay written live in class. Sealed booklets stay as written. Because Original is on, <b>you choose</b> which become reference writing for each student, and you can undo that choice.</p>
        : <p className="sub">A Collections session is a supervised essay written live in class. Sealed booklets stay exactly as written, and you read them all in one place.</p>}
    </div></header>
    {error && <div role="alert" className="teacher-error">{error} <button onClick={onRetry}>Try again</button></div>}
    <div className="teacher-columns">
      <form className="teacher-card teacher-setup" onSubmit={submit}>
        <div className="setup-heading"><span className="book-mark" aria-hidden="true"/><div><h2>Start a new session</h2><p>Three questions. That’s the whole setup.</p></div></div>
        <div className="teacher-steps">
          <section className="teacher-step"><h3>What should they write about?</h3>
            {questions.map((q,i)=><div key={i} className="question-field"><label className={questions.length>1?undefined:'sr-only'} htmlFor={`teacher-question-${i}`}>Question {i+1}</label><textarea id={`teacher-question-${i}`} required maxLength={8000} disabled={busy} value={q} placeholder={i===0?'e.g. In two pages, explain the difference between Luther’s and Calvin’s views of the Lord’s Supper, and which you find more persuasive, and why.':`Question ${i+1}. Students can move between questions freely.`} onChange={e=>setQuestions(questions.map((v,j)=>j===i?e.target.value:v))}/>{i>0&&<button type="button" className="quiet-button" disabled={busy} onClick={()=>setQuestions(questions.filter((_,j)=>j!==i))}>Remove question {i+1}</button>}</div>)}
            <button type="button" className="add-question" disabled={busy||questions.length>=8} onClick={()=>setQuestions([...questions,''])}>+ Add {questions.length===1?'a second':'another'} question</button>
            <p className="hint">Write it the way you’d say it aloud. Students see exactly these words.</p>
          </section>
          <section className="teacher-step"><h3>Which class?</h3><div className="class-choices" aria-label="Choose a class">
            {loading?<p role="status">Loading your classes…</p>:courses.map(c=><button type="button" key={c.id} disabled={busy} aria-pressed={selected?.id===c.id} onClick={()=>setCourseId(c.id)}>{c.code||c.name} · {c.students??0} student{c.students===1?'':'s'}</button>)}
          </div>{!loading&&!courses.length&&!error&&<p>No classes yet. <button type="button" className="quiet-button" onClick={onCourses}>Create your first course</button></p>}</section>
          <section className="teacher-step"><h3><label htmlFor="teacher-duration">How long do they get?</label></h3><div className="time-row"><input id="teacher-duration" aria-label="Session duration in minutes" type="range" min="15" max="120" step="5" value={duration} disabled={busy} onChange={e=>setDuration(Number(e.target.value))}/><output htmlFor="teacher-duration">{duration} min</output></div>
            <div className="quiet-note"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l8 4v6c0 5-3.5 7.5-8 8-4.5-.5-8-3-8-8V7z"/><path d="M9 12l2 2 4-4"/></svg><p><strong>Everything else is already handled.</strong> Drafts save on the student’s device every few seconds, and the finished booklet reaches you when they seal it. Collections keeps the text and a few session facts (time spent, word count, paste attempts, print or save attempts, times the window lost focus), never the screen or camera. Session facts are context for you to read afterward, not evidence.</p></div>
          </section>
        </div>
        {saveError&&<p className="teacher-error" role="alert">{saveError}</p>}
        <div className="launch-row"><button className="teacher-primary" disabled={busy||loading||!!error||!courses.length} type="submit"><svg viewBox="0 0 24 24" aria-hidden="true"><polygon points="6 3 20 12 6 21 6 3"/></svg>{busy?'Opening…':'Open the booklets'}</button><span>{selected?.code||selected?.name||'Choose a class'} · {questions.length} question{questions.length>1?'s':''} · {duration} minutes</span></div>
        {receipt&&<div className="code-chip" role="status" ref={chip}><div className="code">OPEN</div><div className="cc-l">Session is open. Students on this class roster find it under <b>My exams</b>.</div><button type="button" onClick={()=>onManage(receipt)}>Manage session and read submissions →</button></div>}
      </form>
      <aside><section className="teacher-card session-history"><div className="section-title"><h2>Sessions</h2><span>{demo?'example term':`${exams.length} in total`}</span></div>
        {loading?<p role="status">Loading sessions…</p>:!exams.length?<p>No sessions yet. Your first one will appear here.</p>:exams.map(e=>{const st=sessionState(e);return <button className="session-row" key={e.id} onClick={()=>onOpen(e)}><span className={'small-book'+(st==='closed'?' done':'')} aria-hidden="true"/><span className="session-title"><strong>{e.title}</strong><small>{[e.course,dateLabel(e.created_at),`${e.duration} min`].filter(Boolean).join(' · ')}</small></span><span className="session-badge"><span className={'s-badge '+SESSION_TONE[st]}><span className="d"/>{st}</span><small>{e.submissions??0} sealed</small></span></button>;})}
      </section><section className="teacher-card teacher-why"><h2>Why Collections matters</h2>
        {hasOriginal
          ? <p>Collections gives students a quiet, trustworthy place to write. Because Original is on, the sealed booklets you <b>approve</b> become the reference writing it compares later papers against. More approved samples give it more to go on; with only a few, it may say it can’t tell.</p>
          : <p>Collections gives students a quiet, trustworthy place to write. Give them a clear prompt and enough time, then read their work, in their own words, in one place.</p>}
      </section></aside>
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
  // Refresh the stored products (Original can be switched on or off while
  // signed in); nothing here displays the answer, so a failure is ignored.
  useEffect(()=>{BB_API.authMe().catch(()=>{});},[]);
  const open=exam=>{window.BB_MANAGE_EXAM=exam.id;onNavigate('manage-exam');};
  if(overview) return <TeacherOverview onNavigate={onNavigate} courses={data.courses} exams={data.exams} loading={loading} error={error} onRetry={()=>setRetry(v=>v+1)}/>;
  return <SessionSetup {...data} loading={loading} error={error} onRetry={()=>setRetry(v=>v+1)} onCourses={()=>onNavigate('courses')} hasOriginal={BB_API.hasOriginal()} onOpen={open} receipt={created} onManage={open} onCreate={async payload=>{const e=await BB_API.createExam(payload);setData(d=>({...d,exams:[e,...d.exams]}));setCreated(e);}}/>;
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
    <header className="teacher-head"><div className="eyebrow">Your teaching workspace</div><h1>{name ? `Welcome back, ${name}.` : 'Begin with the writing.'}</h1><p>Set a collection, invite your class, and give their words a thoughtful reading.</p></header>
    {error && <div role="alert" className="teacher-error">{error} <button onClick={onRetry}>Try again</button></div>}
    {detailError && !error && <div role="alert" className="teacher-error">{detailError} <button onClick={loadDetails}>Try again</button></div>}
    {loading ? <p role="status">Loading your workspace…</p> : !error && !detailError && <>
      <div className="bb-grid cols-4" style={{ marginBottom: '1.5rem' }}>
        <Stat value={open.length} label="Open now" note={open.length ? 'students can sit these' : undefined} />
        <Stat value={subs === null ? '…' : unmarked.length} label="Waiting to be marked" />
        <Stat value={unreleased.length} label="Results not yet released" />
        <Stat value={students === null ? '…' : (students.length - invited)} label="Students who have joined" note={invited ? `${invited} not joined yet` : undefined} />
      </div>
      {!courses.length && <div className="teacher-card teacher-list" style={{ marginBottom: '1.5rem' }}>
        <h2>Start here</h2>
        <p style={{ margin: '.8rem 0' }}>Create a course, add your students by email, then open a session for them.</p>
        <button className="teacher-primary" onClick={() => onNavigate('courses')}>Create your first course →</button>
      </div>}
      {!!courses.length && <div className="bb-actions" style={{ marginBottom: '1.5rem' }}>
        <button className="teacher-primary" onClick={() => onNavigate('new-exam')}>New collection →</button>
        <button className="quiet-button" onClick={() => onNavigate('courses')}>Manage courses and invitations</button>
      </div>}
      {unreleased.length > 0 && <Section title="Ready to release">
        <Table rowKey={e => e.id} rows={unreleased} caption="Collections with unreleased results" columns={[
          { key: 'title', label: 'Collection', lead: true },
          { key: 'submissions', label: 'Submitted', num: true },
          { key: 'go', label: 'Open', actions: true, render: e => <LinkBtn onClick={() => manage(e.id)}>Mark and release →</LinkBtn> },
        ]} />
      </Section>}
      <Section title="Recent submissions">
        <Table rowKey={s => s.id} rows={(subs || []).slice(0, 8)} caption="Recent submissions" empty={subs === null ? 'Loading…' : 'Nothing submitted yet.'} columns={[
          { key: 'student', label: 'Student', lead: true },
          { key: 'exam', label: 'Collection' },
          { key: 'created_at', label: 'Submitted', render: s => when(s.created_at) },
          { key: 'mark', label: 'Mark', render: s => s.mark ? s.mark : <Badge tone="warn">to mark</Badge> },
          { key: 'go', label: 'Open', actions: true, render: s => s.exam_id ? <LinkBtn onClick={() => manage(s.exam_id)}>Read →</LinkBtn> : '—' },
        ]} />
      </Section>
    </>}
  </div>;
}

// Courses.jsx — the real course registry (GET /bluebook/courses), with an
// honest limit stated up front: bluebook_courses exists and is real, but
// nothing in the schema links it to student_profiles or submission_manifests
// (the tables every other page in this app reads). bluebook_exams and
// bluebook_submissions each carry a free-text `course` string, not a foreign
// key to bluebook_courses.course_id — so "students enrolled" / "baseline
// coverage" / "flags" per course cannot be shown without a real schema
// change (see the note rendered below; this is not a client-side gap).

import { useEffect, useState } from 'react';
import { getJSON } from './api.js';
import { Sidebar, Topbar, Icon } from './components.jsx';
import { fmtDate } from './util.js';

export function Courses() {
  const [courses, setCourses] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    getJSON('/bluebook/courses').then((r) => alive && setCourses((r && r.courses) || []))
      .catch((e) => alive && setError(String(e.message || e)));
    return () => { alive = false; };
  }, []);

  return (
    <>
      <Sidebar active="courses" />
      <div className="main">
        <Topbar crumb="Courses" semester="Live demo" />
        <div className="page-body">
          <div className="page-header">
            <div>
              <h1 className="page-title">Courses</h1>
              <p className="page-subtitle">{courses === null ? 'Loading…' : `${courses.length} registered · from /bluebook/courses`}</p>
            </div>
          </div>

          <div className="dash-error" style={{ background: 'var(--gold-light)', color: 'var(--amber)', border: '1px solid var(--gold-muted)' }}>
            This list is real (Bluebook's course registry), but it's disconnected from the roster/scoring data
            the rest of this app uses — <code>bluebook_courses</code> has no link to <code>student_profiles</code>
            or <code>submission_manifests</code> in the schema today. So you'll see real courses here, but not
            which students are in them or how they're scoring — that needs a real backend change, not a
            frontend one.
          </div>

          {error && <div className="dash-error">Couldn't load courses: {error}</div>}

          <div className="section-card">
            <div className="student-head" style={{ gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr' }}>
              <div className="th">Course</div>
              <div className="th">Code</div>
              <div className="th">Term</div>
              <div className="th">Status</div>
              <div className="th right">Registered</div>
            </div>
            {courses === null && <div className="empty-state"><p>Loading…</p></div>}
            {courses && courses.length === 0 && (
              <div className="empty-state"><h3>No courses yet</h3><p>Create one from the classic Bluebook admin view.</p></div>
            )}
            {courses && courses.map((c) => (
              <div className="student-row" key={c.course_id} style={{ gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr', cursor: 'default' }}>
                <div className="s-name">{c.name}</div>
                <div className="td">{c.code || '—'}</div>
                <div className="td">{c.term || '—'}</div>
                <div className="td"><span className={'baseline-pill ' + (c.status === 'ACTIVE' ? 'strong' : 'none')}><span className="bp-dot" />{c.status}</span></div>
                <div className="td right">{fmtDate(c.created_at)}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}

// components.jsx — presentational pieces for the Oxford dashboard shell.
// Markup + classNames mirror the Claude Design mockup (original-dashboard.html);
// data is passed in as props (no hardcoded values).

import { useEffect, useState } from 'react';
import { getJSON } from './api.js';

const ICONS = {
  grid: <><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></>,
  book: <><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></>,
  users: <><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></>,
  flag: <><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></>,
  upload: <><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></>,
  bar: <><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></>,
  building: <><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></>,
  gear: <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></>,
  search: <><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></>,
  bell: <><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></>,
  plus: <><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></>,
  eye: <><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></>,
  alert: <><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></>,
  clock: <><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></>,
  inbox: <><polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></>,
  sliders: <><line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/></>,
  atom: <><circle cx="12" cy="12" r="10"/><path d="M8.56 2.75c4.37 6.03 6.02 9.42 8.03 17.72m2.54-15.38c-3.72 4.35-8.94 5.66-16.88 5.85m19.5 1.9c-3.5-.93-6.63-.82-8.94 0-2.58.92-5.01 2.86-7.44 6.32"/></>,
  activity: <><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></>,
  user: <><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></>,
  edit: <><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></>,
};

export function Icon({ name }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      {ICONS[name] || null}
    </svg>
  );
}

function NavItem({ icon, label, active, href = '#', badge }) {
  return (
    <a className={'nav-item' + (active ? ' active' : '')} href={href}>
      <Icon name={icon} />
      {label}
      {badge != null && <span className="nav-badge">{badge}</span>}
    </a>
  );
}

export function Sidebar({ school, flaggedCount, active = 'dashboard' }) {
  const is = (k) => k === active;
  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <div className="logo-mark">
          <div className="logo-icon">
            <svg viewBox="0 0 24 24" fill="none" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
            </svg>
          </div>
          <span className="logo-wordmark">Original</span>
        </div>
        <div className="logo-school">{school || 'Pilot Institution'}</div>
      </div>

      <nav className="sidebar-nav">
        <div className="nav-section-label">Workspace</div>
        <NavItem icon="grid" label="Dashboard" active={is('dashboard')} href="index.html" />
        <NavItem icon="upload" label="Submissions" active={is('submissions')} href="submissions.html" />
        <NavItem icon="users" label="Students" active={is('students')} href="students.html" />
        <NavItem icon="flag" label="Flagged" active={is('flagged')} href="flagged.html" badge={flaggedCount != null ? flaggedCount : undefined} />
        <NavItem icon="bar" label="Reports" active={is('reports')} href="reports.html" />
        <NavItem icon="book" label="Courses" active={is('courses')} href="courses.html" />
        <NavItem icon="edit" label="Bluebook" href="/bluebook/" />

        <div className="nav-section-label">Research</div>
        <NavItem icon="sliders" label="Fingerprint" active={is('fingerprint')} href="fingerprint.html" />
        <NavItem icon="atom" label="Quantum State" active={is('quantum')} href="quantum.html" />
        <NavItem icon="activity" label="Interference" active={is('interference')} href="interference.html" />

        <div className="nav-section-label">Institution</div>
        <NavItem icon="building" label="Admin" active={is('admin')} href="admin.html" />
        <NavItem icon="inbox" label="Operator" active={is('operator')} href="operator.html" />
        <NavItem icon="gear" label="Settings" active={is('settings')} href="settings.html" />
        {/* Bridges to the classic app + the student-facing surface */}
        <NavItem icon="eye" label="Classic analysis" href="/professor.html" />
        <NavItem icon="user" label="Student portal" active={is('portal')} href="portal.html" />
      </nav>

      <div className="sidebar-user">
        <div className="user-avatar">AC</div>
        <div className="user-info">
          <div className="user-name">Instructor</div>
          <div className="user-role">Demo principal</div>
        </div>
      </div>
    </aside>
  );
}

export function Topbar({ crumb, semester }) {
  // No decorative search/bell buttons — they did nothing and just squeezed
  // the breadcrumb at narrow widths.
  return (
    <div className="topbar">
      <div className="topbar-left">
        <div className="breadcrumb">
          <span>Original</span>
          <span className="breadcrumb-sep">/</span>
          <span className="breadcrumb-current">{crumb}</span>
        </div>
      </div>
      <div className="topbar-right">
        {semester && <div className="semester-badge">{semester}</div>}
      </div>
    </div>
  );
}

export function StatCard({ variant = 'default', label, value, unit, meta }) {
  return (
    <div className={'stat-card stat-' + variant}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">
        {value}
        {unit && <span style={{ fontSize: '1.1rem', fontWeight: 400 }}>{unit}</span>}
      </div>
      <div className="stat-meta">{meta}</div>
    </div>
  );
}

export function SectionCard({ title, titleMeta, action, children }) {
  return (
    <div className="section-card">
      <div className="section-head">
        <div>
          <span className="section-title">{title}</span>
          {titleMeta && <span className="section-title-meta">{titleMeta}</span>}
        </div>
        {action}
      </div>
      {children}
    </div>
  );
}

// Shared per-student selector for the Research pages: loads the roster,
// honors ?student=<id>, and reports the selection upward. Purely a picker —
// pages fetch their own per-student data on change.
export function useStudentSelection() {
  const [students, setStudents] = useState([]);
  const [studentId, setStudentId] = useState('');
  useEffect(() => {
    let alive = true;
    const preselect = new URLSearchParams(window.location.search).get('student');
    getJSON('/students').then((r) => {
      if (!alive) return;
      const ids = (r && r.students) || [];
      setStudents(ids);
      if (preselect && ids.includes(preselect)) setStudentId(preselect);
      else if (ids.length) setStudentId(ids[0]);
    }).catch(() => {});
    return () => { alive = false; };
  }, []);
  return { students, studentId, setStudentId };
}

export function StudentPicker({ students, studentId, onChange, shortLabelFn }) {
  return (
    <select className="a-select" style={{ maxWidth: 320 }} value={studentId} onChange={(e) => onChange(e.target.value)}>
      {students.length === 0 && <option value="">Loading…</option>}
      {students.map((id) => (
        <option key={id} value={id} style={{ textTransform: 'capitalize' }}>
          {shortLabelFn ? shortLabelFn(id) : id}
        </option>
      ))}
    </select>
  );
}

// Shared audit-log table (Admin + Operator pages) over GET /admin/audit.
// Items: {created_at, action, student_id, tenant_id, actor, result, details}.
export function AuditTable({ items, loading }) {
  if (loading) return <div className="empty-state"><p>Loading audit log…</p></div>;
  if (!items || items.length === 0) return <div className="empty-state"><p>No audit entries yet.</p></div>;
  return (
    <div className="audit-table">
      <div className="audit-head">
        <div className="th">When</div>
        <div className="th">Action</div>
        <div className="th">Subject</div>
        <div className="th">Result</div>
      </div>
      {items.map((a, i) => (
        <div className="audit-row" key={a.id ?? i}>
          <div className="td audit-when">{(a.created_at || '').replace('T', ' ').slice(0, 16)}</div>
          <div className="td"><span className="flag-course-tag" style={{ textTransform: 'none' }}>{a.action}</span></div>
          <div className="td audit-subject">{a.student_id || a.tenant_id || a.actor || '—'}</div>
          <div className="td">{a.result || '—'}</div>
        </div>
      ))}
    </div>
  );
}

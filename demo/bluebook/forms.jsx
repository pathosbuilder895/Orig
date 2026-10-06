import React from 'react';
import { BB, BtnPrimary, GoldRule, Logotype, fontBody, fontDisplay, fontMono } from './components.jsx';
import './bluebook-app.css';

// ════════════════════════════════════════════════════════════════
//  BLUEBOOK — shared pieces for the self-serve screens.
//  Layout comes from bluebook-app.css (responsive at 1000px and 600px),
//  in the visual language of the teacher frame (TeacherWorkspace.jsx).
// ════════════════════════════════════════════════════════════════

export function Field({ id, label, type = 'text', value, onChange, placeholder, autoComplete, required = true, hint, ...rest }) {
  return (
    <div className="bb-field">
      <label htmlFor={id}>{label}</label>
      <input id={id} className="bb-input" type={type} value={value} onChange={e => onChange(e.target.value)}
        placeholder={placeholder} autoComplete={autoComplete} required={required} {...rest} />
      {hint && <p className="bb-hint">{hint}</p>}
    </div>
  );
}

export function TextArea({ id, label, value, onChange, rows = 4, placeholder, hint, ...rest }) {
  return (
    <div className="bb-field">
      <label htmlFor={id}>{label}</label>
      <textarea id={id} className="bb-input" rows={rows} value={value} placeholder={placeholder}
        onChange={e => onChange(e.target.value)} {...rest} />
      {hint && <p className="bb-hint">{hint}</p>}
    </div>
  );
}

export function Select({ id, label, value, onChange, children }) {
  return (
    <div className="bb-field">
      <label htmlFor={id}>{label}</label>
      <select id={id} className="bb-input" value={value} onChange={e => onChange(e.target.value)}>{children}</select>
    </div>
  );
}

export function ErrorText({ children }) {
  if (!children) return null;
  return <p role="alert" className="bb-error">{children}</p>;
}

export function Notice({ children }) {
  if (!children) return null;
  return <p role="status" className="bb-notice">{children}</p>;
}

export function Btn({ children, primary = false, danger = false, className = '', ...rest }) {
  const cls = ['bb-btn', primary && 'primary', danger && 'danger', className].filter(Boolean).join(' ');
  return <button type="button" className={cls} {...rest}>{children}</button>;
}

export function LinkBtn({ children, muted = false, danger = false, ...rest }) {
  const cls = ['bb-link', muted && 'muted', danger && 'danger'].filter(Boolean).join(' ');
  return <button type="button" className={cls} {...rest}>{children}</button>;
}

// Kept for older call sites: small text-styled action.
export function SmallCaps({ onClick, children, disabled = false }) {
  return <LinkBtn onClick={onClick} disabled={disabled}>{children}</LinkBtn>;
}
export const TextLink = SmallCaps;

const BADGE_TONE = {
  open: 'ok', active: 'ok', submitted: 'ok', released: 'ok', writing: 'warn',
  invited: 'warn', upcoming: 'warn', scheduled: 'warn', draft: '', closed: '',
  late: 'bad', not_started: '', time_up: 'bad', link: '',
};
export function Badge({ children, tone }) {
  const key = String(children || '').toLowerCase().replace(/\s+/g, '_');
  const t = tone !== undefined ? tone : (BADGE_TONE[key] || '');
  return <span className={'bb-badge ' + t}>{String(children || '').replace(/_/g, ' ')}</span>;
}

// Page frame. `title`, optional `eyebrow`, `meta`, and right-aligned `actions`.
export function Page({ title, eyebrow, meta, actions, children }) {
  return (
    <div className="bb-page">
      <header className="bb-head">
        <div>
          {eyebrow && <div className="bb-eyebrow">{eyebrow}</div>}
          <h1>{title}</h1>
          {meta && <p className="bb-meta">{meta}</p>}
        </div>
        {actions && <div className="bb-actions">{actions}</div>}
      </header>
      {children}
    </div>
  );
}

export function Panel({ children, className = '', style }) {
  return <section className={'bb-card ' + className} style={style}>{children}</section>;
}

export function Section({ title, actions, children }) {
  return (
    <section className="bb-section">
      {(title || actions) && (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
          {title && <h2>{title}</h2>}
          {actions && <div className="bb-actions">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

// Responsive table. columns: [{key, label, lead?, num?, actions?, render?(row)}].
// On phones every row becomes a card; the `lead` column is its title.
export function Table({ columns, rows, rowKey, empty = 'Nothing here yet.', caption }) {
  return (
    <div className="bb-table-wrap">
      <table className="bb-table">
        {caption && <caption style={{ position: 'absolute', left: -9999 }}>{caption}</caption>}
        <thead><tr>{columns.map(c => <th key={c.key} scope="col">{c.label}</th>)}</tr></thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td className="bb-empty lead" colSpan={columns.length}>{empty}</td></tr>
          )}
          {rows.map(r => (
            <tr key={rowKey(r)}>
              {columns.map(c => (
                <td key={c.key} data-label={c.label}
                  className={[c.lead && 'lead', c.num && 'num', c.actions && 'actions'].filter(Boolean).join(' ') || undefined}>
                  {c.render ? c.render(r) : (r[c.key] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Stat({ value, label, note }) {
  return <div className="bb-card bb-stat"><strong>{value}</strong><span>{label}</span>{note && <small>{note}</small>}</div>;
}

// Centered card for the public auth screens (sign in style).
export function AuthShell({ title, onBack, children, footer }) {
  return (
    <div className="bb-screen" style={{
      minHeight: '100vh', background: BB.oxford,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: 16,
    }}>
      {onBack && (
        <button onClick={onBack} style={{
          position: 'fixed', top: 20, left: 20,
          fontFamily: fontMono, fontSize: 11, letterSpacing: '0.18em',
          textTransform: 'uppercase', color: BB.fade,
          background: 'none', border: 'none', cursor: 'pointer', padding: 10,
        }}>← Return</button>
      )}
      <div style={{ width: '100%', maxWidth: 420 }}>
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <Logotype size={28} />
          <GoldRule double style={{ margin: '18px 0 14px' }} />
          <h1 style={{
            fontFamily: fontDisplay, fontStyle: 'italic', fontWeight: 400,
            fontSize: 21, color: BB.fade, letterSpacing: '0.04em', margin: 0,
          }}>{title}</h1>
        </div>
        <div className="bb-page" style={{ border: '1px solid rgba(201,169,97,0.28)', padding: 'clamp(20px, 5vw, 32px)' }}>
          {children}
        </div>
        {footer}
      </div>
    </div>
  );
}

export function SubmitButton({ busy, children, busyLabel = 'Working…' }) {
  return (
    <BtnPrimary full style={{ padding: '14px 0', fontSize: 17 }}>
      {busy ? busyLabel : children}
    </BtnPrimary>
  );
}

// Plain text for small print inside dark pages.
export function Small({ children }) {
  return <p style={{ fontFamily: fontBody, fontSize: 15, color: BB.fade, lineHeight: 1.55 }}>{children}</p>;
}

// Local, human date-time for an ISO string (or an em dash).
export function when(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d)) return '—';
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

// ISO string -> value for <input type="datetime-local"> in local time.
export function toLocalInput(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return '';
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// <input type="datetime-local"> value (local time) -> ISO string, or null.
export function fromLocalInput(v) {
  if (!v) return null;
  const d = new Date(v);
  return isNaN(d) ? null : d.toISOString();
}

// An exam's questions: the list when present, else the single legacy prompt.
export function questionsOf(exam) {
  const qs = (exam && exam.questions) || [];
  if (qs.length) return qs;
  return exam && exam.prompt ? [exam.prompt] : [];
}

// Save text as a file in the browser.
export function downloadText(filename, text, type = 'text/csv') {
  const url = URL.createObjectURL(new Blob([text], { type: type + ';charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch (e) { return false; }
}

export function absoluteLink(path) {
  try { return new URL(path, window.location.origin).toString(); } catch (e) { return path; }
}

export function csvCell(v) {
  const s = v == null ? '' : String(v);
  const safe = /^[=+\-@\t\r]/.test(s) ? "'" + s : s;
  return /[",\n]/.test(safe) ? '"' + safe.replace(/"/g, '""') + '"' : safe;
}

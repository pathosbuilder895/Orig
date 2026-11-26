import React, { useEffect, useRef, useState } from 'react';
import { InstructionsGuide, openGuide } from './instructions.jsx';

// The one top bar of both apps (W3, ADR-015 section 4): the same markup and
// classes as demo/original/shell.js (Shell.markup), styled by
// demo/assets/tokens.css. Brand mark and the current app's name, the app
// switch (Collections | Original), the app's own pages as pills, and the
// account menu. Display only: the pages, routes and actions are the ones
// each screen already had; this draws them.

const ICON = {
  book: <><path d="M4 19.5A2.5 2.5 0 016.5 17H20V3H6.5A2.5 2.5 0 004 5.5z"/><path d="M4 19.5A2.5 2.5 0 006.5 22H20v-5"/></>,
  user: <><circle cx="12" cy="8" r="3.4"/><path d="M5 20c0-3.6 3-5.6 7-5.6s7 2 7 5.6"/></>,
  help: <><circle cx="12" cy="12" r="9"/><path d="M9.6 9.4a2.5 2.5 0 114 2c-.9.6-1.6 1.1-1.6 2.1"/><path d="M12 17h.01"/></>,
  out: <><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/></>,
};
const Icon = ({ name }) => <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">{ICON[name]}</svg>;

// The avatar's letters: the first letter of the first two words of the
// teacher's name, letters and digits only ("Andrew (Alpha test)" is "AA",
// never "A("), the fallback ("T") when there is no name to read.
export function avatarInitials(name, fallback = 'T') {
  const words = String(name || '').split(/\s+/).map(w => w.replace(/[^\p{L}\p{N}]/gu, '')).filter(Boolean);
  return words.slice(0, 2).map(w => w[0].toUpperCase()).join('') || fallback;
}

// The way from Collections into Original, labelled as in testing wherever it
// is offered (NORTH_STAR rule 10).
export const ORIGINAL_NAV_LABEL = 'Original (in testing)';

const ROLE = { professor: 'Teacher', admin: 'Workspace admin', operator: 'Operator', super_admin: 'Platform admin' };
export const roleLabel = role => ROLE[role] || '';

/**
 * @param navLabel     the nav landmark's name ("Teacher navigation")
 * @param appName      the brand's word: the current app
 * @param pills        [{ key, label, icon (node), current, onClick, title? }]
 * @param pillsRef     ref + className for the page strip (TeacherFrame's fade)
 * @param original     { href, label, title }: the Original side of the switch,
 *                     or null where this audience is not offered Original
 * @param account      { onClick, current }: the Account item, or null
 * @param guideFor     'teacher' | 'student': adds the Instructions item and its dialog
 * @param onSignOut    adds the Sign out item
 * @param name, sub, initials   who is signed in (menu head and the button)
 * @param sticky       the student pages' bar over a full-width page
 */
export function AppBar({ navLabel, appName = 'Collections', pills = [], pillsRef, pillsClass = '', original = null, account = null, guideFor = null, onSignOut = null, name = '', sub = '', initials = '··', sticky = false }) {
  const [open, setOpen] = useState(false);
  const btn = useRef(null);
  const wrap = useRef(null);
  const guide = useRef(null);

  // Escape closes the menu and gives focus back to the account button; a click
  // anywhere else closes it too (the same behaviour as shell.js).
  useEffect(() => {
    if (!open) return undefined;
    const onKey = e => { if (e.key === 'Escape') { setOpen(false); if (btn.current) btn.current.focus(); } };
    const onDoc = e => { if (wrap.current && !wrap.current.contains(e.target)) setOpen(false); };
    document.addEventListener('keydown', onKey);
    document.addEventListener('click', onDoc);
    return () => { document.removeEventListener('keydown', onKey); document.removeEventListener('click', onDoc); };
  }, [open]);

  const hasText = typeof window !== 'undefined' && !!window.BBDisplay;
  const pick = fn => () => { setOpen(false); fn(); };

  return <nav className={'shell' + (sticky ? ' shell-bar' : '') + (original ? '' : ' no-switch')} aria-label={navLabel}>
    <div className="brand"><span className="mk" aria-hidden="true"/><span className="bn">{appName}</span></div>
    {original && <div className="app-switch" role="group" aria-label="Apps">
      <a aria-current="true">Collections</a>
      <a href={original.href} title={original.title}>{original.label}</a>
    </div>}
    <div ref={pillsRef} className={'pills' + (pillsClass ? ' ' + pillsClass : '')}>
      {pills.map(p => <button key={p.key} type="button" className={'pill' + (p.current ? ' on' : '')} aria-current={p.current ? 'page' : undefined} title={p.title} onClick={p.onClick}>{p.icon}{p.label}</button>)}
    </div>
    <div className="nav-right" ref={wrap}>
      <button ref={btn} className="avatar" id="me-btn" type="button" title="Account" aria-label="Account" aria-haspopup="true" aria-expanded={open} aria-controls="me-menu" onClick={() => setOpen(o => !o)}>{initials}</button>
      <div className={'me-menu' + (open ? ' open' : '')} id="me-menu">
        <div className="mm-head"><b id="mm-name">{name || 'Your account'}</b><span id="mm-sub">{sub}</span></div>
        {account && <button type="button" aria-current={account.current ? 'page' : undefined} onClick={pick(account.onClick)}><Icon name="user"/>Account</button>}
        {guideFor && <button type="button" aria-haspopup="dialog" onClick={pick(() => openGuide(guide))}><Icon name="help"/>Instructions</button>}
        {hasText && <button type="button" id="mm-text" data-testid="text-settings-button" aria-haspopup="dialog" title="Text size and font" onClick={pick(() => window.BBDisplay.open(btn.current))}><span className="mm-aa" aria-hidden="true">Aa</span>Text</button>}
        {onSignOut && <button type="button" id="sign-out" onClick={pick(onSignOut)}><Icon name="out"/>Sign out</button>}
      </div>
    </div>
    {guideFor && <InstructionsGuide who={guideFor} dialog={guide} returnFocusTo={btn} />}
  </nav>;
}

export { Icon as MenuIcon };

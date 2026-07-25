import React from 'react';
import { BB, BB_API, BtnGhost, BtnPrimary, GoldRule, MetaLabel, Ornament, fontBody, fontDisplay, fontMono, rowKeyDown } from './components.jsx';
import { qrEncode, qrPath } from './vendor/qr.js';

// ════════════════════════════════════════════════════════════════
//  BLUEBOOK — Proctor tiles (QR phone park)
// ════════════════════════════════════════════════════════════════
//
// One tile per parked phone, refreshed every 5s. A tile is a prompt for a
// person to look up — never a verdict, and the copy in here has to keep it
// that way. docs/PROCTOR_SCRIPT.md teaches proctors two rules: one quiet word
// per event, and never accuse from a tile alone. Nothing on this screen should
// contradict either, so there is no "violation", no "suspicious", no counts of
// anything that reads like a tally of offences.
//
// `state` is derived server-side: a phone unseen for 30s reads "dropped"
// whatever it last claimed, because a phone in a pocket cannot tell us it left.
// We render what the server says and never recompute it here — the client
// clock, the poll offset and the network delay would all disagree with it.

const POLL_MS = 5000;

// The presentation of each state the server can hand us. `tone` drives colour,
// but colour is never the only cue: `label` carries the meaning in words and
// `glyph` distinguishes the states by shape, so the tiles still read correctly
// in greyscale or with any form of colour blindness (WCAG 1.4.1).
const STATE_VIEW = {
  parked:          { label: 'Parked',   glyph: '●', tone: 'calm', note: 'Phone present and idle.' },
  resumed:         { label: 'Resumed',  glyph: '●', tone: 'calm', note: 'Came back after being away.' },
  foreground_lost: { label: 'Away',     glyph: '▲', tone: 'attn', note: 'The page stopped being visible.' },
  dropped:         { label: 'Dropped',  glyph: '▲', tone: 'attn', note: 'No signal for over 30 seconds.' },
};

const TONE = {
  calm: { color: '#5EB87C', border: 'rgba(94,184,124,0.32)', wash: 'rgba(94,184,124,0.05)' },
  attn: { color: '#C9A961', border: 'rgba(201,169,97,0.40)', wash: 'rgba(201,169,97,0.06)' },
};

function viewFor(state) {
  return STATE_VIEW[state] || { label: state || 'Unknown', glyph: '◆', tone: 'attn', note: '' };
}

function agoLabel(seconds) {
  const s = Math.max(0, Number(seconds) || 0);
  if (s < 60) return `last seen ${s}s ago`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m < 60) return `last seen ${m}m ${rem}s ago`;
  return `last seen ${Math.floor(m / 60)}h ${m % 60}m ago`;
}

function clockTime(iso) {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso || '');
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

// ─── One tile ────────────────────────────────────────────────────────────────
function Tile({ tile, expanded, onToggle }) {
  const view = viewFor(tile.state);
  const tone = TONE[view.tone];
  const transitions = tile.transitions || [];

  return (
    <div style={{ border: `1px solid ${tone.border}`, background: BB.oxford }}>
      <div
        style={{
          padding: '14px 16px',
          cursor: 'pointer',
          background: expanded ? tone.wash : 'transparent',
          borderLeft: `3px solid ${expanded ? tone.color : 'transparent'}`,
          transition: 'background 0.2s',
        }}
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        aria-label={`${tile.student_hint} — ${view.label}, ${agoLabel(tile.last_seen_seconds_ago)}. ${expanded ? 'Hide' : 'Show'} timeline.`}
        onClick={onToggle}
        onKeyDown={rowKeyDown(onToggle)}
      >
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 10 }}>
          <p style={{
            fontFamily: fontBody, fontSize: 17, color: BB.cream,
            margin: 0, letterSpacing: '0.01em',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>{tile.student_hint}</p>
          {/* glyph + word + colour: three cues, any one of which is enough */}
          <span style={{
            fontFamily: fontMono, fontSize: 11, letterSpacing: '0.16em',
            textTransform: 'uppercase', color: tone.color,
            display: 'inline-flex', alignItems: 'center', gap: 6, flexShrink: 0,
          }}>
            <span aria-hidden="true" style={{ fontSize: 10 }}>{view.glyph}</span>
            {view.label}
          </span>
        </div>
        <MetaLabel style={{ display: 'block', marginTop: 7, textTransform: 'none', letterSpacing: '0.06em' }}>
          {agoLabel(tile.last_seen_seconds_ago)}
        </MetaLabel>
      </div>

      {expanded && (
        <div style={{ borderTop: `1px solid ${tone.border}`, padding: '12px 16px 14px' }}>
          <MetaLabel style={{ display: 'block', marginBottom: 10 }}>Timeline</MetaLabel>
          {transitions.length === 0 ? (
            <p style={{ fontFamily: fontBody, fontSize: 14, color: BB.fade, margin: 0 }}>
              No changes recorded yet.
            </p>
          ) : (
            <ol style={{ listStyle: 'none', margin: 0, padding: 0 }}>
              {transitions.map((t, i) => {
                const tv = viewFor(t.state);
                return (
                  <li
                    key={`${t.at}-${i}`}
                    style={{ display: 'flex', alignItems: 'baseline', gap: 10, padding: '4px 0' }}
                  >
                    <span aria-hidden="true" style={{ fontSize: 9, color: TONE[tv.tone].color, flexShrink: 0 }}>
                      {tv.glyph}
                    </span>
                    <span style={{
                      fontFamily: fontMono, fontSize: 11, letterSpacing: '0.1em',
                      textTransform: 'uppercase', color: TONE[tv.tone].color,
                      minWidth: 74, flexShrink: 0,
                    }}>{tv.label}</span>
                    <span style={{ fontFamily: fontMono, fontSize: 12, color: BB.fade }}>
                      {clockTime(t.at)}
                    </span>
                  </li>
                );
              })}
            </ol>
          )}
          {view.note && (
            <p style={{ fontFamily: fontBody, fontSize: 13.5, color: BB.fade, margin: '10px 0 0', lineHeight: 1.5 }}>
              {view.note}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ─── The live view ───────────────────────────────────────────────────────────
export function ProctorTiles({ examSessionId }) {
  const [tiles, setTiles] = React.useState(null);   // null = first load
  const [missing, setMissing] = React.useState(false);
  const [expanded, setExpanded] = React.useState(null);

  React.useEffect(() => {
    // No session yet (or one was just closed): drop any tiles still on screen
    // rather than leaving the previous sitting's phones showing.
    if (!examSessionId) {
      setTiles(null);
      setMissing(false);
      setExpanded(null);
      return undefined;
    }
    let live = true;

    const poll = () => {
      BB_API.parkStatus(examSessionId).then((res) => {
        if (!live) return;
        // `null` is a transient failure — keep whatever is on screen rather
        // than blanking a proctor's view because one request timed out.
        if (res === null) return;
        setMissing(res.missing);
        setTiles(res.tiles);
      });
    };

    poll();
    const id = setInterval(poll, POLL_MS);
    return () => { live = false; clearInterval(id); };
  }, [examSessionId]);

  const list = tiles || [];
  const idle = !examSessionId;   // nothing open — "Loading…" would be a lie

  return (
    <section aria-label="Parked phones">
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 12 }}>
        <h3 style={{
          fontFamily: fontDisplay, fontSize: 20, color: BB.cream,
          fontWeight: 500, margin: 0, letterSpacing: '0.02em',
        }}>Parked Phones</h3>
        <MetaLabel>
          {idle ? 'Not started'
            : tiles === null ? 'Loading…'
              : `${list.length} phone${list.length === 1 ? '' : 's'}`}
        </MetaLabel>
      </div>
      <GoldRule faint style={{ marginBottom: 16 }} />

      {(idle || (tiles !== null && list.length === 0)) && (
        <div style={{
          border: '1px dashed rgba(201,169,97,0.28)',
          padding: '26px 20px', textAlign: 'center',
        }}>
          <p style={{ fontFamily: fontBody, fontSize: 16, color: BB.fade, margin: 0 }}>
            {idle
              ? 'Start a phone park above to see tiles here.'
              : missing
                ? 'No phone park is open for this examination yet.'
                : 'No phones parked yet — students scan the code to appear here.'}
          </p>
        </div>
      )}

      {list.length > 0 && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(210px, 1fr))',
          gap: 12,
        }}>
          {list.map((tile) => (
            <Tile
              key={tile.student_hint}
              tile={tile}
              expanded={expanded === tile.student_hint}
              onToggle={() => setExpanded(expanded === tile.student_hint ? null : tile.student_hint)}
            />
          ))}
        </div>
      )}

      <p style={{
        fontFamily: fontBody, fontSize: 13.5, color: BB.fade,
        margin: '16px 0 0', lineHeight: 1.55,
      }}>
        A tile shows what a phone reported, nothing more. A phone can go quiet for
        ordinary reasons — a locked screen, a flat battery, poor signal. Treat a
        change as a reason to walk over and have a quiet word, never as a finding.
      </p>
    </section>
  );
}

// ─── QR code ─────────────────────────────────────────────────────────────────
// Encoded in-process (see vendor/qr.js) — never a CDN or an image service,
// which would mean posting the park URL to a third party and would leave an
// offline exam room with a blank square where the code should be.
//
// Rendered dark-on-white regardless of the surrounding theme: scanners expect
// dark modules on a light field, and the quiet zone is part of the symbol.
function QrCode({ value, px = 300 }) {
  const encoded = React.useMemo(() => {
    try {
      return qrEncode(value);
    } catch (e) {
      return null;   // over capacity — the caller shows the URL instead
    }
  }, [value]);

  const d = React.useMemo(() => (encoded ? qrPath(encoded.modules) : ''), [encoded]);
  if (!encoded) return null;

  const quiet = 4;
  const total = encoded.size + quiet * 2;
  return (
    <svg
      width={px} height={px}
      viewBox={`0 0 ${total} ${total}`}
      shapeRendering="crispEdges"
      role="img"
      aria-label="QR code for the phone park page. The same link is printed below."
      style={{ display: 'block' }}
    >
      <rect width={total} height={total} fill="#FFFFFF" />
      <g transform={`translate(${quiet} ${quiet})`} fill="#000000">
        <path d={d} />
      </g>
    </svg>
  );
}

// ─── Proctor screen ──────────────────────────────────────────────────────────
// The professor's own screen during a sitting: the code to project, and the
// tiles to watch. Opening is an explicit click rather than a mount side effect
// — visiting a screen should not create an exam session. Re-opening the same
// id is idempotent server-side (same token for 6h), so a professor who reloads
// mid-exam presses the button again and gets the *same* code back rather than
// stranding every phone already parked on the old one.
export function ProctorScreen() {
  const cfg = (typeof window !== 'undefined' && window.BB_EXAM_CONFIG) || {};
  const [sessionId, setSessionId] = React.useState(() => String(cfg.id || ''));
  const [open, setOpen] = React.useState(null);      // { park_token, qr_url }
  const [openedFor, setOpenedFor] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState('');
  const [closed, setClosed] = React.useState(false);

  const trimmed = sessionId.trim();

  const start = () => {
    if (!trimmed || busy) return;
    setBusy(true); setError(''); setClosed(false);
    BB_API.parkOpen(trimmed)
      .then((res) => { setOpen(res); setOpenedFor(trimmed); })
      .catch((e) => setError(e.message || 'Could not start the phone park.'))
      .then(() => setBusy(false));
  };

  const close = () => {
    if (!openedFor || busy) return;
    setBusy(true); setError('');
    BB_API.parkDelete(openedFor)
      .then(() => {
        // The response counts rows, not phones — so it is never shown.
        setOpen(null); setOpenedFor(''); setClosed(true);
      })
      .catch((e) => setError(e.message || 'Could not close the phone park.'))
      .then(() => setBusy(false));
  };

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '44px 48px', background: BB.deep }}>
      <div>
        <h1 style={{
          fontFamily: fontDisplay, fontSize: 34, color: BB.cream,
          fontWeight: 400, letterSpacing: '0.01em', margin: '0 0 6px',
        }}>Phone Park</h1>
        <MetaLabel>Deterrence and signal — never proof</MetaLabel>
      </div>
      <GoldRule double style={{ margin: '20px 0 32px' }} />

      <p style={{
        fontFamily: fontBody, fontSize: 16, color: BB.fade,
        maxWidth: 620, margin: '0 0 28px', lineHeight: 1.6,
      }}>
        Project the code at the start of the sitting and ask the room to scan it
        with the phone they are putting face-down. Each phone gets a tile below.
        This cannot stop anyone using a phone, and it is not meant to — it makes
        "phones away" a shared, visible ritual and tells you where to look.
      </p>

      {/* ── Session id + start ── */}
      <div style={{
        border: '1px solid rgba(201,169,97,0.2)', background: BB.oxford,
        padding: '20px 24px', maxWidth: 620, marginBottom: 28,
      }}>
        <MetaLabel htmlFor="park-session">Examination session</MetaLabel>
        <div style={{ display: 'flex', gap: 12, marginTop: 10, flexWrap: 'wrap' }}>
          <input
            id="park-session"
            type="text"
            value={sessionId}
            maxLength={128}
            placeholder="e.g. phil301-final"
            onChange={(e) => setSessionId(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); start(); } }}
            style={{
              flex: '1 1 240px', minWidth: 0, padding: '11px 13px',
              fontFamily: fontBody, fontSize: 16, color: BB.cream,
              background: BB.deep, border: '1px solid rgba(201,169,97,0.32)',
            }}
          />
          {open ? (
            <BtnGhost onClick={close} disabled={busy} style={{ padding: '11px 26px', fontSize: 16 }}>
              Close Phone Park
            </BtnGhost>
          ) : (
            <BtnPrimary onClick={start} disabled={busy || !trimmed} style={{ padding: '11px 26px', fontSize: 16 }}>
              Start Phone Park
            </BtnPrimary>
          )}
        </div>
        <p style={{ fontFamily: fontBody, fontSize: 13.5, color: BB.fade, margin: '10px 0 0', lineHeight: 1.5 }}>
          Any label you will recognise later. Reopening the same one during a
          sitting shows the same code, so a reload will not strand parked phones.
        </p>
        {error && (
          <p role="alert" style={{ fontFamily: fontBody, fontSize: 15, color: '#E8A598', margin: '10px 0 0' }}>
            {error}
          </p>
        )}
        {closed && !open && (
          <p role="status" style={{ fontFamily: fontBody, fontSize: 15, color: BB.fade, margin: '10px 0 0' }}>
            Phone park closed. The code no longer works and the beats are deleted.
          </p>
        )}
      </div>

      {/* ── The code itself ── */}
      {open && (
        <div style={{
          border: '1px solid rgba(201,169,97,0.28)', background: BB.oxford,
          padding: '28px 24px', maxWidth: 620, marginBottom: 36, textAlign: 'center',
        }}>
          <MetaLabel style={{ display: 'block', marginBottom: 18 }}>Scan to park a phone</MetaLabel>
          <div style={{ display: 'inline-block', padding: 14, background: '#FFFFFF' }}>
            <QrCode value={open.qr_url} px={300} />
          </div>
          <p style={{
            fontFamily: fontMono, fontSize: 13, color: BB.cream,
            margin: '18px 0 0', wordBreak: 'break-all', lineHeight: 1.5,
          }}>{open.qr_url}</p>
          <p style={{ fontFamily: fontBody, fontSize: 13.5, color: BB.fade, margin: '8px 0 0' }}>
            A phone that cannot scan can type this in instead.
          </p>
        </div>
      )}

      <Ornament py={0} />

      <div style={{ marginTop: 28 }}>
        <ProctorTiles examSessionId={openedFor} />
      </div>
    </div>
  );
}

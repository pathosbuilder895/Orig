// Flagged.jsx — the flagged-submissions queue, wired to the live Original API.
//
// Data source: GET /admin/manifests?limit=300 → { total, items: [ManifestListItem] }
// "Flagged" = items whose action is escalate | schedule_conversation — the same
// definition /admin/health uses for its flagged_count, so the number on this
// page always matches the Dashboard/Sidebar badge.
//
// There is no write endpoint here (escalate/clear/etc.) to call from this
// view yet — the detail pane bridges to the classic review page, where those
// actions are already real, rather than wiring fake buttons.

import { useEffect, useMemo, useState } from 'react';
import { getJSONSafe } from './api.js';
import { Sidebar, Topbar, Icon } from './components.jsx';
import { fmtScore, fmtDate, daysAgo, humanize, shortLabel } from './util.js';

function severity(item) {
  if (item.action === 'escalate' || (item.divergence_score || 0) >= 0.85) return 'high';
  if (item.action === 'schedule_conversation' || (item.divergence_score || 0) >= 0.7) return 'medium';
  return 'watch';
}

export function Flagged() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState('');
  const [actionFilter, setActionFilter] = useState('all');
  const [selectedId, setSelectedId] = useState(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      const manifests = await getJSONSafe('/admin/manifests?limit=300');
      if (!alive) return;
      const all = (manifests && manifests.items) || [];
      const flagged = all.filter((m) => m.action === 'escalate' || m.action === 'schedule_conversation')
        .sort((a, b) => (b.divergence_score || 0) - (a.divergence_score || 0));
      setTotal((manifests && manifests.total) || all.length);
      setItems(flagged);
      setLoading(false);
      if (flagged.length) setSelectedId(flagged[0].submission_id);
    })().catch((e) => { if (alive) { setError(String(e)); setLoading(false); } });
    return () => { alive = false; };
  }, []);

  const visible = useMemo(() => {
    let out = items;
    if (actionFilter !== 'all') out = out.filter((m) => m.action === actionFilter);
    const q = query.trim().toLowerCase();
    if (q) out = out.filter((m) => m.student_id.toLowerCase().includes(q) || (m.submission_id || '').toLowerCase().includes(q));
    return out.slice().sort((a, b) => (b.divergence_score || 0) - (a.divergence_score || 0));
  }, [items, actionFilter, query]);

  const recent = visible.filter((m) => daysAgo(m.created_at) <= 7);
  const earlier = visible.filter((m) => daysAgo(m.created_at) > 7);
  const selected = items.find((m) => m.submission_id === selectedId) || visible[0] || null;

  return (
    <>
      <Sidebar active="flagged" flaggedCount={total ? items.length : undefined} />
      <div className="main">
        <Topbar crumb="Flagged" semester="Live demo" />

        <div className="split-view">
          <div className="list-pane">
            <div className="list-header">
              <div className="list-title-row">
                <div>
                  <div className="list-title">Flagged {loading ? '' : `(${items.length})`}</div>
                  <div className="list-subtitle">
                    {loading ? 'Loading…' : error ? 'Live data unavailable' : 'escalate + schedule-conversation, from /admin/manifests'}
                  </div>
                </div>
                <a className="btn btn-ghost" href="/professor.html"><Icon name="eye" />Classic view</a>
              </div>
            </div>

            <div className="filter-bar">
              {[
                ['all', 'All'], ['escalate', 'Escalate'], ['schedule_conversation', 'Schedule conversation'],
              ].map(([key, label]) => (
                <div key={key} className={'filter-chip' + (actionFilter === key ? ' active' : '') + (key === 'escalate' ? ' red' : '')}
                     onClick={() => setActionFilter(key)}>{label}</div>
              ))}
              <div className="filter-search">
                <Icon name="search" />
                <input placeholder="Search…" value={query} onChange={(e) => setQuery(e.target.value)} />
              </div>
            </div>

            <div className="flag-list">
              {!loading && visible.length === 0 && (
                <div className="detail-empty">
                  <div className="detail-empty-icon"><Icon name="inbox" /></div>
                  <h3>Nothing flagged</h3>
                  <p>No submissions currently need review.</p>
                </div>
              )}

              {recent.length > 0 && <div className="list-section-divider">This week</div>}
              {recent.map((m) => (
                <FlagRow key={m.submission_id} item={m} selected={m.submission_id === selectedId} onClick={() => setSelectedId(m.submission_id)} />
              ))}
              {earlier.length > 0 && <div className="list-section-divider">Earlier</div>}
              {earlier.map((m) => (
                <FlagRow key={m.submission_id} item={m} selected={m.submission_id === selectedId} onClick={() => setSelectedId(m.submission_id)} />
              ))}
            </div>
          </div>

          <div className="detail-pane">
            {!selected && (
              <div className="detail-empty">
                <div className="detail-empty-icon"><Icon name="eye" /></div>
                <h3>Select a submission</h3>
                <p>Choose an item on the left to see its detail.</p>
              </div>
            )}
            {selected && <FlagDetail item={selected} />}
          </div>
        </div>
      </div>
    </>
  );
}

function FlagRow({ item, selected, onClick }) {
  const sev = severity(item);
  return (
    <div className={'flag-list-item' + (selected ? ' selected' : '')} onClick={onClick}>
      <div className="flag-item-row1">
        <span className="flag-student-name" style={{ textTransform: 'capitalize' }}>{shortLabel(item.student_id)}</span>
        <span className={'flag-score-badge ' + sev}>{fmtScore(item.divergence_score)}</span>
      </div>
      <div className="flag-item-row2">
        <span className="flag-assignment">{item.submission_id || 'submission'}</span>
        <span className="flag-course-tag">{item.length_regime}</span>
      </div>
      <div className="flag-item-row3">
        <span className="flag-signals">{(item.flags || []).map(humanize).join(' · ') || 'no flags'}</span>
        <span className="flag-date">{fmtDate(item.created_at)}</span>
      </div>
    </div>
  );
}

function FlagDetail({ item }) {
  const sev = severity(item);
  const pct = Math.round((item.divergence_score || 0) * 100);
  return (
    <div className="detail-content visible">
      <div className="detail-header">
        {sev === 'high' && (
          <div className="detail-alert"><Icon name="alert" /><span>High deviation — recommended for review</span></div>
        )}
        <div className="detail-assignment" style={{ textTransform: 'capitalize' }}>{shortLabel(item.student_id)}</div>
        <div className="detail-meta-row">
          <span className="detail-meta"><Icon name="clock" />{fmtDate(item.created_at)}</span>
          <span className="detail-meta">{item.submission_id}</span>
          <span className="detail-meta" style={{ textTransform: 'capitalize' }}>{humanize(item.action)}</span>
        </div>
      </div>

      <div className="detail-score-row">
        <div>
          <div className="detail-score-num">{fmtScore(item.divergence_score)}</div>
          <div className="detail-score-label">Deviation</div>
        </div>
        <div className="detail-score-bar-wrap">
          <div className="detail-score-bar"><div className="detail-score-fill" style={{ width: `${pct}%` }} /></div>
          <div className="detail-threshold-labels"><span>0 · within baseline</span><span>1 · high deviation</span></div>
        </div>
      </div>

      <div className="detail-section-title">Signals</div>
      <div className="signal-list">
        {(item.flags || []).length === 0 && (
          <div className="signal-item"><span className="signal-name">No specific flags recorded</span></div>
        )}
        {(item.flags || []).map((f) => (
          <div className="signal-item" key={f}>
            <span className="signal-name">{humanize(f)}</span>
            <span className="signal-delta warn">flag</span>
          </div>
        ))}
        {(item.anchor_tiers || []).length > 0 && (
          <div className="signal-item">
            <span className="signal-name">Anchor tiers</span>
            <span className="signal-delta warn">{item.anchor_tiers.join(', ')}</span>
          </div>
        )}
        <div className="signal-item">
          <span className="signal-name">Length regime</span>
          <span className="signal-delta warn">{item.length_regime}</span>
        </div>
      </div>

      <div className="detail-actions">
        <a className="btn btn-review btn-full" href={`student.html?id=${encodeURIComponent(item.student_id)}`}>View student →</a>
        <a className="btn btn-ghost btn-full" href="/professor.html">Open in classic review</a>
      </div>
    </div>
  );
}

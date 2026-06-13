// ════════════════════════════════════════════════════════════════
//  BLUEBOOK — New Examination Screen
//  Create and configure a new examination
// ════════════════════════════════════════════════════════════════
const { useState: useNEState } = React;

const COURSES = [
  { code: 'PHIL 301A', name: 'Ethics in the Modern World' },
  { code: 'POLS 204',  name: 'Foundations of Political Thought' },
  { code: 'PHIL 590',  name: 'Metaphysics and Epistemology' },
  { code: 'LAW 101',   name: 'Constitutional Principles' },
  { code: 'ECON 203',  name: 'History of Economic Thought' },
];

// ─── Form Field Components ────────────────────────────────────────────────────
function FormField({ label, hint, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <MetaLabel>{label}</MetaLabel>
        {hint && <span style={{
          fontFamily: fontBody, fontStyle: 'italic',
          fontSize: 13, color: BB.fade, opacity: 0.7,
        }}>{hint}</span>}
      </div>
      {children}
    </div>
  );
}

const fieldBase = {
  width: '100%', boxSizing: 'border-box',
  background: 'transparent',
  border: 'none',
  borderBottom: '1px solid rgba(201,169,97,0.35)',
  padding: '8px 2px',
  fontFamily: fontBody, fontSize: 17,
  color: BB.cream, outline: 'none',
  letterSpacing: '0.02em',
  transition: 'border-color 0.3s',
};

function TextInput({ value, onChange, placeholder, type = 'text' }) {
  const [focused, setFocused] = useNEState(false);
  return (
    <input
      type={type} value={value} onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      style={{
        ...fieldBase,
        borderBottomColor: focused ? 'rgba(201,169,97,0.75)' : 'rgba(201,169,97,0.35)',
        color: BB.cream,
      }}
    />
  );
}

function SelectInput({ value, onChange, options }) {
  const [focused, setFocused] = useNEState(false);
  return (
    <select
      value={value} onChange={e => onChange(e.target.value)}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      style={{
        ...fieldBase,
        borderBottomColor: focused ? 'rgba(201,169,97,0.75)' : 'rgba(201,169,97,0.35)',
        appearance: 'none',
        cursor: 'pointer',
        background: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23C9A961' opacity='.5'/%3E%3C/svg%3E") right 4px center no-repeat`,
      }}
    >
      {options.map(o => (
        <option key={o.value} value={o.value}
          style={{ background: '#002147', color: '#F0EDE4' }}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

function NumberInput({ value, onChange, placeholder, min = 0 }) {
  const [focused, setFocused] = useNEState(false);
  return (
    <input
      type="number" value={value} min={min}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      style={{
        ...fieldBase,
        borderBottomColor: focused ? 'rgba(201,169,97,0.75)' : 'rgba(201,169,97,0.35)',
        width: '100%',
        MozAppearance: 'textfield',
      }}
    />
  );
}

function ToggleRow({ label, desc, value, onChange }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '13px 0',
    }}>
      <div>
        <p style={{ fontFamily: fontBody, fontSize: 16, color: BB.cream, margin: '0 0 2px' }}>
          {label}
        </p>
        {desc && <p style={{ fontFamily: fontBody, fontStyle: 'italic', fontSize: 14, color: BB.fade, margin: 0 }}>
          {desc}
        </p>}
      </div>
      <button
        onClick={() => onChange(!value)}
        style={{
          width: 44, height: 24, borderRadius: 12, border: 'none',
          background: value ? BB.gold : 'rgba(139,155,180,0.2)',
          position: 'relative', cursor: 'pointer', flexShrink: 0,
          transition: 'background 0.3s',
        }}
      >
        <span style={{
          position: 'absolute', top: 3,
          left: value ? 23 : 3,
          width: 18, height: 18, borderRadius: '50%',
          background: value ? BB.deep : BB.fade,
          transition: 'left 0.25s, background 0.3s',
        }} />
      </button>
    </div>
  );
}

// ─── New Exam Screen ──────────────────────────────────────────────────────────
function NewExamScreen({ onNavigate }) {
  const [title,     setTitle]     = useNEState('');
  const [course,    setCourse]    = useNEState('PHIL 301A');
  const [duration,  setDuration]  = useNEState(90);
  const [minWords,  setMinWords]  = useNEState(600);
  const [maxWords,  setMaxWords]  = useNEState(1200);
  const [prompts,   setPrompts]   = useNEState(['']);
  // ── Lockdown (default ON — the secure baseline) ──
  const [blockAI,    setBlockAI]    = useNEState(true);
  const [blockWeb,   setBlockWeb]   = useNEState(true);
  const [blockCopy,  setBlockCopy]  = useNEState(true);
  // ── Secondary conditions ──
  const [spellChk,  setSpellChk]  = useNEState(false);
  const [phoneBlk,  setPhoneBlk]  = useNEState(true);
  const [aiDetect,  setAiDetect]  = useNEState(true);
  const [saving,    setSaving]    = useNEState(false);
  const [saved,     setSaved]     = useNEState(false);

  const canSubmit = title.trim() && duration && prompts.some(p => p.trim());

  function addPrompt() {
    setPrompts(ps => [...ps, '']);
  }

  function updatePrompt(i, val) {
    setPrompts(ps => ps.map((p, idx) => idx === i ? val : p));
  }

  function removePrompt(i) {
    setPrompts(ps => ps.filter((_, idx) => idx !== i));
  }

  async function handleSave(publish = false) {
    if (!canSubmit || saving) return;
    const conditions = { blockAI, blockWeb, blockCopy, spellChk, phoneBlk, aiDetect };
    // Keep the live config so taking the exam immediately reflects these settings.
    window.BB_EXAM_CONFIG = {
      title:    title.trim(),
      course,
      courseTitle: course,
      duration: Number(duration) || 90,
      minWords: Number(minWords) || 0,
      maxWords: Number(maxWords) || 0,
      prompt:   prompts.find(p => p.trim()) || '',
      ...conditions,
    };
    setSaving(true);
    // Persist to Original (tenant-scoped). Demo still works if the call fails.
    try {
      const created = await BB_API.createExam({
        title:    title.trim(),
        course,
        duration: Number(duration) || 90,
        minWords: Number(minWords) || 0,
        maxWords: Number(maxWords) || 0,
        prompt:   prompts.find(p => p.trim()) || '',
        conditions,
        status:   publish ? 'ACTIVE' : 'DRAFT',
      });
      if (created && created.id) window.BB_EXAM_CONFIG.id = created.id;
    } catch (e) {
      // Non-fatal in demo; the exam is still usable from the live config above.
      console.warn('Bluebook exam persistence failed:', e && e.message);
    }
    setSaving(false);
    setSaved(true);
    setTimeout(() => onNavigate('exams'), 900);
  }

  if (saved) return (
    <div className="bb-screen" style={{
      minHeight: '100vh', background: BB.oxford,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div style={{ textAlign: 'center' }}>
        <Seal size={48} verified glow />
        <p style={{
          fontFamily: fontDisplay, fontSize: 28, color: BB.cream,
          margin: '20px 0 8px', fontWeight: 400,
        }}>Examination Created</p>
        <p style={{ fontFamily: fontBody, fontStyle: 'italic', fontSize: 17, color: BB.fade }}>
          Returning to examinations…
        </p>
      </div>
    </div>
  );

  return (
    <div className="bb-screen" style={{
      minHeight: '100vh', background: BB.deep,
      fontFamily: fontBody,
    }}>
      {/* Top bar */}
      <div style={{
        position: 'sticky', top: 0, zIndex: 10,
        background: BB.oxford,
        padding: '14px 48px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        borderBottom: '1px solid rgba(201,169,97,0.25)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 28 }}>
          <button onClick={() => onNavigate('exams')} style={{
            fontFamily: fontMono, fontSize: 10, letterSpacing: '0.18em',
            textTransform: 'uppercase', color: BB.fade,
            background: 'none', border: 'none', cursor: 'pointer',
            transition: 'color 0.25s',
          }}
            onMouseEnter={e => e.currentTarget.style.color = BB.gold}
            onMouseLeave={e => e.currentTarget.style.color = BB.fade}
          >← Examinations</button>
          <GoldRule style={{ width: 1, height: 16, borderTop: 'none', borderLeft: '1px solid rgba(201,169,97,0.3)' }} />
          <p style={{ fontFamily: fontBody, fontVariant: 'small-caps', fontSize: 16, color: BB.fade, letterSpacing: '0.1em', margin: 0 }}>
            New Examination
          </p>
        </div>
        <Logotype size={18} onClick={() => onNavigate('dashboard')} />
      </div>

      {/* Form */}
      <div style={{ maxWidth: 680, margin: '0 auto', padding: '48px 24px 80px' }}>

        {/* Title */}
        <h1 style={{
          fontFamily: fontDisplay, fontSize: 32, fontWeight: 400,
          color: BB.cream, letterSpacing: '0.01em',
          margin: '0 0 4px',
        }}>New Examination</h1>
        <p style={{ fontFamily: fontBody, fontStyle: 'italic', fontSize: 17, color: BB.fade, margin: '0 0 36px' }}>
          Dr. Sarah Chen · Balliol College
        </p>

        <GoldRule double style={{ marginBottom: 40 }} />

        {/* ── Section I: Identity ── */}
        <div style={{ marginBottom: 40 }}>
          <MetaLabel style={{ display: 'block', marginBottom: 20 }}>I. Identity</MetaLabel>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
            <FormField label="Examination Title">
              <TextInput
                value={title} onChange={setTitle}
                placeholder="e.g. Ethics in the Modern World — Final Examination"
              />
            </FormField>
            <FormField label="Course">
              <SelectInput
                value={course} onChange={setCourse}
                options={COURSES.map(c => ({ value: c.code, label: `${c.code} · ${c.name}` }))}
              />
            </FormField>
          </div>
        </div>

        <GoldRule faint style={{ marginBottom: 36 }} />

        {/* ── Section II: Constraints ── */}
        <div style={{ marginBottom: 40 }}>
          <MetaLabel style={{ display: 'block', marginBottom: 20 }}>II. Time & Length</MetaLabel>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 28 }}>
            <FormField label="Duration" hint="minutes">
              <NumberInput value={duration} onChange={setDuration} placeholder="90" min={10} />
            </FormField>
            <FormField label="Minimum Words" hint="optional">
              <NumberInput value={minWords} onChange={setMinWords} placeholder="600" />
            </FormField>
            <FormField label="Maximum Words" hint="optional">
              <NumberInput value={maxWords} onChange={setMaxWords} placeholder="1200" />
            </FormField>
          </div>
        </div>

        <GoldRule faint style={{ marginBottom: 36 }} />

        {/* ── Section III: Prompts ── */}
        <div style={{ marginBottom: 40 }}>
          <MetaLabel style={{ display: 'block', marginBottom: 20 }}>III. Examination Prompts</MetaLabel>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
            {prompts.map((prompt, i) => (
              <div key={i}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 7 }}>
                  <MetaLabel>Question {['I','II','III','IV','V'][i] || i + 1}</MetaLabel>
                  {prompts.length > 1 && (
                    <button onClick={() => removePrompt(i)} style={{
                      fontFamily: fontMono, fontSize: 9, letterSpacing: '0.15em',
                      textTransform: 'uppercase', color: 'rgba(196,122,107,0.7)',
                      background: 'none', border: 'none', cursor: 'pointer',
                    }}>Remove</button>
                  )}
                </div>
                <textarea
                  value={prompt}
                  onChange={e => updatePrompt(i, e.target.value)}
                  placeholder="Write the examination question here…"
                  rows={4}
                  style={{
                    ...fieldBase,
                    borderBottom: 'none',
                    border: '1px solid rgba(201,169,97,0.28)',
                    padding: '14px 16px',
                    resize: 'vertical',
                    lineHeight: 1.65,
                    minHeight: 100,
                  }}
                />
              </div>
            ))}
            {prompts.length < 5 && (
              <button onClick={addPrompt} style={{
                fontFamily: fontBody, fontStyle: 'italic', fontSize: 15,
                color: BB.gold, background: 'none', border: 'none',
                cursor: 'pointer', textAlign: 'left', padding: '4px 0',
                letterSpacing: '0.02em',
                opacity: 0.75, transition: 'opacity 0.25s',
              }}
                onMouseEnter={e => e.currentTarget.style.opacity = 1}
                onMouseLeave={e => e.currentTarget.style.opacity = 0.75}
              >+ Add another question</button>
            )}
          </div>
        </div>

        <GoldRule faint style={{ marginBottom: 36 }} />

        {/* ── Section IV: Lockdown ── */}
        <div style={{ marginBottom: 40 }}>
          <MetaLabel style={{ display: 'block', marginBottom: 8 }}>IV. Secure Lockdown</MetaLabel>
          <p style={{ fontFamily: fontBody, fontStyle: 'italic', fontSize: 15, color: BB.fade, margin: '0 0 16px' }}>
            The secure baseline. Enabled conditions are enforced for the duration of the examination
            and disclosed to candidates before they begin.
          </p>
          <div style={{ border: '1px solid rgba(201,169,97,0.28)', padding: '4px 20px', background: BB.oxford }}>
            <ToggleRow label="Block AI assistants"      desc="Prevent access to AI writing tools and assistants" value={blockAI}  onChange={setBlockAI} />
            <GoldRule faint />
            <ToggleRow label="Block web & external tabs" desc="Lock the browser; no navigation away from the exam" value={blockWeb} onChange={setBlockWeb} />
            <GoldRule faint />
            <ToggleRow label="Block copy & paste"        desc="Disable clipboard input and output entirely" value={blockCopy} onChange={setBlockCopy} />
          </div>
        </div>

        <GoldRule faint style={{ marginBottom: 36 }} />

        {/* ── Section V: Additional conditions ── */}
        <div style={{ marginBottom: 48 }}>
          <MetaLabel style={{ display: 'block', marginBottom: 8 }}>V. Additional Conditions</MetaLabel>
          <div>
            <GoldRule faint />
            <ToggleRow label="Allow spell check"    desc="Browser spell-check is permitted" value={spellChk}  onChange={setSpellChk} />
            <GoldRule faint />
            <ToggleRow label="Phone blocker"        desc="Prompt students to silence devices" value={phoneBlk} onChange={setPhoneBlk} />
            <GoldRule faint />
            <ToggleRow label="AI detection (Original)" desc="Run post-submission authenticity analysis" value={aiDetect} onChange={setAiDetect} />
            <GoldRule faint />
          </div>
        </div>

        {/* ── Submit ── */}
        <GoldRule double style={{ marginBottom: 28 }} />
        <div style={{ display: 'flex', gap: 14, justifyContent: 'flex-end' }}>
          <BtnGhost onClick={() => handleSave(false)} disabled={!canSubmit || saving} style={{ padding: '11px 32px' }}>
            {saving ? 'Saving…' : 'Save as Draft'}
          </BtnGhost>
          <BtnPrimary onClick={() => handleSave(true)} disabled={!canSubmit || saving} style={{ padding: '11px 36px' }}>
            {saving ? 'Creating…' : 'Publish Examination'}
          </BtnPrimary>
        </div>
        {!canSubmit && (
          <p style={{
            textAlign: 'right', marginTop: 10,
            fontFamily: fontMono, fontSize: 10, letterSpacing: '0.14em',
            color: 'rgba(139,155,180,0.4)', textTransform: 'uppercase',
          }}>Title and at least one prompt are required</p>
        )}
      </div>
    </div>
  );
}

Object.assign(window, { NewExamScreen });

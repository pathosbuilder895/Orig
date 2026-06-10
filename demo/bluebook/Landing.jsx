// ════════════════════════════════════════════════════════════════
//  BLUEBOOK — Landing & Login Screens
// ════════════════════════════════════════════════════════════════
const { useState: useLState } = React;

// ─── Landing Screen ──────────────────────────────────────────────────────────
function LandingScreen({ onNavigate }) {
  return (
    <div className="bb-screen" style={{
      minHeight: '100vh', background: BB.oxford,
      display: 'flex', flexDirection: 'column',
      fontFamily: fontBody, color: BB.cream,
    }}>
      {/* Nav */}
      <nav style={{
        position: 'fixed', top: 0, left: 0, right: 0, zIndex: 50,
        padding: '20px 48px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        background: BB.oxford,
        borderBottom: '1px solid rgba(201,169,97,0.14)',
      }}>
        <Logotype size={22} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 36 }}>
          <button onClick={() => onNavigate('login')} style={{
            fontFamily: fontBody, fontSize: 16, color: BB.fade,
            background: 'none', border: 'none', cursor: 'pointer',
            letterSpacing: '0.03em', transition: 'color 0.3s',
          }}>Sign in</button>
          <button onClick={() => onNavigate('login')} style={{
            fontFamily: fontBody, fontVariant: 'small-caps',
            letterSpacing: '0.12em', fontSize: 16,
            color: BB.gold, background: 'none', border: 'none',
            borderBottom: '1px solid rgba(201,169,97,0.45)',
            paddingBottom: 2, cursor: 'pointer',
          }}>Begin →</button>
        </div>
      </nav>

      {/* Hero — bottom-anchored, title-page spirit */}
      <section style={{
        flex: 1, display: 'flex', flexDirection: 'column',
        justifyContent: 'flex-end', minHeight: '100vh',
        padding: '120px 48px 48px', position: 'relative',
      }}>
        <div style={{ position: 'absolute', top: 80, left: 48, display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 6, height: 6, borderRadius: '50%', background: BB.gold }} />
          <MetaLabel>Academic Integrity Platform · Est. MMXXIV</MetaLabel>
        </div>
        <MetaLabel style={{ position: 'absolute', top: 80, right: 48 }}>01 / 04</MetaLabel>

        <div style={{ marginBottom: 48 }}>
          <h1 style={{
            fontFamily: fontDisplay, fontWeight: 300, fontStyle: 'normal',
            fontSize: 'clamp(3rem, 8vw, 7rem)', lineHeight: 0.9,
            color: BB.cream, letterSpacing: '-0.01em', margin: 0,
          }}>Academic integrity,</h1>
          <h1 style={{
            fontFamily: fontDisplay, fontWeight: 300, fontStyle: 'italic',
            fontSize: 'clamp(3rem, 8vw, 7rem)', lineHeight: 0.9,
            color: BB.gold, letterSpacing: '-0.01em', margin: 0,
          }}>examined.</h1>
        </div>

        <GoldRule />
        <div style={{
          paddingTop: 28, display: 'flex',
          justifyContent: 'space-between', alignItems: 'flex-end',
          gap: 32, flexWrap: 'wrap',
        }}>
          <p style={{
            fontFamily: fontBody, fontSize: 17, color: BB.fade,
            lineHeight: 1.65, maxWidth: 380, margin: 0,
          }}>
            The digital counterpart to the traditional examination notebook —
            built for institutions that treat authenticity as an obligation,
            not a product feature.
          </p>
          <div style={{ display: 'flex', gap: 14, flexShrink: 0 }}>
            <BtnGhost onClick={() => onNavigate('login')} style={{ padding: '10px 28px', fontSize: 16 }}>
              Sign in
            </BtnGhost>
            <BtnPrimary onClick={() => onNavigate('login')} style={{ padding: '10px 28px', fontSize: 16 }}>
              Begin free trial
            </BtnPrimary>
          </div>
        </div>
      </section>

      {/* Features — table of contents */}
      <section style={{ borderTop: '1px solid rgba(201,169,97,0.2)', padding: '0 48px' }}>
        <div style={{ maxWidth: 860, margin: '0 auto' }}>
          <div style={{
            padding: '28px 0 10px', display: 'flex',
            justifyContent: 'space-between', alignItems: 'baseline',
          }}>
            <MetaLabel>Contents</MetaLabel>
            <MetaLabel>Section</MetaLabel>
          </div>
          <GoldRule faint />
          {[
            { num: 'I',   title: 'Lockdown Mode',      desc: 'Secure browser environment' },
            { num: 'II',  title: 'Keystroke Dynamics',  desc: 'Behavioural fingerprinting' },
            { num: 'III', title: 'AI Detection',        desc: 'Integrated with Original' },
            { num: 'IV',  title: 'Proctor Dashboard',   desc: 'Live supervision & alerts' },
          ].map(({ num, title, desc }) => (
            <div key={num}>
              <div style={{ padding: '16px 0', display: 'flex', alignItems: 'baseline', gap: 20 }}>
                <span style={{
                  fontFamily: fontMono, fontSize: 10,
                  color: BB.fade, letterSpacing: '0.18em',
                  width: 28, flexShrink: 0,
                }}>{num}</span>
                <span style={{
                  fontFamily: fontDisplay, fontSize: 22,
                  color: BB.cream, fontWeight: 500,
                  letterSpacing: '0.02em', flex: 1,
                }}>{title}</span>
                <span style={{
                  fontFamily: fontBody, fontSize: 15, fontStyle: 'italic',
                  color: BB.fade, letterSpacing: '0.03em', flexShrink: 0,
                }}>{desc}</span>
              </div>
              <GoldRule faint />
            </div>
          ))}
          <div style={{ padding: '28px 0 36px', display: 'flex', justifyContent: 'center' }}>
            <Seal size={26} verified />
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer style={{
        borderTop: '1px solid rgba(201,169,97,0.18)',
        padding: '18px 48px',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      }}>
        <Logotype size={17} />
        <MetaLabel>© MMXXVI · All rights reserved</MetaLabel>
        <div style={{ display: 'flex', gap: 28 }}>
          {['Sign in', 'Register', 'About'].map(l => (
            <button key={l} onClick={() => onNavigate('login')} style={{
              fontFamily: fontMono, fontSize: 10, letterSpacing: '0.18em',
              textTransform: 'uppercase', color: BB.fade,
              background: 'none', border: 'none', cursor: 'pointer',
            }}>{l}</button>
          ))}
        </div>
      </footer>
    </div>
  );
}

// ─── Login Screen ─────────────────────────────────────────────────────────────
function LoginScreen({ onNavigate }) {
  const [email,   setEmail]   = useLState('');
  const [pass,    setPass]    = useLState('');
  const [loading, setLoading] = useLState(false);
  const [error,   setError]   = useLState('');

  async function handleSubmit(e) {
    e.preventDefault();
    if (loading) return;
    setError('');
    setLoading(true);
    try {
      await BB_API.login(email, pass);
      onNavigate('dashboard');
    } catch (err) {
      setError(err && err.message ? err.message : 'Sign-in failed');
      setLoading(false);
    }
  }

  const inputStyle = {
    width: '100%', boxSizing: 'border-box',
    background: 'rgba(0,0,0,0.25)',
    border: '1px solid rgba(201,169,97,0.18)',
    borderBottom: '1px solid rgba(201,169,97,0.5)',
    padding: '10px 14px',
    fontFamily: fontBody, fontSize: 17,
    color: BB.cream, outline: 'none',
    letterSpacing: '0.03em',
    transition: 'border-color 0.3s',
  };

  return (
    <div className="bb-screen" style={{
      minHeight: '100vh', background: BB.oxford,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: 24,
    }}>
      <button onClick={() => onNavigate('landing')} style={{
        position: 'fixed', top: 28, left: 48,
        fontFamily: fontMono, fontSize: 10, letterSpacing: '0.18em',
        textTransform: 'uppercase', color: BB.fade,
        background: 'none', border: 'none', cursor: 'pointer',
      }}>← Return</button>

      <div style={{ width: '100%', maxWidth: 400 }}>
        <div style={{ textAlign: 'center', marginBottom: 36 }}>
          <Logotype size={28} onClick={() => onNavigate('landing')} />
          <GoldRule double style={{ margin: '18px 0 14px' }} />
          <p style={{
            fontFamily: fontDisplay, fontStyle: 'italic',
            fontSize: 19, color: BB.fade, letterSpacing: '0.04em', margin: 0,
          }}>Verification of Identity</p>
        </div>

        <div style={{ border: '1px solid rgba(201,169,97,0.28)', padding: '32px 36px' }}>
          <form onSubmit={handleSubmit}>
            <div style={{ marginBottom: 22 }}>
              <MetaLabel style={{ display: 'block', marginBottom: 8 }}>
                Electronic Address
              </MetaLabel>
              <input
                type="email" value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="you@institution.edu"
                style={inputStyle}
                required
              />
            </div>
            <div style={{ marginBottom: 30 }}>
              <MetaLabel style={{ display: 'block', marginBottom: 8 }}>
                Passphrase
              </MetaLabel>
              <input
                type="password" value={pass}
                onChange={e => setPass(e.target.value)}
                placeholder="••••••••••"
                style={{ ...inputStyle, letterSpacing: '0.12em' }}
              />
            </div>
            {error && (
              <p style={{
                fontFamily: fontBody, fontStyle: 'italic', fontSize: 14,
                color: '#C47A6B', textAlign: 'center', letterSpacing: '0.02em',
                margin: '0 0 14px',
              }}>{error}</p>
            )}
            <BtnPrimary full style={{ padding: '14px 0', fontSize: 17 }}>
              {loading ? 'Verifying…' : 'Enter'}
            </BtnPrimary>
          </form>

          <Ornament char="·" py={18} />

          <p style={{
            textAlign: 'center', fontFamily: fontBody, fontSize: 16,
            color: BB.fade, letterSpacing: '0.02em', margin: '0 0 14px',
          }}>
            Not yet registered?{' '}
            <button style={{
              fontFamily: fontBody, fontSize: 16, color: BB.gold,
              background: 'none', border: 'none', cursor: 'pointer',
              textDecoration: 'underline', letterSpacing: '0.02em',
            }}>Apply for access</button>
          </p>
          <div style={{ textAlign: 'center' }}>
            <button onClick={() => onNavigate('dashboard')} style={{
              fontFamily: fontMono, fontSize: 10, letterSpacing: '0.18em',
              textTransform: 'uppercase', color: 'rgba(139,155,180,0.6)',
              background: 'none', border: 'none', cursor: 'pointer',
            }}>Explore the demo →</button>
          </div>
        </div>

        <p style={{
          textAlign: 'center', marginTop: 20,
          fontFamily: fontMono, fontSize: 10, letterSpacing: '0.18em',
          color: 'rgba(139,155,180,0.45)', textTransform: 'uppercase',
        }}>Secure · Encrypted · Monitored</p>
      </div>
    </div>
  );
}

Object.assign(window, { LandingScreen, LoginScreen });

import { FormEvent, useState } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export function Login() {
  const { user, signIn, loading } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!loading && user) {
    return <Navigate to="/" replace />;
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      await signIn(email.trim(), password);
    } catch {
      setErr("Invalid email or password.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4 bg-gradient-to-b from-paper-100 to-paper-50">
      <div className="w-full max-w-[400px]">
        <div className="text-center mb-10">
          <p className="font-serif text-3xl sm:text-4xl font-semibold text-ink-900 tracking-tight">
            Original
          </p>
          <p className="mt-2 text-sm text-ink-700/80">
            Stylometric authorship analysis for academic integrity
          </p>
        </div>

        <div className="bg-white rounded-2xl shadow-card border border-paper-200 p-8">
          <h1 className="font-semibold text-lg text-ink-900 mb-6">Sign in</h1>
          <form onSubmit={onSubmit} className="space-y-5">
            <div>
              <label htmlFor="email" className="block text-xs font-medium text-ink-700 uppercase tracking-wide mb-1.5">
                Email
              </label>
              <input
                id="email"
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="w-full rounded-lg border border-paper-200 px-3 py-2.5 text-ink-900 placeholder:text-ink-700/40 focus:border-accent bg-paper-50/50"
                placeholder="you@institution.edu"
              />
            </div>
            <div>
              <label htmlFor="password" className="block text-xs font-medium text-ink-700 uppercase tracking-wide mb-1.5">
                Password
              </label>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="w-full rounded-lg border border-paper-200 px-3 py-2.5 text-ink-900 focus:border-accent bg-paper-50/50"
              />
            </div>
            {err && (
              <p className="text-sm text-red-700 bg-red-50 border border-red-100 rounded-lg px-3 py-2" role="alert">
                {err}
              </p>
            )}
            <button
              type="submit"
              disabled={busy}
              className="w-full rounded-lg bg-accent text-accent-fg font-medium py-2.5 shadow-sm hover:bg-ink-800 transition-colors disabled:opacity-60"
            >
              {busy ? "Signing in…" : "Continue"}
            </button>
          </form>
        </div>

        <p className="text-center text-xs text-ink-700/60 mt-8 max-w-sm mx-auto leading-relaxed">
          Use an instructor or admin account from your Original deployment. Create one with{" "}
          <code className="text-ink-800 bg-paper-100 px-1 rounded">create-admin</code> if needed.
        </p>
      </div>
    </div>
  );
}

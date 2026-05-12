import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export function Dashboard() {
  const { user } = useAuth();

  return (
    <div className="max-w-3xl">
      <h1 className="font-serif text-3xl font-semibold text-ink-900 tracking-tight">
        Welcome back{user?.full_name ? `, ${user.full_name.split(" ")[0]}` : ""}
      </h1>
      <p className="mt-2 text-ink-700/85 leading-relaxed">
        Review students, inspect writing-state signals, and score new submissions against each learner&apos;s
        authenticated baseline.
      </p>

      <div className="mt-10 grid gap-4 sm:grid-cols-2">
        <Link
          to="/students"
          className="group rounded-2xl border border-paper-200 bg-white p-6 shadow-card hover:shadow-lift hover:border-accent/25 transition-all"
        >
          <h2 className="font-semibold text-ink-900 group-hover:text-accent">Students</h2>
          <p className="mt-2 text-sm text-ink-700/80 leading-relaxed">
            Browse your roster, open profiles, and run authorship scoring.
          </p>
          <span className="mt-4 inline-flex items-center text-sm font-medium text-accent">
            Open
            <span className="ml-1 transition-transform group-hover:translate-x-0.5" aria-hidden>
              →
            </span>
          </span>
        </Link>

        <a
          href="/api/reference"
          target="_blank"
          rel="noreferrer"
          className="group rounded-2xl border border-paper-200 bg-white p-6 shadow-card hover:shadow-lift hover:border-accent/25 transition-all"
        >
          <h2 className="font-semibold text-ink-900 group-hover:text-accent">API reference</h2>
          <p className="mt-2 text-sm text-ink-700/80 leading-relaxed">
            Scalar UI — search, try requests, and browse the full OpenAPI spec.
          </p>
          <span className="mt-4 inline-flex items-center text-sm font-medium text-accent">
            Open Scalar
            <span className="ml-1" aria-hidden>
              ↗
            </span>
          </span>
        </a>
      </div>

      {user && (
        <dl className="mt-12 grid gap-4 sm:grid-cols-2 text-sm border-t border-paper-200 pt-10">
          <div>
            <dt className="text-ink-700/70">Role</dt>
            <dd className="font-medium text-ink-900 capitalize mt-0.5">{user.role}</dd>
          </div>
          <div>
            <dt className="text-ink-700/70">Institution</dt>
            <dd className="font-mono text-xs text-ink-800 mt-0.5 break-all">{user.institution_id}</dd>
          </div>
        </dl>
      )}
    </div>
  );
}

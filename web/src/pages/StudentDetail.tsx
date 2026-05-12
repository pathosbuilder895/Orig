import { FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiFetch, fetchStudentState } from "../api/client";
import type { ScoreResponse, StudentResponse, StudentStateResponse } from "../api/types";

export function StudentDetail() {
  const { id } = useParams<{ id: string }>();
  const [student, setStudent] = useState<StudentResponse | null>(null);
  const [state, setState] = useState<StudentStateResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const [scoreText, setScoreText] = useState("");
  const [assignment, setAssignment] = useState("");
  const [scoreResult, setScoreResult] = useState<ScoreResponse | null>(null);
  const [scoreErr, setScoreErr] = useState<string | null>(null);
  const [scoring, setScoring] = useState(false);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    (async () => {
      try {
        const sRes = await apiFetch(`/api/v1/students/${id}`);
        if (!sRes.ok) throw new Error("Student not found");
        const sJson = (await sRes.json()) as StudentResponse;
        if (!cancelled) setStudent(sJson);
        try {
          const st = await fetchStudentState(id);
          if (!cancelled) setState(st);
        } catch {
          if (!cancelled) setState(null);
        }
      } catch (e) {
        if (!cancelled) setErr(e instanceof Error ? e.message : "Failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  async function onScore(e: FormEvent) {
    e.preventDefault();
    if (!id) return;
    setScoreErr(null);
    setScoreResult(null);
    setScoring(true);
    try {
      const res = await apiFetch(`/api/v1/submissions/${id}/score`, {
        method: "POST",
        body: JSON.stringify({
          text: scoreText,
          assignment: assignment || undefined,
        }),
      });
      const raw = await res.text();
      if (!res.ok) {
        try {
          const j = JSON.parse(raw) as { detail?: string };
          throw new Error(typeof j.detail === "string" ? j.detail : raw);
        } catch {
          throw new Error(raw || res.statusText);
        }
      }
      setScoreResult(JSON.parse(raw) as ScoreResponse);
    } catch (e) {
      setScoreErr(e instanceof Error ? e.message : "Scoring failed");
    } finally {
      setScoring(false);
    }
  }

  if (loading) {
    return <div className="animate-pulse h-40 bg-paper-200 rounded-xl max-w-3xl" />;
  }

  if (err || !student || !id) {
    return (
      <div className="text-red-800 text-sm">
        {err || "Not found"}{" "}
        <Link to="/students" className="text-accent underline ml-2">
          Back to list
        </Link>
      </div>
    );
  }

  return (
    <div className="max-w-3xl space-y-10">
      <div>
        <Link to="/students" className="text-sm text-accent font-medium hover:underline">
          ← Students
        </Link>
        <h1 className="mt-4 font-serif text-3xl font-semibold text-ink-900">{student.full_name}</h1>
        <p className="text-ink-700/80 mt-1">{student.email}</p>
        <p className="text-xs font-mono text-ink-700/60 mt-2">ID {student.id}</p>
      </div>

      {state && (
        <section className="rounded-2xl border border-paper-200 bg-white p-6 shadow-card">
          <h2 className="font-semibold text-ink-900">Writing profile</h2>
          <dl className="mt-4 grid grid-cols-2 sm:grid-cols-3 gap-4 text-sm">
            <div>
              <dt className="text-ink-700/70">Baseline samples</dt>
              <dd className="font-medium text-ink-900 mt-0.5">{state.sample_count}</dd>
            </div>
            <div>
              <dt className="text-ink-700/70">Authenticated</dt>
              <dd className="font-medium text-ink-900 mt-0.5">{state.authenticated_count}</dd>
            </div>
            <div>
              <dt className="text-ink-700/70">State purity</dt>
              <dd className="font-medium text-ink-900 mt-0.5">{state.purity.toFixed(4)}</dd>
            </div>
            <div className="col-span-2">
              <dt className="text-ink-700/70">Trajectory</dt>
              <dd className="font-medium text-ink-900 mt-0.5 capitalize">
                {state.trajectory_direction}{" "}
                <span className="text-ink-700/70 font-normal">
                  ({(state.trajectory_confidence * 100).toFixed(0)}% confidence)
                </span>
              </dd>
            </div>
          </dl>
        </section>
      )}

      <section className="rounded-2xl border border-paper-200 bg-white p-6 shadow-card">
        <h2 className="font-semibold text-ink-900">Score a submission</h2>
        <p className="text-sm text-ink-700/80 mt-2 leading-relaxed">
          Paste at least <strong>50 words</strong> of student writing. Original compares it to this learner&apos;s
          baseline using the full stylometric pipeline.
        </p>
        <form onSubmit={onScore} className="mt-6 space-y-4">
          <div>
            <label className="block text-xs font-medium text-ink-700 uppercase tracking-wide mb-1.5">
              Assignment (optional)
            </label>
            <input
              value={assignment}
              onChange={(e) => setAssignment(e.target.value)}
              className="w-full rounded-lg border border-paper-200 px-3 py-2 text-sm"
              placeholder="e.g. Exegesis paper"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-ink-700 uppercase tracking-wide mb-1.5">
              Submission text
            </label>
            <textarea
              value={scoreText}
              onChange={(e) => setScoreText(e.target.value)}
              rows={12}
              className="w-full rounded-lg border border-paper-200 px-3 py-2 text-sm font-mono leading-relaxed"
              placeholder="Paste essay text here…"
              required
            />
          </div>
          {scoreErr && (
            <p className="text-sm text-red-700 bg-red-50 border border-red-100 rounded-lg px-3 py-2">{scoreErr}</p>
          )}
          <button
            type="submit"
            disabled={scoring}
            className="rounded-lg bg-accent text-accent-fg font-medium px-5 py-2.5 disabled:opacity-60"
          >
            {scoring ? "Scoring…" : "Run analysis"}
          </button>
        </form>

        {scoreResult && (
          <div className="mt-8 pt-8 border-t border-paper-200 space-y-4">
            <h3 className="font-semibold text-ink-900">Result</h3>
            <div className="grid sm:grid-cols-2 gap-3 text-sm">
              <div className="rounded-lg bg-paper-100 px-4 py-3">
                <div className="text-ink-700/70 text-xs uppercase tracking-wide">Deviation</div>
                <div className="text-2xl font-semibold text-ink-900">{scoreResult.deviation_score.toFixed(3)}</div>
              </div>
              <div className="rounded-lg bg-paper-100 px-4 py-3">
                <div className="text-ink-700/70 text-xs uppercase tracking-wide">Authorship probability</div>
                <div className="text-2xl font-semibold text-ink-900">
                  {(scoreResult.authorship_probability * 100).toFixed(1)}%
                </div>
              </div>
            </div>
            <p className="text-sm">
              <span className="font-medium capitalize">{scoreResult.recommended_action.replace(/_/g, " ")}</span>
              <span className="text-ink-700/80"> — {scoreResult.rationale}</span>
            </p>
          </div>
        )}
      </section>
    </div>
  );
}

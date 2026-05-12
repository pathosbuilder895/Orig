import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchStudents } from "../api/client";
import type { StudentResponse } from "../api/types";

export function Students() {
  const [items, setItems] = useState<StudentResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchStudents();
        if (!cancelled) {
          setItems(data.items);
          setTotal(data.total);
        }
      } catch (e) {
        if (!cancelled) setErr(e instanceof Error ? e.message : "Failed to load students");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="animate-pulse space-y-4 max-w-4xl">
        <div className="h-8 bg-paper-200 rounded w-48" />
        <div className="h-24 bg-paper-200 rounded-xl" />
        <div className="h-24 bg-paper-200 rounded-xl" />
      </div>
    );
  }

  if (err) {
    return (
      <div className="max-w-lg rounded-xl border border-red-200 bg-red-50 text-red-900 px-4 py-3 text-sm">
        {err}
      </div>
    );
  }

  return (
    <div className="max-w-4xl">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4 mb-8">
        <div>
          <h1 className="font-serif text-3xl font-semibold text-ink-900">Students</h1>
          <p className="mt-1 text-ink-700/80 text-sm">{total} in your institution</p>
        </div>
      </div>

      {items.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-paper-300 bg-white/60 px-6 py-16 text-center">
          <p className="text-ink-800 font-medium">No students yet</p>
          <p className="mt-2 text-sm text-ink-700/75 max-w-md mx-auto">
            Add learners via the API or your LMS integration. In Swagger, use{" "}
            <code className="text-xs bg-paper-100 px-1 rounded">POST /api/v1/students/</code>.
          </p>
        </div>
      ) : (
        <ul className="space-y-3">
          {items.map((s) => (
            <li key={s.id}>
              <Link
                to={`/students/${s.id}`}
                className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 rounded-xl border border-paper-200 bg-white px-5 py-4 shadow-sm hover:shadow-card hover:border-accent/20 transition-all"
              >
                <div>
                  <span className="font-medium text-ink-900">{s.full_name}</span>
                  <span className="text-ink-700/70 text-sm ml-2">{s.email}</span>
                </div>
                <div className="flex items-center gap-4 text-sm text-ink-700/80">
                  <span>{s.baseline_sample_count} baseline samples</span>
                  <span className="text-accent font-medium">View →</span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

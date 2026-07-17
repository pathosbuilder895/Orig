import { useId } from 'react';
import type { ReactNode } from 'react';
import './Chart.css';

export interface ChartProps {
  /**
   * Required short text alternative for the visualization — becomes the
   * accessible name via `aria-label` on the role="img" wrapper. There is no
   * way to render a `Chart` without one: TypeScript requires this prop, so
   * a chart can never ship silent the way `student.html`'s `#fpSvg`,
   * `#arcSvg`, and `#vocabSpark` did.
   */
  summary: string;
  /**
   * The visual itself (SVG, canvas, whatever). Hidden from the
   * accessibility tree via `aria-hidden` — its meaning is carried by
   * `summary` (and `details`, if given), not by any text nodes inside it,
   * so assistive tech doesn't also try to read raw SVG markup or duplicate
   * the summary.
   *
   * Because of that unconditional `aria-hidden`, children MUST NOT contain
   * focusable/interactive elements — an embedded legend button or tooltip
   * trigger would be an axe `aria-hidden-focus` violation (focusable but
   * invisible to AT). Interactive charts need an API change here first,
   * not a workaround.
   */
  children: ReactNode;
  /**
   * Optional richer fallback for when one line isn't enough — e.g. a
   * `<table>` of the underlying data, or a `<ul>` of value/label pairs.
   * Rendered visually-hidden (not display:none, so it's still in the
   * accessibility tree) and linked to the chart via `aria-describedby`.
   */
  details?: ReactNode;
  className?: string;
}

/**
 * An accessible wrapper for chart/status SVGs (WS-8 R2 primitive, fixes
 * durable W9 — student.html's voice-radar `#fpSvg`/`#arcSvg`/`#vocabSpark`
 * and the professor radar/arc canvases had no text alternative at all).
 * Doesn't render a chart itself — it enforces that whoever does supplies a
 * `summary`, and gives the visual a `role="img"` + `aria-label` so it reads
 * as one accessible unit instead of a pile of unlabeled paths, with an
 * optional linked, visually-hidden `details` fallback for anything a single
 * sentence can't capture. Mirrors the good pattern already established in
 * `demo/_components/metric.js` (`role="img" aria-label="NN percent"`).
 */
export function Chart({ summary, children, details, className }: ChartProps) {
  const detailsId = useId();

  return (
    <div className={['chart-wrapper', className].filter(Boolean).join(' ')}>
      <div
        role="img"
        aria-label={summary}
        aria-describedby={details ? detailsId : undefined}
        className="chart-visual"
      >
        <div aria-hidden="true">{children}</div>
      </div>
      {details ? (
        <div id={detailsId} className="sr-only">
          {details}
        </div>
      ) : null}
    </div>
  );
}

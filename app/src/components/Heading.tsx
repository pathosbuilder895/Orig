import { createContext, useContext } from 'react';
import type { ReactNode } from 'react';
import './Heading.css';

export type HeadingLevel = 2 | 3 | 4 | 5 | 6;

// Tracks how many levels deep the current subtree is in the page outline,
// so a CardTitle can pick the right <h2>..<h6> without its call site having
// to count levels by hand. PageTitle resets this to 2 for its descendants
// (its own <h1> is fixed and separate, outside this context entirely);
// Section increments it by one for whatever it wraps.
//
// Design choice (WS-8 R2, durable W7): a plain `level` prop alone would
// still let every CardTitle guess its own number independently — exactly
// the bug this primitive exists to close (pages that skip from h1 to h3,
// or go h2 -> h2 -> h4 as sections get reordered over time). Deriving the
// level from *composition* (how components are nested) instead means the
// hierarchy stays coherent by construction as pages are edited, without
// anyone having to recount. `level` is kept as an escape hatch for genuine
// one-off exceptions, not as the default way to pick a level.
const HeadingLevelContext = createContext<HeadingLevel>(2);

export interface SectionProps {
  children: ReactNode;
}

/**
 * Marks one more level of nesting in the page outline (WS-8 R2 primitive,
 * pairs with `CardTitle`). Wrap a card/subsection's *content* — not just
 * its title — in `Section` wherever it represents going one level deeper;
 * any `CardTitle` inside renders one heading level below its surrounding
 * context, automatically.
 */
export function Section({ children }: SectionProps) {
  const level = useContext(HeadingLevelContext);
  const nextLevel = Math.min(level + 1, 6) as HeadingLevel;
  return <HeadingLevelContext.Provider value={nextLevel}>{children}</HeadingLevelContext.Provider>;
}

export interface PageTitleProps {
  children: ReactNode;
  className?: string;
}

/**
 * The page's single <h1> (WS-8 R2 primitive, fixes durable W7 — the durable
 * replacement for pages like student.html that had zero real headings).
 * Always renders h1 regardless of ambient nesting — a page has exactly
 * one — and resets the ambient level to 2 for anything nested inside it, so
 * the first `CardTitle` after a `PageTitle` is an h2 without either
 * component needing to know about the other.
 */
export function PageTitle({ children, className }: PageTitleProps) {
  return (
    <HeadingLevelContext.Provider value={2}>
      <h1 className={['page-title', className].filter(Boolean).join(' ')}>{children}</h1>
    </HeadingLevelContext.Provider>
  );
}

export interface CardTitleProps {
  children: ReactNode;
  className?: string;
  /**
   * Escape hatch: force a specific heading level instead of the ambient
   * one from context. Prefer wrapping nested content in `<Section>` over
   * reaching for this — it exists for genuine one-off exceptions, not as
   * the default way to pick a level.
   */
  level?: HeadingLevel;
}

/**
 * A section/card heading (WS-8 R2 primitive, fixes durable W7 — e.g.
 * professor.html's first heading being an h3 followed later by an h2).
 * Renders at the ambient level tracked by context — h2 by default, one
 * level deeper inside each `<Section>` — rather than each call site
 * guessing its own level independently.
 */
export function CardTitle({ children, className, level }: CardTitleProps) {
  const contextLevel = useContext(HeadingLevelContext);
  const resolvedLevel = level ?? contextLevel;
  const Tag = `h${resolvedLevel}` as `h${HeadingLevel}`;
  return <Tag className={['card-title', className].filter(Boolean).join(' ')}>{children}</Tag>;
}

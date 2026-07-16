import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { LiveRegion } from './LiveRegion';
import './Timer.css';

export type TimerMode = 'countdown' | 'elapsed';

export interface TimerProps {
  /** Total duration in seconds. Required for countdown mode — ignored in elapsed mode. */
  durationSeconds?: number;
  /** 'countdown' (default) counts down to zero and fires onExpire; 'elapsed' counts up with no milestones/expiry. */
  mode?: TimerMode;
  /** Pauses the tick without losing progress — e.g. while a modal blocks a timed exam, or for an extended-time accommodation. */
  paused?: boolean;
  /** Called once when a countdown reaches zero. */
  onExpire?: () => void;
  /** Called on every tick with the currently displayed value (remaining seconds for countdown, elapsed seconds for elapsed mode). */
  onTick?: (seconds: number) => void;
  /** Visible label rendered before the clock face, e.g. "Time remaining". */
  label?: ReactNode;
  className?: string;
}

interface Milestone {
  /** Fraction of total duration remaining at which this milestone fires. */
  fraction: number;
  message: (spokenTime: string) => string;
}

// Checkpoints, not a per-second re-announcement: a screen reader user hears
// "half your time remains", not "12:41 remaining… 12:40 remaining… 12:39
// remaining…". Ordered descending so a single sweep of the list below finds
// every checkpoint crossed since the last tick.
const MILESTONES: Milestone[] = [
  { fraction: 0.5, message: (t) => `Half your time remains — ${t} left.` },
  { fraction: 0.25, message: (t) => `A quarter of your time remains — ${t} left.` },
  { fraction: 0.1, message: (t) => `${t} remaining.` },
  { fraction: 0.05, message: (t) => `${t} remaining.` },
  { fraction: 0.01, message: (t) => `${t} remaining — almost out of time.` },
];

function formatClock(totalSeconds: number): string {
  const clamped = Math.max(0, Math.round(totalSeconds));
  const hours = Math.floor(clamped / 3600);
  const minutes = Math.floor((clamped % 3600) / 60);
  const seconds = clamped % 60;
  const minutesText = String(minutes).padStart(2, '0');
  const secondsText = String(seconds).padStart(2, '0');
  return hours > 0 ? `${hours}:${minutesText}:${secondsText}` : `${minutesText}:${secondsText}`;
}

function formatSpoken(totalSeconds: number): string {
  const clamped = Math.max(0, Math.round(totalSeconds));
  const hours = Math.floor(clamped / 3600);
  const minutes = Math.floor((clamped % 3600) / 60);
  const seconds = clamped % 60;
  const parts: string[] = [];
  if (hours > 0) parts.push(`${hours} hour${hours === 1 ? '' : 's'}`);
  if (minutes > 0) parts.push(`${minutes} minute${minutes === 1 ? '' : 's'}`);
  if (hours === 0 && minutes < 5 && seconds > 0) {
    parts.push(`${seconds} second${seconds === 1 ? '' : 's'}`);
  }
  return parts.length > 0 ? parts.join(', ') : 'less than a second';
}

/**
 * A countdown/elapsed-time display (WS-8 R2 primitive, fixes durable W10 —
 * used for Bluebook's timed exams). Ticks once per second internally.
 * Screen-reader users get milestone announcements through a nested
 * LiveRegion at 50/25/10/5/1% of time remaining (plus expiry) rather than
 * a re-announcement every second, which would be unusable — this mirrors
 * the "polite timer milestones" pattern already used in
 * demo/bluebook/Exam.jsx, generalized from two hardcoded checkpoints
 * (5 min / 1 min) to percentage-based ones so it scales to any duration.
 * The visible clock face carries an aria-label with a friendlier spoken
 * reading than raw "MM:SS" digits, but is not itself part of a live region,
 * so it never fires an announcement on its own — only the LiveRegion does.
 * Low-time color and the critical-time pulse are decorative; reduced-motion
 * handling comes from the single global rule in tokens.css (see Modal.tsx's
 * comment for the same convention), not a component-local media query.
 */
export function Timer({
  durationSeconds,
  mode = 'countdown',
  paused = false,
  onExpire,
  onTick,
  label,
  className,
}: TimerProps) {
  const [elapsed, setElapsed] = useState(0);
  const [announcement, setAnnouncement] = useState('');
  const nextMilestoneIndexRef = useRef(0);
  const expiredRef = useRef(false);

  useEffect(() => {
    if (paused) return undefined;
    const id = setInterval(() => {
      setElapsed((previous) => {
        // Once a countdown has fully expired, stop bumping state every
        // second forever — the displayed value is already clamped to 0.
        if (mode === 'countdown' && durationSeconds != null && previous >= durationSeconds) {
          return previous;
        }
        return previous + 1;
      });
    }, 1000);
    return () => clearInterval(id);
  }, [paused, mode, durationSeconds]);

  const remaining =
    mode === 'countdown' && durationSeconds != null
      ? Math.max(durationSeconds - elapsed, 0)
      : null;
  const displaySeconds = mode === 'countdown' ? (remaining ?? 0) : elapsed;

  useEffect(() => {
    onTick?.(displaySeconds);
    // onTick is intentionally excluded: it should fire once per real tick
    // (a displaySeconds change), not once per parent re-render that merely
    // hands in a new function identity for the same value.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [displaySeconds]);

  useEffect(() => {
    if (mode !== 'countdown' || durationSeconds == null || durationSeconds <= 0) return;
    if (remaining === null) return;

    if (remaining <= 0) {
      if (!expiredRef.current) {
        expiredRef.current = true;
        setAnnouncement('Time has expired.');
        onExpire?.();
      }
      return;
    }

    const fraction = remaining / durationSeconds;
    let index = nextMilestoneIndexRef.current;
    let crossed: Milestone | null = null;
    while (index < MILESTONES.length && fraction <= MILESTONES[index].fraction) {
      crossed = MILESTONES[index];
      index += 1;
    }
    if (crossed) {
      nextMilestoneIndexRef.current = index;
      setAnnouncement(crossed.message(formatSpoken(remaining)));
    }
  }, [remaining, durationSeconds, mode, onExpire]);

  const fraction =
    mode === 'countdown' && durationSeconds ? (remaining ?? 0) / durationSeconds : null;
  const isLow = fraction !== null && fraction <= 0.25;
  const isVeryLow = fraction !== null && fraction <= 0.1;
  const spokenValue = `${formatSpoken(displaySeconds)} ${mode === 'countdown' ? 'remaining' : 'elapsed'}`;

  return (
    <div className={['timer', className].filter(Boolean).join(' ')}>
      {label ? <span className="timer-label">{label}</span> : null}
      <span
        className={[
          'timer-face',
          isVeryLow ? 'timer-face--critical' : isLow ? 'timer-face--low' : '',
        ]
          .filter(Boolean)
          .join(' ')}
        aria-label={spokenValue}
      >
        {formatClock(displaySeconds)}
      </span>
      <LiveRegion message={announcement} />
    </div>
  );
}

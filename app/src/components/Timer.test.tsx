import { act, render, screen } from '@testing-library/react';
import { axe } from 'jest-axe';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Timer } from './Timer';

function advance(seconds: number) {
  act(() => {
    vi.advanceTimersByTime(seconds * 1000);
  });
}

describe('Timer', () => {
  // Fake timers are opted into per-test (not via a shared beforeEach) so
  // the axe test below — which doesn't need to advance the clock — runs
  // against real timers. jest-axe's internals rely on real timer
  // resolution and hang forever under fake timers.
  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders the initial countdown value as MM:SS', () => {
    vi.useFakeTimers();
    render(<Timer durationSeconds={600} />);
    expect(screen.getByText('10:00')).toBeInTheDocument();
  });

  it('counts down once per second', () => {
    vi.useFakeTimers();
    render(<Timer durationSeconds={600} />);
    advance(1);
    expect(screen.getByText('09:59')).toBeInTheDocument();
    advance(59);
    expect(screen.getByText('09:00')).toBeInTheDocument();
  });

  it('counts up in elapsed mode instead of down', () => {
    vi.useFakeTimers();
    render(<Timer mode="elapsed" />);
    advance(5);
    expect(screen.getByText('00:05')).toBeInTheDocument();
  });

  it('does not tick while paused', () => {
    vi.useFakeTimers();
    render(<Timer durationSeconds={600} paused />);
    advance(10);
    expect(screen.getByText('10:00')).toBeInTheDocument();
  });

  it('announces the halfway milestone via the live region, once', () => {
    vi.useFakeTimers();
    render(<Timer durationSeconds={100} />);
    advance(49);
    expect(screen.getByRole('status')).toHaveTextContent('');
    advance(1); // 50s remaining of 100 = 50%
    expect(screen.getByRole('status')).toHaveTextContent(/half your time remains/i);
  });

  it('announces the quarter and near-expiry milestones as time runs out', () => {
    vi.useFakeTimers();
    render(<Timer durationSeconds={100} />);
    advance(75); // 25s remaining = 25%
    expect(screen.getByRole('status')).toHaveTextContent(/quarter of your time remains/i);
    advance(24); // 1s remaining = 1%
    expect(screen.getByRole('status')).toHaveTextContent(/almost out of time/i);
  });

  it('does not re-announce a milestone already crossed', () => {
    vi.useFakeTimers();
    render(<Timer durationSeconds={100} />);
    advance(50); // crosses 50%
    advance(1); // still above 25% — no new milestone
    expect(screen.getByRole('status')).toHaveTextContent(/half your time remains/i);
  });

  it('announces expiry and calls onExpire exactly once when the countdown reaches zero', () => {
    vi.useFakeTimers();
    const onExpire = vi.fn();
    render(<Timer durationSeconds={3} onExpire={onExpire} />);
    advance(3);
    expect(screen.getByRole('status')).toHaveTextContent('Time has expired.');
    expect(onExpire).toHaveBeenCalledTimes(1);
    advance(5); // stays expired; no further onExpire calls
    expect(onExpire).toHaveBeenCalledTimes(1);
  });

  it('calls onTick with the current displayed value on every tick', () => {
    vi.useFakeTimers();
    const onTick = vi.fn();
    render(<Timer durationSeconds={10} onTick={onTick} />);
    advance(3);
    expect(onTick).toHaveBeenCalledWith(7);
  });

  it('renders an optional label alongside the clock face', () => {
    render(<Timer durationSeconds={600} label="Time remaining" />);
    expect(screen.getByText('Time remaining')).toBeInTheDocument();
  });

  it('gives the clock face a friendlier spoken accessible name than raw digits', () => {
    render(<Timer durationSeconds={90} />);
    expect(screen.getByLabelText('1 minute, 30 seconds remaining')).toBeInTheDocument();
  });

  it('has zero axe violations', async () => {
    const { container } = render(<Timer durationSeconds={600} label="Time remaining" />);
    expect(await axe(container)).toHaveNoViolations();
  });
});

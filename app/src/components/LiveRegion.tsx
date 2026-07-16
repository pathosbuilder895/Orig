export interface LiveRegionProps {
  /** The text to announce. An empty string announces nothing. */
  message: string;
  /**
   * Assertive announcements (role="alert") interrupt the screen reader
   * immediately — reserve for errors/urgent status. Defaults to polite
   * (role="status"), which waits for the current speech to finish.
   */
  assertive?: boolean;
  className?: string;
}

// Visually-hidden but present in the accessibility tree: the region must
// stay mounted (not display:none) for screen readers to pick up changes to
// its content.
const visuallyHiddenStyle = {
  position: 'absolute',
  width: '1px',
  height: '1px',
  padding: 0,
  margin: '-1px',
  overflow: 'hidden',
  clip: 'rect(0, 0, 0, 0)',
  whiteSpace: 'nowrap',
  border: 0,
} as const;

/**
 * A simple aria-live announcer for screen-reader status messages (WS-8 R2
 * primitive, durable W4). Mount one instance near the root of a page/flow
 * and feed it the latest status message via the `message` prop — e.g. from
 * a toast queue, autosave indicator, or timer milestone. Polite by default;
 * pass `assertive` for errors that should interrupt.
 */
export function LiveRegion({ message, assertive = false, className }: LiveRegionProps) {
  return (
    <div
      role={assertive ? 'alert' : 'status'}
      aria-live={assertive ? 'assertive' : 'polite'}
      aria-atomic="true"
      className={className}
      style={visuallyHiddenStyle}
    >
      {message}
    </div>
  );
}

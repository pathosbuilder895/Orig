import { useEffect, useId, useRef } from 'react';
import { createPortal } from 'react-dom';
import type { KeyboardEvent as ReactKeyboardEvent, ReactNode } from 'react';
import './Modal.css';

// Elements considered part of the modal's tab cycle. Deliberately excludes
// disabled/negative-tabindex elements so the trap only cycles through what a
// keyboard user could actually reach.
const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ');

export interface ModalProps {
  /** Whether the modal is open. Controlled by the consumer. */
  open: boolean;
  /** Called on Escape, or the built-in close button. Consumer sets open=false. */
  onClose: () => void;
  /** Accessible name for the dialog; also rendered as the visible heading. */
  title: ReactNode;
  children: ReactNode;
  className?: string;
}

/**
 * An accessible modal dialog (WS-8 R2 primitive, fixes durable W8): a focus
 * trap while open, Escape-to-close, and focus returned to whatever triggered
 * the modal once it closes. Implemented as a plain element with
 * role="dialog" + aria-modal="true" rather than native <dialog>.showModal()
 * — jsdom (this workspace's test environment) does not implement
 * showModal(), and a manual trap gives precise, uniform control over focus
 * order across browsers. Reduced-motion handling for the open/close
 * transition comes from the single global rule in tokens.css, not a
 * component-local media query. Portaled to document.body so the fixed
 * overlay cannot be captured by an ancestor containing block
 * (transform/filter/contain), with background content made inert while open.
 */
export function Modal({ open, onClose, title, children, className }: ModalProps) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);

  // Make everything behind the dialog inert while it is open — Tab-trapping
  // alone doesn't stop a screen reader's browse/virtual cursor from reading
  // background content (WAI-ARIA APG dialog pattern). Only marks elements
  // this effect itself made inert, so pre-existing inert content (or a
  // second stacked modal) is left alone on cleanup. Declared BEFORE the
  // focus effect: cleanups run in declaration order, so inert is removed
  // before focus is restored to the (no-longer-inert) trigger. Captures
  // the previously-focused element FIRST, before marking anything inert:
  // per the HTML spec, inert can force-blur a focused descendant, so
  // capturing here — rather than in the focus effect below, which runs
  // after this one — is correct regardless of whether that blur happens
  // synchronously.
  useEffect(() => {
    if (!open) return;

    previouslyFocusedRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;

    const overlay = overlayRef.current;
    const madeInert: Element[] = [];
    for (const el of Array.from(document.body.children)) {
      if (el === overlay || el.hasAttribute('inert')) continue;
      el.setAttribute('inert', '');
      madeInert.push(el);
    }
    return () => {
      for (const el of madeInert) el.removeAttribute('inert');
    };
  }, [open]);

  // Move focus into the dialog on open; restore it to the trigger on close.
  // (previouslyFocusedRef is captured by the inert effect above, not here —
  // see that effect's comment.)
  useEffect(() => {
    if (!open) return;

    const panel = panelRef.current;
    const focusable = panel?.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR);
    const target = focusable && focusable.length > 0 ? focusable[0] : panel;
    target?.focus();

    return () => {
      previouslyFocusedRef.current?.focus();
    };
  }, [open]);

  // Escape-to-close, listened on the document so it fires regardless of
  // which element inside the dialog currently has focus.
  useEffect(() => {
    if (!open) return;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
      }
    }

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  function handleTabTrap(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key !== 'Tab') return;
    const panel = panelRef.current;
    if (!panel) return;

    const focusable = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
    if (focusable.length === 0) {
      event.preventDefault();
      return;
    }

    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  if (!open) return null;

  return createPortal(
    <div className="modal-overlay" ref={overlayRef}>
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions --
          role="dialog" is a window role, not a widget role, so jsx-a11y treats it as
          non-interactive — but attaching the Tab-trap keydown handler to the dialog
          container is exactly the WAI-ARIA APG dialog pattern. */}
      <div
        ref={panelRef}
        className={['modal-panel', className].filter(Boolean).join(' ')}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onKeyDown={handleTabTrap}
      >
        <button
          type="button"
          className="modal-close-button"
          aria-label="Close dialog"
          onClick={onClose}
        >
          <span aria-hidden="true">×</span>
        </button>
        <h2 id={titleId} className="modal-title">
          {title}
        </h2>
        {children}
      </div>
    </div>,
    document.body,
  );
}

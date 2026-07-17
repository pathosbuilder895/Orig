import { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { axe } from 'jest-axe';
import { describe, expect, it } from 'vitest';
import { Modal } from './Modal';

function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button type="button" onClick={() => setOpen(true)}>
        Open modal
      </button>
      <Modal open={open} onClose={() => setOpen(false)} title="Confirm action">
        <p>Are you sure?</p>
        <button type="button">First action</button>
        <button type="button">Second action</button>
      </Modal>
    </div>
  );
}

describe('Modal', () => {
  it('is not rendered when closed', () => {
    render(<Harness />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('renders with role=dialog, aria-modal, and an accessible name from the title', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: 'Open modal' }));
    const dialog = screen.getByRole('dialog', { name: 'Confirm action' });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
  });

  it('moves focus into the dialog on open', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: 'Open modal' }));
    const dialog = screen.getByRole('dialog');
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
  });

  it('traps Tab/Shift+Tab focus inside the dialog', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: 'Open modal' }));

    const closeButton = screen.getByRole('button', { name: 'Close dialog' });
    const second = screen.getByRole('button', { name: 'Second action' });

    // Focus starts on the first focusable element (the close button).
    expect(document.activeElement).toBe(closeButton);

    // Shift+Tab from the first element wraps to the last.
    fireEvent.keyDown(closeButton, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(second);

    // Tab from the last element wraps back to the first.
    fireEvent.keyDown(second, { key: 'Tab' });
    expect(document.activeElement).toBe(closeButton);
  });

  it('closes on Escape and returns focus to the trigger', () => {
    render(<Harness />);
    const trigger = screen.getByRole('button', { name: 'Open modal' });
    // jsdom's fireEvent.click does not emulate the browser's default
    // focus-follows-click behavior, so focus explicitly as a real click would.
    trigger.focus();
    fireEvent.click(trigger);
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(document.activeElement).toBe(trigger);
  });

  it('closes via the built-in close button and returns focus to the trigger', () => {
    render(<Harness />);
    const trigger = screen.getByRole('button', { name: 'Open modal' });
    trigger.focus();
    fireEvent.click(trigger);

    fireEvent.click(screen.getByRole('button', { name: 'Close dialog' }));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(document.activeElement).toBe(trigger);
  });

  it('has zero axe violations while open', async () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: 'Open modal' }));
    // The dialog is portaled to document.body, so scan the whole body —
    // scanning only the render container would miss the dialog entirely.
    expect(await axe(document.body)).toHaveNoViolations();
  });

  it('portals to document.body and marks background content inert while open', () => {
    const { rerender } = render(
      <div data-testid="background">
        <button type="button">Background action</button>
        <Modal open onClose={() => {}} title="Portaled">
          <p>Content</p>
        </Modal>
      </div>,
    );
    const dialog = screen.getByRole('dialog');
    // The dialog escapes its React parent via a portal…
    expect(screen.getByTestId('background')).not.toContainElement(dialog);
    // …background content is inert, the dialog is not.
    expect(screen.getByTestId('background').closest('[inert]')).not.toBeNull();
    expect(dialog.closest('[inert]')).toBeNull();

    rerender(
      <div data-testid="background">
        <button type="button">Background action</button>
        <Modal open={false} onClose={() => {}} title="Portaled">
          <p>Content</p>
        </Modal>
      </div>,
    );
    expect(screen.getByTestId('background').closest('[inert]')).toBeNull();
  });
});

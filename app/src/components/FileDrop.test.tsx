import { createEvent, fireEvent, render, screen } from '@testing-library/react';
import { axe } from 'jest-axe';
import { describe, expect, it, vi } from 'vitest';
import { FileDrop } from './FileDrop';

function makeFile(name = 'baselines.csv') {
  return new File(['a,b,c'], name, { type: 'text/csv' });
}

describe('FileDrop', () => {
  it('associates the label with a real file input via htmlFor/id', () => {
    render(<FileDrop label="Drop CSV here" onFiles={() => {}} />);
    const input = screen.getByLabelText('Drop CSV here');
    expect(input).toBeInstanceOf(HTMLInputElement);
    expect(input).toHaveAttribute('type', 'file');
  });

  it('the input is reachable by keyboard (not display:none) and calls onFiles when a file is picked', () => {
    const onFiles = vi.fn();
    render(<FileDrop label="Drop CSV here" onFiles={onFiles} />);
    const input = screen.getByLabelText('Drop CSV here') as HTMLInputElement;

    input.focus();
    expect(document.activeElement).toBe(input);
    expect(input).not.toHaveStyle({ display: 'none' });

    const file = makeFile();
    fireEvent.change(input, { target: { files: [file] } });

    expect(onFiles).toHaveBeenCalledTimes(1);
    expect(onFiles.mock.calls[0][0]).toHaveLength(1);
    expect(onFiles.mock.calls[0][0][0].name).toBe('baselines.csv');
  });

  it('calls onFiles when a file is dropped on the zone', () => {
    const onFiles = vi.fn();
    render(<FileDrop label="Drop CSV here" onFiles={onFiles} />);
    const zone = screen.getByText('Drop CSV here');

    const file = makeFile('dropped.csv');
    fireEvent.drop(zone, { dataTransfer: { files: [file] } });

    expect(onFiles).toHaveBeenCalledTimes(1);
    expect(onFiles.mock.calls[0][0][0].name).toBe('dropped.csv');
  });

  it('does not call onFiles when the file list is empty', () => {
    const onFiles = vi.fn();
    render(<FileDrop label="Drop CSV here" onFiles={onFiles} />);
    const input = screen.getByLabelText('Drop CSV here');
    fireEvent.change(input, { target: { files: [] } });
    expect(onFiles).not.toHaveBeenCalled();
  });

  it('forwards accept and multiple to the underlying input', () => {
    render(<FileDrop label="Drop files" onFiles={() => {}} accept=".csv" multiple />);
    const input = screen.getByLabelText('Drop files');
    expect(input).toHaveAttribute('accept', '.csv');
    expect(input).toHaveAttribute('multiple');
  });

  it('wires help text via aria-describedby', () => {
    render(<FileDrop label="Drop CSV here" onFiles={() => {}} helpText="Up to 10MB" />);
    const input = screen.getByLabelText('Drop CSV here');
    const describedBy = input.getAttribute('aria-describedby');
    expect(describedBy).toBeTruthy();
    expect(screen.getByText('Up to 10MB')).toHaveAttribute('id', describedBy!);
  });

  it('has zero axe violations in the base state', async () => {
    const { container } = render(<FileDrop label="Drop CSV here" onFiles={() => {}} />);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('has zero axe violations with help text', async () => {
    const { container } = render(
      <FileDrop label="Drop CSV here" onFiles={() => {}} helpText="Up to 10MB" />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it('ignores dragleave events bubbling from the hidden input', () => {
    render(<FileDrop label="Upload files" onFiles={() => {}} />);
    const input = screen.getByLabelText('Upload files');
    const zone = input.closest('label')!;

    fireEvent.dragOver(zone);
    expect(zone.className).toContain('file-drop-zone--dragging');

    // Leaving *into a child* of the zone must not clear the dragging state…
    // (jsdom's drag events drop relatedTarget from the init dict, so set it
    // on the built event directly.)
    const leaveToChild = createEvent.dragLeave(zone);
    Object.defineProperty(leaveToChild, 'relatedTarget', { value: input });
    fireEvent(zone, leaveToChild);
    expect(zone.className).toContain('file-drop-zone--dragging');

    // …leaving the zone entirely must.
    const leaveZone = createEvent.dragLeave(zone);
    Object.defineProperty(leaveZone, 'relatedTarget', { value: document.body });
    fireEvent(zone, leaveZone);
    expect(zone.className).not.toContain('file-drop-zone--dragging');
  });
});

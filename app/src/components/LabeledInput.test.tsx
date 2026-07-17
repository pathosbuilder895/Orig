import { createRef } from 'react';
import { render, screen } from '@testing-library/react';
import { axe } from 'jest-axe';
import { describe, expect, it } from 'vitest';
import { LabeledInput } from './LabeledInput';

describe('LabeledInput', () => {
  it('associates the label with the input via htmlFor/id', () => {
    render(<LabeledInput label="Email address" />);
    const input = screen.getByLabelText('Email address');
    expect(input).toBeInstanceOf(HTMLInputElement);
  });

  it('uses an explicit id when provided', () => {
    render(<LabeledInput label="Name" id="student-name" />);
    expect(screen.getByLabelText('Name')).toHaveAttribute('id', 'student-name');
  });

  it('wires help text via aria-describedby', () => {
    render(<LabeledInput label="Course code" helpText="e.g. THEO-301" />);
    const input = screen.getByLabelText('Course code');
    const describedBy = input.getAttribute('aria-describedby');
    expect(describedBy).toBeTruthy();
    expect(screen.getByText('e.g. THEO-301')).toHaveAttribute('id', describedBy!);
  });

  it('wires an error message via aria-describedby, aria-invalid, and role=alert', () => {
    render(<LabeledInput label="Email address" error="Enter a valid email" />);
    const input = screen.getByLabelText('Email address');
    expect(input).toHaveAttribute('aria-invalid', 'true');
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Enter a valid email');
    expect(input.getAttribute('aria-describedby')).toContain(alert.id);
  });

  it('includes both help text and error in aria-describedby when both are present', () => {
    render(
      <LabeledInput label="Email address" helpText="We will never share this" error="Required" />,
    );
    const input = screen.getByLabelText('Email address');
    const describedBy = input.getAttribute('aria-describedby')!.split(' ');
    expect(describedBy).toHaveLength(2);
  });

  it('forwards the ref to the underlying input element', () => {
    const ref = createRef<HTMLInputElement>();
    render(<LabeledInput label="Focus target" ref={ref} />);
    expect(ref.current).toBeInstanceOf(HTMLInputElement);
    ref.current?.focus();
    expect(document.activeElement).toBe(ref.current);
  });

  it('has zero axe violations in the base state', async () => {
    const { container } = render(<LabeledInput label="Email address" />);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('has zero axe violations with help text and an error', async () => {
    const { container } = render(
      <LabeledInput
        label="Email address"
        helpText="We will never share this"
        error="Enter a valid email"
        required
      />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});

import { forwardRef, useId } from 'react';
import type { InputHTMLAttributes, ReactNode } from 'react';
import './LabeledInput.css';

export interface LabeledInputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'id'> {
  /** Visible label text — always rendered as a real <label htmlFor>. */
  label: ReactNode;
  /** Explicit id; auto-generated via useId when omitted. */
  id?: string;
  /** Supplementary help text, wired up via aria-describedby. */
  helpText?: ReactNode;
  /** Validation error; wired up via aria-describedby + aria-invalid, announced via role="alert". */
  error?: ReactNode;
}

/**
 * A text input that is always programmatically associated with its label —
 * no orphaned `<label>`s (WS-8 R2 primitive, fixes durable W5). Supports an
 * error/help-text slot wired to the input via aria-describedby, and forwards
 * its ref to the underlying <input> so consumers can call .focus() etc.
 */
export const LabeledInput = forwardRef<HTMLInputElement, LabeledInputProps>(function LabeledInput(
  { label, id, helpText, error, required, className, ...inputProps },
  ref,
) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const helpId = helpText ? `${inputId}-help` : undefined;
  const errorId = error ? `${inputId}-error` : undefined;
  const describedBy = [helpId, errorId].filter(Boolean).join(' ') || undefined;

  return (
    <div className={['labeled-input', className].filter(Boolean).join(' ')}>
      <label htmlFor={inputId} className="labeled-input-label">
        {label}
        {required ? (
          <span className="labeled-input-required" aria-hidden="true">
            {' '}
            *
          </span>
        ) : null}
      </label>
      <input
        {...inputProps}
        ref={ref}
        id={inputId}
        required={required}
        aria-describedby={describedBy}
        aria-invalid={error ? true : inputProps['aria-invalid']}
        className={['labeled-input-field', error ? 'labeled-input-field--error' : '']
          .filter(Boolean)
          .join(' ')}
      />
      {helpText ? (
        <p id={helpId} className="labeled-input-help">
          {helpText}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className="labeled-input-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
});

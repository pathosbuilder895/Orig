import { useId, useRef, useState } from 'react';
import type { DragEvent, ReactNode } from 'react';
import './FileDrop.css';

export interface FileDropProps {
  /** Accessible name for the file input, and the visible instruction text. */
  label: ReactNode;
  /** Called with the chosen/dropped files, from either the picker or a drop. */
  onFiles: (files: FileList) => void;
  /** Forwarded to the underlying <input type="file"> accept attribute. */
  accept?: string;
  /** Forwarded to the underlying <input type="file"> multiple attribute. */
  multiple?: boolean;
  /** Explicit id; auto-generated via useId when omitted. */
  id?: string;
  /** Supplementary help text below the drop zone. */
  helpText?: ReactNode;
  className?: string;
}

/**
 * A drag-and-drop file target that is also a real, focusable file picker
 * (WS-8 R2 primitive, fixes durable W13). The legacy pattern this replaces
 * — a `<div onclick>` opening a `display:none` file input — is invisible to
 * keyboard/AT users entirely, since a display:none input can never receive
 * focus. Here the `<input type="file">` is visually hidden (clipped, not
 * display:none — see FileDrop.css) but sits directly under the drop zone's
 * `<label>`, so Tab reaches it, Enter/Space opens the native file picker,
 * and it carries the label's text as its accessible name for free via
 * label/for association — no separate aria-label needed.
 */
export function FileDrop({
  label,
  onFiles,
  accept,
  multiple,
  id,
  helpText,
  className,
}: FileDropProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const helpId = helpText ? `${inputId}-help` : undefined;
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);

  function handleDragOver(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setIsDragging(true);
  }

  function handleDragLeave(event: DragEvent<HTMLLabelElement>) {
    // dragleave fires when the pointer moves onto a child (the hidden
    // input); only clear when actually leaving the zone.
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
    setIsDragging(false);
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setIsDragging(false);
    const files = event.dataTransfer.files;
    if (files.length > 0) onFiles(files);
  }

  return (
    <div className={['file-drop-wrap', className].filter(Boolean).join(' ')}>
      <label
        htmlFor={inputId}
        className={['file-drop-zone', isDragging ? 'file-drop-zone--dragging' : '']
          .filter(Boolean)
          .join(' ')}
        onDragOver={handleDragOver}
        onDragEnter={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {label}
        <input
          ref={inputRef}
          type="file"
          id={inputId}
          accept={accept}
          multiple={multiple}
          aria-describedby={helpId}
          className="file-drop-input"
          onChange={(event) => {
            const files = event.target.files;
            if (files && files.length > 0) onFiles(files);
          }}
        />
      </label>
      {helpText ? (
        <p id={helpId} className="file-drop-help">
          {helpText}
        </p>
      ) : null}
    </div>
  );
}

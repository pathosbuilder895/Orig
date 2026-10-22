import React from 'react';
import { qrEncode, qrPath } from './vendor/qr.js';

// ─── QR code ─────────────────────────────────────────────────────────────────
// Encoded in-process (see vendor/qr.js) — never a CDN or an image service,
// which would mean posting the park URL to a third party and would leave an
// offline exam room with a blank square where the code should be.
//
// Rendered dark-on-white regardless of the surrounding theme: scanners expect
// dark modules on a light field, and the quiet zone is part of the symbol.
export function QrCode({ value, px = 300, label = 'QR code for the phone park page. The same link is printed below.' }) {
  const encoded = React.useMemo(() => {
    try {
      return qrEncode(value);
    } catch (e) {
      return null;   // over capacity — the caller shows the URL instead
    }
  }, [value]);

  const d = React.useMemo(() => (encoded ? qrPath(encoded.modules) : ''), [encoded]);
  if (!encoded) return null;

  const quiet = 4;
  const total = encoded.size + quiet * 2;
  return (
    <svg
      width={px} height={px}
      viewBox={`0 0 ${total} ${total}`}
      shapeRendering="crispEdges"
      role="img"
      aria-label={label}
      style={{ display: 'block' }}
    >
      <rect width={total} height={total} fill="#FFFFFF" />
      <g transform={`translate(${quiet} ${quiet})`} fill="#000000">
        <path d={d} />
      </g>
    </svg>
  );
}

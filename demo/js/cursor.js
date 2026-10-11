/* ──────────────────────────────────────────────────────────────────────────
   cursor.js: custom cursor with magnetic snap.
   Adds .cursor-ring and .cursor-dot to body, tracks pointer with damped lag,
   detects "magnetic" elements (a, button, [data-magnetic]) for snap+scale,
   and detects text fields to hide cursor.
   ────────────────────────────────────────────────────────────────────────── */
(function () {
  if (window.matchMedia('(pointer:coarse)').matches) return;

  const ring = document.createElement('div');
  ring.className = 'cursor-ring';
  const dot  = document.createElement('div');
  dot.className = 'cursor-dot';
  document.body.appendChild(ring);
  document.body.appendChild(dot);

  let tx = window.innerWidth / 2, ty = window.innerHeight / 2;
  let rx = tx, ry = ty;          // ring (lags)
  let dx = tx, dy = ty;          // dot (snappy)
  let magnetTarget = null;
  let magnetRect   = null;

  window.addEventListener('pointermove', (e) => {
    tx = e.clientX; ty = e.clientY;
  });

  // detect "magnetic" hovers
  function isMagnetic(el) {
    return el && (el.matches('a, button, [data-magnetic]') ||
                  el.closest('a, button, [data-magnetic]'));
  }
  function isText(el) {
    return el && (el.matches('textarea, input') ||
                  el.closest('textarea, input'));
  }

  document.addEventListener('pointerover', (e) => {
    const m = isMagnetic(e.target);
    document.body.classList.toggle('cursor-on-magnetic', !!m);
    document.body.classList.toggle('cursor-on-text', !!isText(e.target));
    if (m) {
      magnetTarget = m.closest('a, button, [data-magnetic]') || m;
      magnetRect   = magnetTarget.getBoundingClientRect();
    } else {
      magnetTarget = null; magnetRect = null;
    }
  });
  document.addEventListener('pointerout', () => {
    magnetTarget = null; magnetRect = null;
  });

  function frame() {
    let targetX = tx, targetY = ty;
    if (magnetTarget) {
      magnetRect = magnetTarget.getBoundingClientRect();
      const cx = magnetRect.left + magnetRect.width / 2;
      const cy = magnetRect.top  + magnetRect.height / 2;
      // pull cursor 25% toward magnet center
      targetX = tx + (cx - tx) * 0.25;
      targetY = ty + (cy - ty) * 0.25;
    }

    rx += (targetX - rx) * 0.18;
    ry += (targetY - ry) * 0.18;
    dx += (tx - dx) * 0.55;
    dy += (ty - dy) * 0.55;

    ring.style.transform = `translate(${rx}px, ${ry}px) translate(-50%, -50%)`;
    dot.style.transform  = `translate(${dx}px, ${dy}px) translate(-50%, -50%)`;

    requestAnimationFrame(frame);
  }
  frame();
})();

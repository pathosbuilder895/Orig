/* ──────────────────────────────────────────────────────────────────────────
   fingerprint.js — procedural particle fingerprint visualization.
   Renders concentric, deformed oval rings (like a real thumbprint) as
   particles slowly drifting along their target curve. Mouse repels softly.
   Pulses subtly. Re-seeds when palette changes (via .reseed()).
   ────────────────────────────────────────────────────────────────────────── */
(function (window) {
  function Fingerprint(canvas, opts = {}) {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const ctx = canvas.getContext('2d');
    const cfg = Object.assign({
      rings: 16,
      particlesPerRing: 90,
      baseRadius: 36,
      ringGap: 10,
      noiseAmp: 6,
      lineColor: 'rgba(245,239,224,0.55)',
      goldColor: 'rgba(201,160,40,0.85)',
      mouseRepel: 60,
    }, opts);

    let w = 0, h = 0;
    let particles = [];
    let mouse = { x: -9999, y: -9999, in: false };
    let t0 = performance.now();
    let running = true;

    function resize() {
      const rect = canvas.getBoundingClientRect();
      w = rect.width; h = rect.height;
      canvas.width  = w * dpr;
      canvas.height = h * dpr;
      ctx.scale(dpr, dpr);
      seed();
    }

    // 2D noise — quick & cheap based on sin/cos
    function pseudoNoise(x, y, seed) {
      return (
        Math.sin(x * 0.013 + seed * 1.3) * 0.5 +
        Math.cos(y * 0.017 + seed * 2.1) * 0.3 +
        Math.sin((x + y) * 0.009 + seed * 0.7) * 0.4
      );
    }

    function seed() {
      const cx = w / 2;
      const cy = h / 2;
      // make rings sized to canvas
      const maxR = Math.min(w, h) * 0.46;
      const minR = maxR * 0.18;
      const ringStep = (maxR - minR) / cfg.rings;

      particles = [];
      for (let r = 0; r < cfg.rings; r++) {
        const baseR = minR + r * ringStep;
        // each ring has a phase / eccentricity / tilt
        const ringSeed = (r * 7.13) + (Math.random() * 0.1);
        const tilt = (Math.random() - 0.5) * 0.3;
        const ecc  = 0.85 + Math.random() * 0.3;  // x/y stretch
        const breaks = Math.floor(Math.random() * 2);  // ridge breaks
        const breakAt = Math.random() * Math.PI * 2;
        const breakSpan = 0.25 + Math.random() * 0.25;

        for (let p = 0; p < cfg.particlesPerRing; p++) {
          const ang = (p / cfg.particlesPerRing) * Math.PI * 2;

          // skip particles in a small "break" arc to make ridge endings
          if (breaks > 0) {
            const diff = Math.abs(((ang - breakAt + Math.PI * 3) % (Math.PI * 2)) - Math.PI);
            if (Math.PI - diff < breakSpan) continue;
          }

          // deformation
          const n = pseudoNoise(
            Math.cos(ang) * baseR,
            Math.sin(ang) * baseR,
            ringSeed
          );
          const rOff = n * cfg.noiseAmp;

          const x = cx + Math.cos(ang + tilt) * (baseR + rOff) * ecc;
          const y = cy + Math.sin(ang + tilt) * (baseR + rOff);
          particles.push({
            ang, baseR, tilt, ecc, ringSeed,
            x, y, ox: x, oy: y,
            vx: 0, vy: 0,
            r: r < cfg.rings * 0.4 && Math.random() < 0.06 ? 1.4 : 0.8,
            goldP: Math.random() < 0.04,   // some particles are gold
          });
        }
      }
    }

    function step(now) {
      if (!running) return;
      const tt = (now - t0) / 1000;

      ctx.clearRect(0, 0, w, h);

      // ambient breathing pulse
      const pulse = 1 + Math.sin(tt * 0.7) * 0.012;

      for (let i = 0; i < particles.length; i++) {
        const p = particles[i];
        // re-evaluate target with slight phase drift
        const ang = p.ang + tt * 0.02 + Math.sin(tt * 0.3 + p.ringSeed) * 0.005;
        const n   = pseudoNoise(
          Math.cos(ang) * p.baseR,
          Math.sin(ang) * p.baseR,
          p.ringSeed + tt * 0.1
        );
        const rOff = n * cfg.noiseAmp;
        const cx = w / 2, cy = h / 2;
        p.ox = cx + Math.cos(ang + p.tilt) * (p.baseR + rOff) * p.ecc * pulse;
        p.oy = cy + Math.sin(ang + p.tilt) * (p.baseR + rOff) * pulse;

        // mouse repulsion
        if (mouse.in) {
          const dx = p.x - mouse.x;
          const dy = p.y - mouse.y;
          const d2 = dx*dx + dy*dy;
          const R = cfg.mouseRepel;
          if (d2 < R*R) {
            const d = Math.sqrt(d2) || 1;
            const force = (1 - d/R) * 2.0;
            p.vx += (dx/d) * force;
            p.vy += (dy/d) * force;
          }
        }

        // spring back to target
        p.vx += (p.ox - p.x) * 0.10;
        p.vy += (p.oy - p.y) * 0.10;
        p.vx *= 0.78;
        p.vy *= 0.78;
        p.x += p.vx;
        p.y += p.vy;

        ctx.beginPath();
        ctx.fillStyle = p.goldP ? cfg.goldColor : cfg.lineColor;
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fill();
      }

      // central core glyph — a tiny rune
      ctx.save();
      ctx.translate(w/2, h/2);
      ctx.rotate(tt * 0.05);
      ctx.strokeStyle = cfg.goldColor;
      ctx.lineWidth = 1;
      ctx.beginPath();
      const coreR = 10;
      for (let i = 0; i < 6; i++) {
        const a = i * Math.PI / 3;
        ctx.moveTo(0, 0);
        ctx.lineTo(Math.cos(a) * coreR, Math.sin(a) * coreR);
      }
      ctx.stroke();
      ctx.restore();

      requestAnimationFrame(step);
    }

    canvas.addEventListener('pointermove', (e) => {
      const r = canvas.getBoundingClientRect();
      mouse.x = e.clientX - r.left;
      mouse.y = e.clientY - r.top;
      mouse.in = true;
    });
    canvas.addEventListener('pointerleave', () => { mouse.in = false; });

    window.addEventListener('resize', resize);
    resize();
    // Synchronous first frame — guarantees the canvas is non-blank even if
    // rAF is suspended (embedded preview iframes throttle background tabs).
    step(performance.now());
    // Schedule continuous animation if rAF is actually firing.
    requestAnimationFrame(step);

    return {
      reseed: seed,
      setColors: (line, gold) => {
        cfg.lineColor = line; cfg.goldColor = gold;
      },
      stop: () => { running = false; },
    };
  }

  window.Fingerprint = Fingerprint;
})(window);

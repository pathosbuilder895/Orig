/* ──────────────────────────────────────────────────────────────────────────
   tension-arc.js — animated Tension Arc κ visualization.
   Plots σ(ρ) · (1−μ(ρ)) as a smoothed curve over "paragraphs" (x positions).
   Hover shows κ value at that paragraph.
   ────────────────────────────────────────────────────────────────────────── */
(function (window) {
  function TensionArc(canvas, hoverEl, opts = {}) {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const ctx = canvas.getContext('2d');
    const cfg = Object.assign({
      paragraphs: 24,
      lineColor: 'rgba(245,239,224,0.7)',
      goldColor: 'rgba(201,160,40,0.85)',
      ghostColor: 'rgba(245,239,224,0.12)',
    }, opts);

    let w=0,h=0;
    let data = [];
    let mouseX = null;
    let mouseY = null;
    let t0 = performance.now();
    let realSeries = null; // set via setSeries() — genuine per-sentence T(i) from the API

    function resize() {
      const r = canvas.getBoundingClientRect();
      w = r.width; h = r.height;
      canvas.width = w*dpr; canvas.height = h*dpr;
      ctx.scale(dpr, dpr);
      seed();
    }

    // Generate baseline arc data — multi-peak narrative tension
    function seed() {
      data = [];
      if (realSeries && realSeries.length) {
        // Real per-sentence tension — no ghost baseline series is returned by
        // the API, so the "baseline" line is a flat mean (a neutral reference,
        // not a fabricated curve) and the submission line is the true data.
        const n = realSeries.length;
        const mean = realSeries.reduce((a, b) => a + b, 0) / n;
        for (let i = 0; i < n; i++) {
          data.push({ x: n > 1 ? i / (n - 1) : 0, baseline: mean, submission: realSeries[i] });
        }
        return;
      }
      // simulate baseline (lower amplitude) and current submission (higher)
      for (let i=0;i<cfg.paragraphs;i++) {
        const x = i / (cfg.paragraphs-1);
        // multi-bell arc: low → rising → climax mid-end → falling
        const climaxBell = Math.exp(-Math.pow((x-0.72)/0.18, 2)) * 0.9;
        const midBump    = Math.exp(-Math.pow((x-0.42)/0.14, 2)) * 0.45;
        const dip        = Math.exp(-Math.pow((x-0.6)/0.06, 2)) * -0.25;
        const baseline   = climaxBell*0.45 + midBump*0.55 + dip;
        const submission = climaxBell + midBump + dip + (Math.random()-0.5)*0.05;
        data.push({ x, baseline, submission });
      }
    }

    function smooth(points, key) {
      // pass through original Y values, but draw with cardinal-ish smoothing
      return points.map(p => p[key]);
    }

    function drawCurve(values, color, isGhost) {
      // map x→canvas, y→canvas (invert: high tension goes up)
      const padX = 24, padY = 30;
      const pw = w - padX*2, ph = h - padY*2;

      ctx.beginPath();
      ctx.strokeStyle = color;
      ctx.lineWidth = isGhost ? 1.2 : 2;
      ctx.lineJoin = 'round';
      ctx.lineCap  = 'round';

      const N = values.length;
      for (let i = 0; i < N; i++) {
        const x = padX + (i/(N-1)) * pw;
        const v = values[i];
        const y = padY + ph - (v * ph * 0.85);
        if (i === 0) ctx.moveTo(x, y);
        else {
          // smooth using midpoint
          const pX = padX + ((i-1)/(N-1)) * pw;
          const pV = values[i-1];
          const pY = padY + ph - (pV * ph * 0.85);
          const cX = (x + pX) / 2;
          const cY = (y + pY) / 2;
          ctx.quadraticCurveTo(pX, pY, cX, cY);
          if (i === N-1) ctx.lineTo(x, y);
        }
      }
      ctx.stroke();
    }

    function drawGrid() {
      ctx.save();
      ctx.strokeStyle = 'rgba(245,239,224,0.06)';
      ctx.lineWidth = 1;
      for (let i = 1; i < 4; i++) {
        const y = (h * i / 4);
        ctx.beginPath();
        ctx.setLineDash([2, 6]);
        ctx.moveTo(0, y); ctx.lineTo(w, y);
        ctx.stroke();
      }
      ctx.setLineDash([]);
      ctx.restore();
    }

    function drawAxis() {
      // dashed baseline at y=0
      ctx.save();
      const padX = 24, padY = 30;
      const pw = w - padX*2, ph = h - padY*2;
      ctx.strokeStyle = 'rgba(201,160,40,0.20)';
      ctx.setLineDash([4, 6]);
      ctx.beginPath();
      ctx.moveTo(padX, padY + ph); ctx.lineTo(padX + pw, padY + ph);
      ctx.stroke();
      ctx.restore();
    }

    function paragraphAt(px) {
      const padX = 24;
      const pw = w - padX*2;
      const n = Math.max(1, data.length - 1);
      const r = (px - padX) / pw;
      return Math.max(0, Math.min(n, Math.round(r * n)));
    }

    function frame(now) {
      const tt = (now - t0) / 1000;
      ctx.clearRect(0, 0, w, h);
      drawGrid();
      drawAxis();

      // animate the submission curve slightly (subtle breathing) — only for
      // the fabricated demo curve; real data is rendered exactly as measured.
      const animBoost = realSeries ? 1 : 1 + Math.sin(tt * 0.4) * 0.015;
      const subVals = data.map(p => p.submission * animBoost);
      const baseVals = data.map(p => p.baseline);

      drawCurve(baseVals, cfg.ghostColor, true);
      drawCurve(subVals,  cfg.goldColor,  false);

      // hover marker
      if (mouseX !== null && data.length) {
        const idx = paragraphAt(mouseX);
        const padX = 24, padY = 30;
        const pw = w - padX*2, ph = h - padY*2;
        const n = Math.max(1, data.length - 1);
        const x = padX + (idx/n) * pw;
        const v = subVals[idx];
        const y = padY + ph - (v * ph * 0.85);

        // vertical guide
        ctx.save();
        ctx.strokeStyle = 'rgba(245,239,224,0.18)';
        ctx.beginPath();
        ctx.moveTo(x, padY); ctx.lineTo(x, padY + ph);
        ctx.stroke();
        // marker
        ctx.fillStyle = cfg.goldColor;
        ctx.beginPath();
        ctx.arc(x, y, 4, 0, Math.PI*2);
        ctx.fill();
        ctx.restore();

        // update hover element
        if (hoverEl) {
          hoverEl.classList.add('show');
          hoverEl.style.left = `${x}px`;
          hoverEl.style.top  = `${y}px`;
          const unit = realSeries ? 'sentence' : '¶';
          hoverEl.innerHTML =
            `<div>${unit} ${String(idx+1).padStart(2,'0')} / ${data.length}</div>` +
            `<div>κ = <span class="k">${v.toFixed(3)}</span></div>`;
        }
      } else if (hoverEl) {
        hoverEl.classList.remove('show');
      }

      requestAnimationFrame(frame);
    }

    canvas.addEventListener('pointermove', (e) => {
      const r = canvas.getBoundingClientRect();
      mouseX = e.clientX - r.left;
      mouseY = e.clientY - r.top;
    });
    canvas.addEventListener('pointerleave', () => { mouseX = null; mouseY = null; });
    window.addEventListener('resize', resize);

    resize();
    // Synchronous first frame in case rAF is suspended in this iframe.
    frame(performance.now());
    requestAnimationFrame(frame);

    return {
      setColors: (line, gold, ghost) => {
        cfg.lineColor = line; cfg.goldColor = gold; cfg.ghostColor = ghost;
      },
      // Feed genuine per-sentence T(i) values (Layer7Output.tension_arc.tension_series).
      // Values are clamped to [0,1] for the chart's fixed y-scale; real values
      // are typically already in that range but this guards against outliers.
      setSeries: (values) => {
        realSeries = (values || []).map((v) => Math.max(0, Math.min(1, v)));
        seed();
      },
    };
  }

  window.TensionArc = TensionArc;
})(window);

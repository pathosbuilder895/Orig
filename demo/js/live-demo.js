/* ──────────────────────────────────────────────────────────────────────────
   live-demo.js — paste-text → fingerprint extraction (mocked but believable).
   Renders the user's text into pseudo-stylometric numbers, then animates
   a small fingerprint canvas + feature strip.
   ────────────────────────────────────────────────────────────────────────── */
(function (window) {
  // simple deterministic hash for repeatable "fingerprints"
  function hash(str) {
    let h = 2166136261;
    for (let i=0;i<str.length;i++) { h ^= str.charCodeAt(i); h = (h * 16777619) >>> 0; }
    return h >>> 0;
  }
  function rng(seed) {
    let s = seed || 123456789;
    return () => {
      s ^= s << 13; s ^= s >>> 17; s ^= s << 5;
      return ((s >>> 0) / 0xffffffff);
    };
  }

  // simulate stylometric features from text
  function analyze(text) {
    const trimmed = text.trim();
    const sentences = trimmed.split(/[.!?]+(?:\s|$)/).filter(s => s.trim().length>0);
    const words = trimmed.split(/\s+/).filter(Boolean);
    const chars = trimmed.length;
    const sLens = sentences.map(s => s.trim().split(/\s+/).filter(Boolean).length);
    const meanSent = sLens.length ? sLens.reduce((a,b)=>a+b,0)/sLens.length : 0;
    const sdSent = sLens.length > 1
      ? Math.sqrt(sLens.reduce((a,b)=>a+(b-meanSent)**2,0)/(sLens.length-1))
      : 0;
    const uniqW = new Set(words.map(w => w.toLowerCase().replace(/[^\w']/g,''))).size;
    const ttr = words.length ? uniqW / words.length : 0;
    const semicolons = (trimmed.match(/;/g) || []).length;
    const dashes = (trimmed.match(/—|--/g) || []).length;
    const commas = (trimmed.match(/,/g) || []).length;
    const fnWords = ['the','of','and','to','a','in','that','it','is','was','for','on','with','as','by','at','this','from','an','be','or','are'];
    const lowerWords = words.map(w => w.toLowerCase().replace(/[^\w']/g,''));
    const fnHits = lowerWords.filter(w => fnWords.includes(w)).length;
    const fnRatio = words.length ? fnHits / words.length : 0;
    // pretend κ (tension arc) — derived from sentence-length variation
    const kappa = Math.min(1, sdSent / 12 + ttr * 0.4);
    // pretend "voice authenticity" — hash-derived stable value
    const seed = hash(trimmed.slice(0, 256));
    const r = rng(seed);
    const voice = 0.78 + r() * 0.20;
    return {
      words: words.length, chars, sentences: sentences.length,
      meanSent, sdSent, ttr, semicolons, dashes, commas, fnRatio,
      kappa, voice, seed,
    };
  }

  // Animate the strip with feature lines, then reveal the result panel.
  // Plain English — written for a professor, not an engineer.
  const FEATURE_LINES = [
    (s) => `Average sentence length — ${s.meanSent.toFixed(1)} words`,
    (s) => `Sentence variety — ${s.sdSent < 5 ? 'very consistent' : s.sdSent < 10 ? 'moderately varied' : 'highly varied'} (±${s.sdSent.toFixed(1)} words)`,
    (s) => `Vocabulary range — ${Math.round(s.ttr * 100)}% unique words`,
    (s) => `Semicolon use — ${s.semicolons === 0 ? 'none' : `about ${(s.semicolons/Math.max(1,s.sentences)).toFixed(1)} per sentence`}`,
    (s) => `Em-dash habit — ${s.dashes === 0 ? 'avoids them' : s.dashes === 1 ? 'used once' : `used ${s.dashes} times`}`,
    (s) => `Everyday connector words — ${Math.round(s.fnRatio * 100)}% of text`,
    (s) => `Comma rhythm — about ${(s.commas/Math.max(1,s.sentences)).toFixed(1)} per sentence`,
    (s) => `Punctuation formality — ${Math.round((0.31+(s.seed%97)/300) * 100)}%`,
    (s) => `Grammatical variety — ${Math.round(((2.41+(s.seed%173)/600) / 3.2) * 100)}%`,
    (s) => `Personal quirks detected — ${Math.round((0.18+(s.seed%241)/1100) * 100)}% distinctive`,
    (s) => `Voice consistency — ${Math.round(s.voice * 100)}%`,
    (s) => `Narrative tension (κ) — ${Math.round(s.kappa * 100)}%`,
  ];

  // Mini fingerprint draw — adapted from main viz, smaller + faster
  function drawMiniFingerprint(canvas, seed, progress) {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const ctx = canvas.getContext('2d');
    const r = canvas.getBoundingClientRect();
    const w = r.width, h = r.height;
    if (canvas.width !== w*dpr) {
      canvas.width = w*dpr; canvas.height = h*dpr;
      ctx.setTransform(dpr,0,0,dpr,0,0);
    }
    ctx.clearRect(0,0,w,h);
    const cx = w/2, cy = h/2;
    const maxR = Math.min(w,h) * 0.42;
    const minR = maxR * 0.18;
    const rings = 14;
    const rand = rng(seed);
    for (let r2 = 0; r2 < rings; r2++) {
      const ringP = (r2+1) / rings;
      if (ringP > progress) break;
      const baseR = minR + r2 * ((maxR - minR) / rings);
      const tilt = (rand() - 0.5) * 0.4;
      const ecc  = 0.85 + rand() * 0.3;
      const phase = rand() * Math.PI * 2;
      const breakAt = rand() * Math.PI * 2;
      const breakSpan = 0.2 + rand() * 0.3;
      ctx.beginPath();
      ctx.strokeStyle = r2 % 5 === 0
        ? 'rgba(201,160,40,0.85)'
        : 'rgba(245,239,224,0.45)';
      ctx.lineWidth = 1;
      let started = false;
      const N = 120;
      for (let i = 0; i <= N; i++) {
        const ang = (i/N) * Math.PI * 2;
        // skip break arc
        const diff = Math.abs(((ang - breakAt + Math.PI*3) % (Math.PI*2)) - Math.PI);
        if (Math.PI - diff < breakSpan) { started = false; continue; }
        const rOff = Math.sin(ang*3 + phase) * 4 + Math.cos(ang*2 + phase*2) * 2;
        const x = cx + Math.cos(ang + tilt) * (baseR + rOff) * ecc;
        const y = cy + Math.sin(ang + tilt) * (baseR + rOff);
        if (!started) { ctx.moveTo(x, y); started = true; }
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }
    // central core
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(progress * Math.PI * 2);
    ctx.strokeStyle = 'rgba(201,160,40,0.9)';
    ctx.lineWidth = 1;
    for (let i=0;i<6;i++) {
      const a = i*Math.PI/3;
      ctx.beginPath();
      ctx.moveTo(0,0); ctx.lineTo(Math.cos(a)*8, Math.sin(a)*8);
      ctx.stroke();
    }
    ctx.restore();
  }

  function attach(opts) {
    const root = opts.root;
    const textarea  = root.querySelector('.demo-textarea');
    const wordCount = root.querySelector('.demo-word-count');
    const canvas    = root.querySelector('.demo-canvas');
    const strip     = root.querySelector('.demo-feature-strip');
    const result    = root.querySelector('.demo-result');
    const runBtn    = root.querySelector('.demo-btn.run');
    const clearBtn  = root.querySelector('.demo-btn.clear');
    const sampleBtn = root.querySelector('.demo-btn.sample');

    const SAMPLE = `The Bodleian closes at six. Most evenings I am the last to leave Duke Humfrey's, and I confess a quiet vanity in the ritual — the closing of the inkwell, the gathering of leaves, the long walk down between the chained books. Not every student, I suspect, finds this hour as I find it. Some find the same in libraries of their own design; others in the slow undoing of a margin. The space of authentic thought is not a place: it is the cadence of a mind addressing itself, in private, in patience.`;

    function update() {
      const text = textarea.value;
      const words = text.trim().split(/\s+/).filter(Boolean).length;
      wordCount.textContent = `${words} word${words===1?'':'s'}`;
      runBtn.disabled = words < 20;
      runBtn.style.opacity = runBtn.disabled ? 0.45 : 1;
    }
    textarea.addEventListener('input', update);

    let running = false;
    function run() {
      if (running) return;
      const text = textarea.value;
      if (text.trim().split(/\s+/).filter(Boolean).length < 20) return;
      running = true;
      result.classList.remove('show');
      // clear strip
      strip.innerHTML = '';
      const stats = analyze(text);

      // animate fingerprint drawing in
      let finished = false;
      function finish() {
        if (finished) return;
        finished = true;
        drawMiniFingerprint(canvas, stats.seed, 1);
        // reveal result block
        result.querySelector('.cell-voice .v').textContent = stats.voice.toFixed(3);
        result.querySelector('.cell-kappa .v').textContent = stats.kappa.toFixed(3);
        result.querySelector('.cell-features .v').textContent = '103 / 103';
        result.classList.add('show');
        running = false;
      }
      let p = 0;
      const start = performance.now();
      function tick(now) {
        p = Math.min(1, (now - start) / 2400);
        drawMiniFingerprint(canvas, stats.seed, p);
        if (p < 1) requestAnimationFrame(tick);
        else finish();
      }
      requestAnimationFrame(tick);
      // Failsafe: some embedded preview iframes suspend requestAnimationFrame
      // when the tab is hidden; ensure the result still resolves (never hangs on "—").
      setTimeout(finish, 2600);

      // animate feature strip
      FEATURE_LINES.forEach((mk, i) => {
        setTimeout(() => {
          const ln = document.createElement('span');
          ln.className = 'ln';
          const txt = mk(stats);
          // emphasize the value after the em-dash
          const m = txt.match(/^(.+?) — (.+)$/);
          if (m) ln.innerHTML = `<span>${m[1]} — </span><span class="v">${m[2]}</span>`;
          else   ln.textContent = txt;
          strip.appendChild(ln);
          requestAnimationFrame(() => ln.classList.add('show'));
          // keep only last 6 lines
          const all = [...strip.querySelectorAll('.ln')];
          if (all.length > 6) all[0].remove();
        }, 150 + i * 180);
      });
    }

    runBtn.addEventListener('click', run);
    clearBtn.addEventListener('click', () => {
      textarea.value = '';
      update();
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0,0,canvas.width,canvas.height);
      strip.innerHTML = '';
      result.classList.remove('show');
    });
    sampleBtn.addEventListener('click', () => {
      textarea.value = SAMPLE;
      update();
    });

    update();
  }

  window.LiveDemo = { attach };
})(window);

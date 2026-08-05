/* ──────────────────────────────────────────────────────────────────────────
   scenes.js — scroll-driven reveal + parallax + scroll progress.
   IntersectionObserver toggles .in on .reveal elements.
   ────────────────────────────────────────────────────────────────────────── */
(function () {

  // Stagger child indices for .reveal-stagger > *
  document.querySelectorAll('.reveal-stagger').forEach((root) => {
    [...root.children].forEach((c, i) => c.style.setProperty('--i', i));
  });

  // For peel elements: wrap each WORD in a no-break wrapper, then each
  // character in <span class="l"> for per-letter animation. The word
  // wrapper has white-space: nowrap so letters in a word don't break.
  document.querySelectorAll('.peel').forEach((el) => {
    if (el.dataset.peeled) return;
    el.dataset.peeled = '1';
    const original = el.textContent;
    el.innerHTML = '';
    let i = 0;
    const tokens = original.split(/(\s+)/);
    for (const tok of tokens) {
      if (/^\s+$/.test(tok)) {
        el.appendChild(document.createTextNode(' '));
        continue;
      }
      const word = document.createElement('span');
      word.className = 'peel-word';
      word.style.whiteSpace = 'nowrap';
      word.style.display = 'inline-block';
      for (const ch of tok) {
        const s = document.createElement('span');
        s.className = 'l';
        s.textContent = ch;
        s.style.setProperty('--i', i++);
        word.appendChild(s);
      }
      el.appendChild(word);
    }
  });

  // Cold-open word reveal — animation handled in CSS; we just stagger delays
  document.querySelectorAll('.epi-latin').forEach((el) => {
    if (el.dataset.parsed) return;
    el.dataset.parsed = '1';
    const words = el.textContent.split(/(\s+)/);
    el.innerHTML = '';
    let i = 0;
    for (const w of words) {
      if (/^\s+$/.test(w)) { el.appendChild(document.createTextNode(w)); continue; }
      const wrap = document.createElement('span');
      wrap.className = 'word';
      const inner = document.createElement('span');
      inner.textContent = w;
      inner.style.animationDelay = `${i*80}ms`;
      wrap.appendChild(inner);
      el.appendChild(wrap);
      i++;
    }
  });

  // Cold-open failsafe: some embedded preview environments suspend CSS
  // keyframes inside iframes (document.hidden=true throttles rAF and may
  // stall keyframes). Force-resolved state after 1.2s so the text is always
  // present even if the animation didn't progress.
  setTimeout(() => { document.body.classList.add('cold-open-fallback'); }, 1200);

  // Reveal via Web Animations API + inline-style commit. Pure CSS transitions
  // are unreliable in some embedded iframes; WAAPI runs on the compositor and
  // the inline-style commit guarantees the resolved end state regardless.
  function commitReveal(el) {
    if (el.dataset.revealed) return;
    el.dataset.revealed = '1';
    el.classList.add('in');

    const isStagger = el.matches('.reveal-stagger');
    const isPeel    = el.matches('.peel');

    // Kill transition + force reflow + commit end state immediately as a hard
    // floor. We use setProperty with 'important' because in some embedded
    // iframes ordinary inline-style values are masked by an in-progress
    // transition target value that never resolves; !important guarantees it.
    function commit(target) {
      target.style.setProperty('transition', 'none', 'important');
      void target.offsetHeight;
      target.style.setProperty('opacity', '1', 'important');
      target.style.setProperty('transform', 'none', 'important');
    }

    if (isStagger) {
      const kids = [...el.children];
      kids.forEach((kid, i) => {
        try {
          kid.animate(
            [{ opacity: 0, transform: 'translateY(14px)' },
             { opacity: 1, transform: 'translateY(0)' }],
            { duration: 550, delay: i * 80, easing: 'cubic-bezier(.2,.7,.2,1)', fill: 'forwards' }
          );
        } catch (e) {}
        setTimeout(() => commit(kid), 700 + i*80);
      });
      return;
    }

    if (isPeel) {
      const letters = el.querySelectorAll('.l');
      letters.forEach((l, i) => {
        try {
          l.animate(
            [{ opacity: 0, transform: 'translateY(0.4em) rotate(5deg)' },
             { opacity: 1, transform: 'translateY(0) rotate(0)' }],
            { duration: 700, delay: i * 28, easing: 'cubic-bezier(.2,.7,.2,1)', fill: 'forwards' }
          );
        } catch (e) {}
        setTimeout(() => commit(l), 800 + i*28);
      });
      return;
    }

    try {
      el.animate(
        [{ opacity: 0, transform: 'translateY(18px)' },
         { opacity: 1, transform: 'translateY(0)' }],
        { duration: 600, easing: 'cubic-bezier(.2,.7,.2,1)', fill: 'forwards' }
      );
    } catch (e) {}
    setTimeout(() => commit(el), 700);
  }

  function passReveal() {
    const vh = window.innerHeight;
    document.querySelectorAll('.reveal, .reveal-stagger, .peel').forEach((el) => {
      if (el.dataset.revealed) return;
      const r = el.getBoundingClientRect();
      if (r.top < vh * 0.9 && r.bottom > 0) commitReveal(el);
    });
  }
  setTimeout(passReveal, 200);
  setTimeout(passReveal, 800);

  // Generic intersection-driven reveal
  const obs = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) commitReveal(entry.target);
    });
  }, { threshold: 0.18 });
  document.querySelectorAll('.reveal, .reveal-stagger, .peel').forEach(el => obs.observe(el));

  // Special: trigger fingerprint act when in view
  const fpEvent = new CustomEvent('fingerprint:enter');
  const fpObs = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (e.isIntersecting) window.dispatchEvent(fpEvent);
    });
  }, { threshold: 0.3 });
  document.querySelectorAll('.fingerprint-act').forEach(el => fpObs.observe(el));

  // Scroll progress ribbon
  const ribbon = document.querySelector('.scroll-progress');
  function onScroll() {
    const max = document.documentElement.scrollHeight - window.innerHeight;
    const p = max > 0 ? (window.scrollY / max) * 100 : 0;
    if (ribbon) ribbon.style.width = `${p}%`;

    // parallax for .parallax-figure image-slot
    document.querySelectorAll('.parallax-figure').forEach((fig) => {
      const r = fig.getBoundingClientRect();
      const vh = window.innerHeight;
      if (r.bottom < 0 || r.top > vh) return;   // off-screen — skip
      const center = r.top + r.height/2;
      const offset = (vh/2 - center) * 0.28;
      const slot = fig.querySelectorAll('.parallax-bg, image-slot, .arch-placeholder');
      slot.forEach((el) => { el.style.transform = `translateY(${-offset}px)`; });
    });

    // Hero parallax — background drifts at ~22% of scroll speed while the
    // epigraph lifts slightly faster and fades, giving layered depth.
    const hero = document.querySelector('.cold-open');
    if (hero) {
      const y = window.scrollY;
      const vh = window.innerHeight;
      if (y < vh * 1.2) {
        const bg  = hero.querySelector('.hero-bg');
        const epi = hero.querySelector('.epigraph');
        if (bg)  bg.style.transform  = `translateY(${y * 0.22}px)`;
        if (epi) {
          epi.style.transform = `translateY(${y * -0.12}px)`;
          epi.style.opacity   = String(Math.max(0, 1 - y / (vh * 0.7)));
        }
      }
    }

    // Reveal pass — belt-and-braces alongside the IntersectionObserver
    passReveal();
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  // Smooth-scroll on nav anchor click
  document.querySelectorAll('a[href^="#"]').forEach((a) => {
    a.addEventListener('click', (e) => {
      const id = a.getAttribute('href').slice(1);
      const el = document.getElementById(id);
      if (el) {
        e.preventDefault();
        window.scrollTo({ top: el.offsetTop - 40, behavior: 'smooth' });
      }
    });
  });
})();

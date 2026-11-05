/* display-prefs.js — the site-wide Text setting (2026-11).
   Load in <head> (no defer) so the chosen font and size apply before first
   paint. Keeps the choice in localStorage (works before sign-in); a page that
   knows the signed-in account can add a server copy with BBDisplay.sync().
   Display only: never reads or changes what a student writes. */
(function () {
  'use strict';
  var KEY = 'bb.display.v1';
  var FONTS = [
    { id: 'serif', label: 'Book serif', note: 'Default. Easy to read at length' },
    { id: 'sans', label: 'Clear sans', note: 'Plain letters, very clear' },
    { id: 'readable', label: 'Dyslexia-friendly', note: 'Weighted letters, wider spacing' },
    { id: 'classic', label: 'Classic', note: 'The original Garamond look' },
  ];
  var SIZES = [
    { id: 'small', label: 'Small', scale: 0.875 },
    { id: 'default', label: 'Default', scale: 1 },
    { id: 'large', label: 'Large', scale: 1.15 },
    { id: 'xlarge', label: 'Larger', scale: 1.3 },
    { id: 'xxlarge', label: 'Largest', scale: 1.5 },
  ];
  var DEFAULTS = { font: 'serif', size: 'default' };
  var FONT_PREVIEW = {
    serif: "'Source Serif 4',Georgia,serif",
    sans: "'Atkinson Hyperlegible',system-ui,sans-serif",
    readable: "'OpenDyslexic','Atkinson Hyperlegible',Verdana,sans-serif",
    classic: "'EB Garamond',Georgia,serif",
  };
  function valid(p) {
    return !!p && FONTS.some(function (f) { return f.id === p.font; }) &&
      SIZES.some(function (s) { return s.id === p.size; });
  }
  function read() {
    try {
      var p = JSON.parse(localStorage.getItem(KEY) || 'null');
      if (valid(p)) return { font: p.font, size: p.size };
    } catch (e) { /* storage blocked */ }
    return { font: DEFAULTS.font, size: DEFAULTS.size };
  }
  function hasLocal() { try { return !!localStorage.getItem(KEY); } catch (e) { return false; } }
  var current = read();
  var listeners = [];
  var saver = null;

  function apply(p) {
    var root = document.documentElement;
    var scale = 1;
    for (var i = 0; i < SIZES.length; i++) if (SIZES[i].id === p.size) scale = SIZES[i].scale;
    root.setAttribute('data-bb-font', p.font);
    root.setAttribute('data-bb-size', p.size);
    root.style.setProperty('--bb-text-scale', String(scale));
    narrowClasses();
  }

  // The window's width in text widths: how wide it would be at the original
  // 18px default text. Layouts made for narrow windows apply when this is narrow
  // (html.bb-wN, see bluebook/text-breakpoints.mjs).
  var BREAKS = [600, 700, 900, 1000, 1420];
  function narrowClasses() {
    var root = document.documentElement;
    var px = parseFloat(getComputedStyle(root).fontSize) || 18;
    var eff = (root.clientWidth || window.innerWidth) * 18 / px;
    for (var i = 0; i < BREAKS.length; i++) root.classList.toggle('bb-w' + BREAKS[i], eff <= BREAKS[i]);
    var effH = (window.innerHeight || root.clientHeight) * 18 / px;
    root.classList.toggle('bb-h600', effH <= 600);
  }
  window.addEventListener('resize', narrowClasses);
  apply(current);

  function set(p, opts) {
    opts = opts || {};
    var next = { font: p.font || current.font, size: p.size || current.size };
    if (!valid(next)) return current;
    current = next;
    try { localStorage.setItem(KEY, JSON.stringify(current)); } catch (e) { /* ignore */ }
    apply(current);
    for (var i = 0; i < listeners.length; i++) { try { listeners[i](current); } catch (e) { /* ignore */ } }
    if (!opts.fromServer && saver) { try { saver(current); } catch (e) { /* ignore */ } }
    return current;
  }

  // ── Panel ──
  var openState = null;
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    for (var k in attrs || {}) {
      if (k === 'text') n.textContent = attrs[k];
      else if (k === 'style') n.style.cssText = attrs[k];
      else n.setAttribute(k, attrs[k]);
    }
    (kids || []).forEach(function (c) { if (c) n.appendChild(c); });
    return n;
  }
  function radioGroup(name, items, selected, render, onPick, cls) {
    var wrap = el('div', { class: cls, role: 'radiogroup', 'aria-label': name });
    var buttons = items.map(function (it) {
      var b = el('button', { type: 'button', class: 'bbd-opt', role: 'radio', 'data-value': it.id,
        'aria-checked': String(it.id === selected), tabindex: it.id === selected ? '0' : '-1' });
      render(b, it);
      b.addEventListener('click', function () { onPick(it.id); sync(); b.focus(); });
      return b;
    });
    function sync() {
      var sel = onPick.current();
      buttons.forEach(function (b) {
        var on = b.getAttribute('data-value') === sel;
        b.setAttribute('aria-checked', String(on));
        b.setAttribute('tabindex', on ? '0' : '-1');
      });
    }
    wrap.addEventListener('keydown', function (e) {
      var keys = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
      if (!(e.key in keys)) return;
      e.preventDefault();
      var idx = buttons.indexOf(document.activeElement);
      var nb = buttons[(idx + keys[e.key] + buttons.length) % buttons.length];
      nb.click();
    });
    buttons.forEach(function (b) { wrap.appendChild(b); });
    return wrap;
  }
  function close() {
    if (!openState) return;
    var s = openState;
    openState = null;
    document.removeEventListener('keydown', s.onKey, true);
    if (s.backdrop.parentNode) s.backdrop.parentNode.removeChild(s.backdrop);
    if (s.opener && document.contains(s.opener)) { try { s.opener.focus(); } catch (e) { /* ignore */ } }
  }
  function open(opener) {
    if (openState) return;
    var fontPick = function (id) { set({ font: id }); };
    fontPick.current = function () { return current.font; };
    var sizePick = function (id) { set({ size: id }); };
    sizePick.current = function () { return current.size; };
    var title = el('h2', { id: 'bbdTitle', text: 'Text' });
    var note = el('p', { class: 'bbd-note', text: 'Changes how pages look to you, right away. Your writing is not changed.' });
    var fonts = radioGroup('Font', FONTS, current.font, function (b, f) {
      b.appendChild(el('span', { text: f.label, style: 'font-family:' + FONT_PREVIEW[f.id] + ';font-size:1.05rem' }));
      b.appendChild(el('small', { text: f.note }));
    }, fontPick, 'bbd-opts');
    var sizes = radioGroup('Text size', SIZES, current.size, function (b, s) {
      b.appendChild(el('span', { text: s.label }));
      b.setAttribute('aria-label', s.label + ' text (' + Math.round(s.scale * 100) + '%)');
    }, sizePick, 'bbd-sizes');
    var reset = el('button', { type: 'button', class: 'bbd-reset', text: 'Reset to default' });
    var done = el('button', { type: 'button', class: 'bbd-done', text: 'Done' });
    var panel = el('div', { class: 'bbd-panel', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'bbdTitle', 'data-testid': 'text-settings' }, [
      title, note,
      el('fieldset', {}, [el('legend', { text: 'Font' }), fonts]),
      el('fieldset', {}, [el('legend', { text: 'Text size' }), sizes]),
      el('div', { class: 'bbd-actions' }, [reset, done]),
    ]);
    var backdrop = el('div', { class: 'bbd-backdrop' }, [panel]);
    reset.addEventListener('click', function () {
      set(DEFAULTS);
      close(); open(opener);
    });
    done.addEventListener('click', close);
    backdrop.addEventListener('mousedown', function (e) { if (e.target === backdrop) close(); });
    var onKey = function (e) {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); return; }
      if (e.key === 'Tab') { // keep focus in the panel
        var f = panel.querySelectorAll('button[tabindex="0"], .bbd-actions button');
        if (!f.length) return;
        var first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener('keydown', onKey, true);
    document.body.appendChild(backdrop);
    openState = { backdrop: backdrop, opener: opener, onKey: onKey };
    var sel = panel.querySelector('.bbd-opt[aria-checked="true"]');
    (sel || done).focus();
  }

  function makeButton(extraClass) {
    var b = el('button', { type: 'button', class: 'bbd-btn' + (extraClass ? ' ' + extraClass : ''),
      'aria-haspopup': 'dialog', 'data-testid': 'text-settings-button', title: 'Text size and font' });
    b.appendChild(el('span', { class: 'bbd-aa', 'aria-hidden': 'true', text: 'Aa' }));
    b.appendChild(el('span', { text: 'Text' }));
    b.addEventListener('click', function () { open(b); });
    return b;
  }

  // A page that has no built-in Text button opts into a floating one with
  // <script src=".../display-prefs.js" data-float></script>.
  var me = document.currentScript;
  if (me && me.hasAttribute('data-float')) {
    var addFloat = function () { document.body.appendChild(makeButton('bbd-float')); document.body.classList.add('bbd-has-float'); };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', addFloat);
    else addFloat();
  }

  window.BBDisplay = {
    FONTS: FONTS, SIZES: SIZES, DEFAULTS: DEFAULTS,
    get: function () { return { font: current.font, size: current.size }; },
    set: set,
    open: open,
    close: close,
    isOpen: function () { return !!openState; },
    makeButton: makeButton,
    onChange: function (fn) {
      listeners.push(fn);
      return function () { listeners = listeners.filter(function (x) { return x !== fn; }); };
    },
    // load(): Promise<{font,size}|null> from the account; save(prefs): to it.
    sync: function (load, save) {
      saver = save || null;
      if (!load) return Promise.resolve(current);
      return Promise.resolve(load()).then(function (p) {
        if (valid(p)) set(p, { fromServer: true });
        else if (saver && hasLocal()) saver(current); // first sign-in: keep the local choice
        return current;
      }).catch(function () { return current; });
    },
  };
})();

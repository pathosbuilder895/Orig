/* shell.js: the one top bar of every page in the live suite (demo/original/).
   No dependencies, no build step. A page opts in with a placeholder and this
   script straight after it, so the bar is drawn before the rest of the page
   is read and nothing jumps:

     <nav class="shell" data-audience="teacher" data-current="students"></nav>
     <script src="shell.js?v=..."></script>

   data-audience  teacher (the staff pages) or student (voice, my-work)
   data-current   the page itself (its file name without .html). A pill
                  page marks its own pill (aria-current="page"); a student's
                  own pages (baseline, writing-state, evidence, packet) mark
                  Students as their section (aria-current="true"); settings
                  marks no pill, only its menu item.

   What it draws, from the one definition below (Shell.markup):
     the brand mark and the current app's name; the app switch
     (Collections | Original, Original current); the current app's own pages;
     the account menu (Open Collections and Settings for staff, Text, Sign out).
   What it does: opens and closes the account menu (click, Escape, a click
   elsewhere), opens the Text setting (display-prefs.js, BBDisplay), signs out
   through Live.signOut, and once live.js knows who is looking, fills in the
   initials, the name and the role. live.js hides the Collections links for a
   staff workspace without Collections, the app switch's among them.

   The ids and classes live.js, the tests and the e2e specs read stay as they
   were: #me-btn, #me-menu, #mm-name, #mm-sub, #sign-out, .pills, .pill,
   .nav-right, .avatar, .me-menu. Display only. */
(function (window, document) {
  'use strict';

  var ICON = {
    home: '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/>',
    people: '<circle cx="9" cy="8" r="3.2"/><path d="M3 20c0-3.3 2.7-5 6-5s6 1.7 6 5"/><path d="M16 5.2a3.2 3.2 0 010 5.8"/><path d="M21 20c0-2.4-1.4-4-3.6-4.7"/>',
    screen: '<rect x="3" y="4" width="18" height="14" rx="2"/><path d="M8 21h8"/>',
    book: '<path d="M4 19.5A2.5 2.5 0 016.5 17H20V3H6.5A2.5 2.5 0 004 5.5z"/><path d="M4 19.5A2.5 2.5 0 006.5 22H20v-5"/>',
    bars: '<line x1="6" y1="20" x2="6" y2="12"/><line x1="12" y1="20" x2="12" y2="5"/><line x1="18" y1="20" x2="18" y2="9"/>',
    voice: '<circle cx="12" cy="12" r="3.2"/><path d="M12 4.2v2.4M12 17.4v2.4M4.2 12h2.4M17.4 12h2.4M6.6 6.6l1.7 1.7M15.7 15.7l1.7 1.7M17.4 6.6l-1.7 1.7M8.3 15.7l-1.7 1.7"/>',
    page: '<path d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h4"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 11-4 0v-.09a1.65 1.65 0 00-1-1.51 1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 110-4h.09a1.65 1.65 0 001.51-1 1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33h0a1.65 1.65 0 001-1.51V3a2 2 0 114 0v.09a1.65 1.65 0 001 1.51h0a1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82v0a1.65 1.65 0 001.51 1H21a2 2 0 110 4h-.09a1.65 1.65 0 00-1.51 1z"/>',
    out: '<path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/>'
  };

  // The one definition of the bar. "Sessions" is this suite's page of
  // Collections sessions (bluebook.html); the app switch is the only place the
  // word Collections names the Collections app.
  var AUDIENCES = {
    teacher: {
      home: 'index.html',
      collections: '/bluebook/#dashboard',
      pages: [
        { id: 'index', href: 'index.html', label: 'Overview', icon: 'home' },
        { id: 'students', href: 'students.html', label: 'Students', icon: 'people' },
        { id: 'submissions', href: 'submissions.html', label: 'Submissions', icon: 'screen' },
        { id: 'bluebook', href: 'bluebook.html', label: 'Sessions', icon: 'book' },
        { id: 'reports', href: 'reports.html', label: 'Reports', icon: 'bars' }
      ],
      // The way back to the Collections dashboard comes first (bare /bluebook/
      // sends a teacher to Original), then Settings.
      menu: [
        { href: '/bluebook/#dashboard', label: 'Open Collections', icon: 'book' },
        { id: 'settings', href: 'settings.html', label: 'Settings', icon: 'gear' }
      ],
      sub: ''
    },
    student: {
      home: 'voice.html',
      collections: '/bluebook/',
      pages: [
        { id: 'voice', href: 'voice.html', label: 'My voice', icon: 'voice' },
        { id: 'my-work', href: 'my-work.html', label: 'My work', icon: 'page' }
      ],
      // A student has no Settings page: Text and Sign out only.
      menu: [],
      sub: 'Student'
    }
  };

  // The pages that belong to a pill's section without being that pill's page.
  var SECTION_OF = { baseline: 'students', 'writing-state': 'students', evidence: 'students', packet: 'students' };

  var ROLE = { professor: 'Teacher', admin: 'Workspace admin', operator: 'Operator', super_admin: 'Platform admin' };

  var ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return ESCAPES[c]; });
  }
  function svg(name) {
    return '<svg viewBox="0 0 24 24" aria-hidden="true">' + ICON[name] + '</svg>';
  }

  // The bar's inner markup for one audience and current page. Pure: the tests
  // run it under node to read each page's menu and pills.
  function markup(audience, current) {
    var a = AUDIENCES[audience] || AUDIENCES.teacher;
    var section = SECTION_OF[current] || current;
    var html = '';
    html += '<div class="brand"><span class="mk" aria-hidden="true"></span><span class="bn">Original</span></div>';
    html += '<div class="app-switch" role="group" aria-label="Apps">' +
      '<a href="' + esc(a.collections) + '">Collections</a>' +
      '<a href="' + esc(a.home) + '" aria-current="true">Original</a>' +
      '</div>';
    html += '<div class="pills">';
    a.pages.forEach(function (p) {
      var on = p.id === section;
      var mark = !on ? '' : p.id === current ? ' aria-current="page"' : ' aria-current="true"';
      html += '<a class="pill' + (on ? ' on' : '') + '" href="' + esc(p.href) + '"' + mark + '>' +
        svg(p.icon) + esc(p.label) + '</a>';
    });
    html += '</div>';
    html += '<div class="nav-right">';
    html += '<button class="avatar" id="me-btn" type="button" title="Account" aria-label="Account" ' +
      'aria-haspopup="true" aria-expanded="false" aria-controls="me-menu">··</button>';
    html += '<div class="me-menu" id="me-menu">';
    html += '<div class="mm-head"><b id="mm-name">Your account</b><span id="mm-sub">' + esc(a.sub) + '</span></div>';
    a.menu.forEach(function (m) {
      html += '<a href="' + esc(m.href) + '"' + (m.id && m.id === current ? ' aria-current="page"' : '') + '>' +
        svg(m.icon) + esc(m.label) + '</a>';
    });
    html += '<button type="button" id="mm-text" data-testid="text-settings-button" aria-haspopup="dialog" title="Text size and font">' +
      '<span class="mm-aa" aria-hidden="true">Aa</span>Text</button>';
    html += '<a href="#" id="sign-out">' + svg('out') + 'Sign out</a>';
    html += '</div></div>';
    return html;
  }

  function initials(name) {
    var w = String(name || '').trim().split(/[\s_.-]+/).filter(Boolean);
    if (!w.length) return '';
    return (w[0].charAt(0) + (w.length > 1 ? w[w.length - 1].charAt(0) : '')).toUpperCase();
  }

  // Pages that keep something of their own until sign-out add a step here
  // (Shell.beforeSignOut(fn)); Live.signOut clears the suite's shared keys.
  var beforeSignOut = [];

  function wire(nav, audience) {
    var btn = nav.querySelector('#me-btn');
    var menu = nav.querySelector('#me-menu');
    if (!btn || !menu) return;
    function setOpen(open) {
      menu.classList.toggle('open', open);
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    }
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      setOpen(!menu.classList.contains('open'));
    });
    menu.addEventListener('click', function (e) { e.stopPropagation(); });
    document.addEventListener('click', function () { setOpen(false); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && menu.classList.contains('open')) { setOpen(false); btn.focus(); }
    });
    var text = menu.querySelector('#mm-text');
    if (text) {
      text.addEventListener('click', function () {
        setOpen(false);
        // Focus comes back to the account button when the panel closes.
        if (window.BBDisplay && typeof window.BBDisplay.open === 'function') window.BBDisplay.open(btn);
      });
      if (!window.BBDisplay) text.hidden = true;
    }
    var out = menu.querySelector('#sign-out');
    if (out) {
      out.addEventListener('click', function (e) {
        e.preventDefault();
        beforeSignOut.forEach(function (fn) { try { fn(); } catch (err) { /* keep signing out */ } });
        if (window.Live) window.Live.signOut();
      });
    }
    // Who is looking, once live.js has asked (Live.session() is shared, so this
    // costs no extra request).
    var chrome = function () {
      if (!window.Live || typeof window.Live.session !== 'function') return;
      window.Live.session().then(function (sess) {
        btn.textContent = initials(sess.name) || '··';
        var name = nav.querySelector('#mm-name');
        if (name) name.textContent = sess.name || 'Your account';
        if (audience !== 'student') {
          var sub = nav.querySelector('#mm-sub');
          if (sub) sub.textContent = sess.mode === 'demo' ? 'Demo workspace' : (ROLE[sess.role] || '');
          if (out) out.style.display = sess.mode === 'signed-in' ? '' : 'none';
        }
      }, function () { /* the page says what went wrong */ });
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', chrome);
    else chrome();
  }

  function render(nav) {
    if (!nav || nav.getAttribute('data-shell-drawn')) return;
    var audience = nav.getAttribute('data-audience') === 'student' ? 'student' : 'teacher';
    nav.classList.add('shell');
    if (!nav.getAttribute('aria-label')) nav.setAttribute('aria-label', 'Original');
    nav.innerHTML = markup(audience, nav.getAttribute('data-current') || '');
    nav.setAttribute('data-shell-drawn', '1');
    wire(nav, audience);
  }

  window.Shell = {
    AUDIENCES: AUDIENCES,
    markup: markup,
    render: render,
    beforeSignOut: function (fn) { if (typeof fn === 'function') beforeSignOut.push(fn); }
  };

  // Draw the placeholder this script follows (and any other on the page).
  try {
    var navs = document.querySelectorAll('nav[data-audience]');
    for (var i = 0; i < navs.length; i++) render(navs[i]);
  } catch (e) { /* not a browser */ }
})(window, document);

/* live.js: the one shared script of the live navy suite (demo/original/).
   No dependencies, no build step. Each page loads it with
   <script src="live.js"></script> before its own script and uses only
   window.Live for data, sign-in state and the testing-phase label.

   Live.TOKEN_KEYS   localStorage keys a sign-in leaves behind
   Live.NOTICE       the testing-phase label, verbatim (the ONLY copy in the suite)
   Live.esc(s)       HTML-escape any value before it goes into innerHTML
   Live.api(p, o)    same-origin fetch with the bearer token; never throws
   Live.session()    who is looking: demo, signed-in or signed-out
   Live.notices()    fills every [data-testing-notice] with the label
   Live.empty(el,t)  an honest empty state inside a card
   Live.gate(el)     sign-in / "Original is off" panel, or the session
   Live.roster()     the teacher's students with the server's baseline verdicts
   Live.sealed()     the teacher's sealed exams, copied through one allowlist
   Live.signOut()    forget the session and go to the sign-in page */
(function (window, document) {
  'use strict';

  var TOKEN_KEYS = [
    'original_principal_token',
    'original_session_token',
    'original_role',
    'original_tenant',
    'original_name'
  ];

  // Left behind by Bluebook's own sign-in. Signing out clears them too, so a
  // shared machine does not keep the last teacher's email or product list.
  var EXTRA_KEYS = [
    'original_email',
    'original_products',
    'original_student_id',
    'bluebook_student_id',
    'bluebook_candidate_email',
    'bluebook_proctor_token'
  ];

  var NOTICE = 'Testing phase: Original is not yet validated on real student writing. Treat any result as a reason for a conversation, never as evidence.';

  var ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return ESCAPES[c]; });
  }

  function read(key) {
    try { return window.localStorage.getItem(key) || ''; } catch (e) { return ''; }
  }

  function failed() {
    return { ok: false, status: 0, data: null };
  }

  // Same-origin fetch. Adds the principal token when one is stored, turns a
  // plain-object body into JSON, and always resolves {ok, status, data}:
  // a network error or a body that is not JSON gives data = null, never a throw.
  function api(path, opts) {
    try {
      var p = String(path || '');
      if (p.charAt(0) !== '/') return Promise.resolve(failed());
      // The bearer token must never leave this site. Checking the first two
      // characters is not enough: the URL parser reads a backslash as a slash
      // and drops tabs and newlines, so '/\\evil.com/x' and '/<TAB>/evil.com/x'
      // both resolve to another host. Resolve the URL and compare origins.
      var u = new URL(p, window.location.href);
      if (u.origin !== window.location.origin) return Promise.resolve(failed());
      opts = opts || {};
      var init = {};
      Object.keys(opts).forEach(function (k) { init[k] = opts[k]; });
      var headers = new Headers(opts.headers || {});
      var kind = Object.prototype.toString.call(opts.body);
      if (kind === '[object Object]' || kind === '[object Array]') {
        init.body = JSON.stringify(opts.body);
        if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
      }
      var tok = read('original_principal_token');
      if (tok && !headers.has('Authorization')) headers.set('Authorization', 'Bearer ' + tok);
      if (!headers.has('Accept')) headers.set('Accept', 'application/json');
      init.headers = headers;
      init.credentials = 'same-origin';
      return fetch(u.href, init).then(function (res) {
        return res.text().then(function (text) {
          var data = null;
          if (text) { try { data = JSON.parse(text); } catch (e) { data = null; } }
          return { ok: res.ok, status: res.status, data: data };
        }, function () {
          return { ok: res.ok, status: res.status, data: null };
        });
      }, failed);
    } catch (e) {
      return Promise.resolve(failed());
    }
  }

  function loadSession() {
    var name = read('original_name');
    var tenant = read('original_tenant');
    var token = read('original_principal_token');
    // A student holds a session token (an account sign-in) or a launch binding
    // (a Bluebook magic link, which stores no original_role), never a
    // principal token, and /auth/me does not answer for either.
    if (!token && (read('original_session_token') || read('bluebook_student_id'))) {
      return Promise.resolve({ mode: 'signed-in', role: 'student', products: [], tenant: tenant, name: name });
    }
    var me = token ? api('/auth/me') : Promise.resolve(null);
    return me.then(function (res) {
      if (res && res.ok && res.data) {
        return {
          mode: 'signed-in',
          role: String(res.data.role || ''),
          products: Array.isArray(res.data.products) ? res.data.products.slice() : [],
          tenant: String(res.data.tenant_id || tenant),
          name: name
        };
      }
      // /auth/me answers 401 for anonymous and demo callers alike, so ask
      // /health whether this server is the open demo.
      return api('/health').then(function (h) {
        if (h.ok && h.data && h.data.environment === 'demo') {
          return { mode: 'demo', role: 'demo', products: ['original', 'bluebook'], tenant: '', name: '' };
        }
        return { mode: 'signed-out', role: '', products: [], tenant: '', name: '' };
      });
    });
  }

  var sessionPromise = null;
  function session() {
    if (!sessionPromise) sessionPromise = loadSession();
    return sessionPromise;
  }

  function notices() {
    var cut = NOTICE.indexOf(':') + 1;
    var html = '<b>' + esc(NOTICE.slice(0, cut)) + '</b>' + esc(NOTICE.slice(cut));
    var nodes = document.querySelectorAll('[data-testing-notice]');
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      n.classList.add('live-testing');
      // A value on the attribute names a variant class, e.g. "on-paper".
      (n.getAttribute('data-testing-notice') || '').split(/\s+/).forEach(function (c) {
        if (c) n.classList.add(c);
      });
      n.setAttribute('role', 'note');
      n.innerHTML = html;
    }
  }

  function empty(el, text) {
    if (!el) return;
    el.innerHTML = '<div class="live-empty">' + esc(text) + '</div>';
  }

  function panel(el, title, text, href, label) {
    (el || document.body).innerHTML =
      '<div class="live-panel" role="status"><h2>' + esc(title) + '</h2><p>' + esc(text) + '</p>' +
      '<a href="' + esc(href) + '">' + esc(label) + '</a></div>';
  }

  // Resolves the session when the page may load its data; otherwise puts the
  // right panel into el (or sends a student to Bluebook) and resolves null.
  function gate(el) {
    return session().then(function (s) {
      if (s.mode === 'signed-out') {
        panel(el, 'Sign in to continue',
          'This page shows your own classes and students, so it needs you to be signed in.',
          '/index.html', 'Sign in');
        return null;
      }
      if (s.role === 'student') {
        window.location.replace('/bluebook/');
        return null;
      }
      if (s.products.indexOf('original') < 0) {
        panel(el, 'Original is off for this workspace',
          'Your workspace uses Bluebook only. Your classes and sealed exams are in Bluebook.',
          '/bluebook/', 'Open Bluebook');
        return null;
      }
      return s;
    });
  }

  // ── Live.sealed ──────────────────────────────────────────────────────────
  // The one loader for sealed exams. Every page that lists, counts or groups
  // them calls this (Live.roster does too) and never keeps its own copy.
  //
  //   GET /bluebook/submissions   the sealed exams
  //   GET /bluebook/students      names, for the students who sat them
  //   GET /bluebook/exams         title, course and course id of each exam
  //
  // Resolves, and never rejects:
  //   bluebook       'ok' | 'off' | 'error'. 'off' is no Bluebook product in
  //                  this workspace, or a 403; 'error' is any other answer
  //                  that is not a list of sealed exams
  //   submissions[]  one object per sealed exam, holding exactly SEALED_FIELDS
  //                  plus course_id (the exam record's, else null). Nothing
  //                  else Bluebook sent about a submission (its integrity
  //                  readings, a status label, warnings, the grader, the
  //                  feedback, the paper text) is ever copied out
  //   names          Map(student_id -> name) from Bluebook's rosters
  //   exams          Map(exam_id -> {title, course, course_id})
  //
  // Memoised: the three requests are made once per page load, whoever asks.
  // An exam is awaiting review when it has no graded_at (see pendingReview).

  var ROSTER_CAP = 60;        // readiness is asked for the first 60 students
  var ROSTER_IN_FLIGHT = 6;   // requests in flight at once, across the whole load

  // The only fields that ever leave a /bluebook/submissions response.
  var SEALED_FIELDS = ['id', 'exam_id', 'student_id', 'candidate', 'exam', 'course', 'created_at', 'late', 'mark', 'graded_at'];

  // Runs the calls it is given at most `max` at a time, in the order given.
  function limiter(max) {
    var active = 0, waiting = [];
    function pump() {
      while (active < max && waiting.length) {
        (function (job) {
          active++;
          var p;
          try { p = Promise.resolve(job.fn()); } catch (e) { p = Promise.resolve(failed()); }
          var done = function (v) { active--; job.resolve(v); pump(); };
          p.then(done, function () { done(failed()); });
        })(waiting.shift());
      }
    }
    return function (fn) {
      return new Promise(function (resolve) { waiting.push({ fn: fn, resolve: resolve }); pump(); });
    };
  }

  // One limiter for the page: the roster's calls and the sealed-exam calls share
  // the same six slots.
  var get = limiter(ROSTER_IN_FLIGHT);

  function pendingReview(s) {
    return !s.graded_at;
  }

  function sealedRow(raw, exams) {
    var out = {};
    SEALED_FIELDS.forEach(function (k) { out[k] = raw[k] != null ? raw[k] : null; });
    var e = exams.get(out.exam_id);
    out.course_id = e ? e.course_id : null;
    return out;
  }

  function sealedState(state) {
    return { view: { bluebook: state, submissions: [], names: new Map(), exams: new Map() }, students: null };
  }

  function loadSealed(sess) {
    if (sess.products.indexOf('bluebook') < 0) return Promise.resolve(sealedState('off'));
    var sbP = get(function () { return api('/bluebook/submissions'); });
    var bsP = get(function () { return api('/bluebook/students'); });
    var exP = get(function () { return api('/bluebook/exams'); });
    return Promise.all([sbP, bsP, exP]).then(function (all) {
      var sb = all[0], bs = all[1], ex = all[2];
      if (sb.status === 403 || bs.status === 403) return sealedState('off');
      if (!sb.ok || !sb.data || !Array.isArray(sb.data.submissions)) return sealedState('error');

      // Keyed by ids the API sent: a Map, so an id like "constructor" is just an id.
      var names = new Map(), exams = new Map(), students = null;
      if (bs.ok && bs.data && Array.isArray(bs.data.students)) {
        students = bs.data.students.filter(function (x) { return x && typeof x === 'object'; });
        students.forEach(function (x) { if (x.name) names.set(x.student_id, String(x.name)); });
      }
      if (ex.ok && ex.data && Array.isArray(ex.data.exams)) {
        ex.data.exams.forEach(function (e) {
          if (!e || typeof e !== 'object') return;
          exams.set(e.id, {
            title: e.title ? String(e.title) : '',
            course: e.course ? String(e.course) : '',
            course_id: (e.course_id != null && e.course_id !== '') ? String(e.course_id) : null
          });
        });
      }
      var submissions = sb.data.submissions
        .filter(function (r) { return r && typeof r === 'object'; })
        .map(function (r) { return sealedRow(r, exams); });
      return { view: { bluebook: 'ok', submissions: submissions, names: names, exams: exams }, students: students };
    }).then(null, function () { return sealedState('error'); });
  }

  var sealedPromise = null;
  function sealedFor(sess) {
    if (!sealedPromise) sealedPromise = loadSealed(sess);
    return sealedPromise;
  }

  function sealed() {
    return session().then(sealedFor).then(function (x) { return x.view; }, function () { return sealedState('error').view; });
  }

  // ── Live.roster ──────────────────────────────────────────────────────────
  // The one loader for "my students". Every page that lists or counts students
  // calls this and never keeps its own copy.
  //
  //   GET /students                   the roster (a tenant-scoped session) or ids
  //   GET /students/{id}/readiness    the server's own baseline verdict, per student
  //   Live.sealed()                   sealed exams, plus Bluebook's rosters for
  //                                   courses and email (same single load)
  //
  // Resolves, and never rejects:
  //   ok, error      ok is false when the student list itself could not be read
  //   scoped         true when /students carried a roster (names and counts)
  //   students[]     {id, name, email, courses:[{id,code,name}], approved,
  //                   samples, verdict, lastSealed, sealed, pending}
  //                  name is what the API returned, else the id; email is
  //                  Bluebook's, else null; verdict is the server's word
  //                  ('ready' | 'developing' | 'insufficient') or null;
  //                  lastSealed is an ISO time or null; sealed / pending are
  //                  null unless bluebook is 'ok'
  //   sealedToReview sealed exams with no graded_at, null unless bluebook is 'ok'
  //   bluebook       'ok' | 'off' (not in this workspace, or 403) | 'error'
  //   bluebookOff    bluebook === 'off'
  //   courseCount    distinct Bluebook courses among these students
  //   beyondCap      students past ROSTER_CAP, whose readiness was never asked for
  //                  (they are the last beyondCap entries of students[])
  //   submissions[]  {id, student_id, created_at, graded_at} only: nothing
  //                  Bluebook computed about a submission is passed on

  var VERDICTS = ['ready', 'developing', 'insufficient'];

  function count(v) {
    return (typeof v === 'number' && isFinite(v)) ? v : null;
  }

  function rosterFailure() {
    return {
      ok: false, error: 'Could not load your students', scoped: false, students: [],
      sealedToReview: null, bluebook: 'error', bluebookOff: false,
      courseCount: 0, beyondCap: 0, submissions: []
    };
  }

  function loadRoster(sess) {
    var stP = get(function () { return api('/students'); });
    var slP = sealedFor(sess);

    return stP.then(function (st) {
      var ok = !!(st.ok && st.data);
      var rows = ok && Array.isArray(st.data.roster) ? st.data.roster : null;
      var ids = ok && Array.isArray(st.data.students) ? st.data.students : [];

      // A workspace roster carries each student's name and counts; without one
      // (the open demo) /students lists ids only and the id stands in for the
      // name. The readiness response below then supplies the counts.
      var base = rows
        ? rows.map(function (r) {
            return { id: String(r.id), name: r.name, ac: count(r.authenticated_count), sc: count(r.sample_count), verdict: null };
          })
        : ids.map(function (id) { return { id: String(id), name: '', ac: null, sc: null, verdict: null }; });

      var asked = base.slice(0, ROSTER_CAP);
      var checks = asked.map(function (r) {
        return get(function () { return api('/students/' + encodeURIComponent(r.id) + '/readiness'); });
      });

      return Promise.all([Promise.all(checks), slP]).then(function (all) {
        var sl = all[1], bluebook = sl.view.bluebook;
        asked.forEach(function (r, i) {
          var d = all[0][i] && all[0][i].ok && all[0][i].data;
          if (!d) return;
          if (VERDICTS.indexOf(d.verdict) >= 0) r.verdict = d.verdict;
          if (!rows) { r.ac = count(d.authenticated_count); r.sc = count(d.sample_count); }
        });

        // Keyed by ids the API sent: a Map, so an id like "constructor" is just an id.
        var subs = [], byStudent = new Map(), bbById = new Map();
        try {
          if (bluebook === 'ok') {
            subs = sl.view.submissions.map(function (s) {
              return { id: s.id, student_id: s.student_id, created_at: s.created_at, graded_at: s.graded_at };
            });
            subs.forEach(function (s) {
              var e = byStudent.get(s.student_id);
              if (!e) { e = { n: 0, pending: 0, last: '' }; byStudent.set(s.student_id, e); }
              e.n++;
              if (pendingReview(s)) e.pending++;
              if (s.created_at && s.created_at > e.last) e.last = s.created_at;
            });
            (sl.students || []).forEach(function (x) { bbById.set(x.student_id, x); });
          }
        } catch (e) {
          // Sealed-exam data of an unexpected shape must not hide the roster.
          bluebook = 'error'; subs = []; byStudent = new Map(); bbById = new Map();
        }

        var courseIds = new Set();
        var students = base.map(function (r) {
          var b = bbById.get(r.id), e = byStudent.get(r.id);
          var seen = new Set(), courses = [];
          (b && Array.isArray(b.courses) ? b.courses : []).forEach(function (c) {
            if (!c) return;
            courseIds.add(c.course_id);
            var label = c.code || c.name;
            if (label && !seen.has(label)) {
              seen.add(label);
              courses.push({ id: c.course_id, code: c.code ? String(c.code) : '', name: c.name ? String(c.name) : '' });
            }
          });
          return {
            id: r.id,
            name: String(r.name || r.id),
            email: b && b.email ? String(b.email) : null,
            courses: courses,
            approved: r.ac,
            samples: r.sc,
            verdict: r.verdict,
            lastSealed: bluebook === 'ok' ? ((b && b.last_submitted_at) || (e && e.last) || null) : null,
            sealed: bluebook === 'ok' ? (e ? e.n : 0) : null,
            pending: bluebook === 'ok' ? (e ? e.pending : 0) : null
          };
        });

        return {
          ok: ok,
          error: ok ? null : 'Could not load your students',
          scoped: rows !== null,
          students: students,
          sealedToReview: bluebook === 'ok' ? subs.filter(pendingReview).length : null,
          bluebook: bluebook,
          bluebookOff: bluebook === 'off',
          courseCount: courseIds.size,
          beyondCap: base.length - asked.length,
          submissions: subs
        };
      });
    });
  }

  function roster() {
    return session().then(loadRoster).then(null, rosterFailure);
  }

  function signOut() {
    TOKEN_KEYS.concat(EXTRA_KEYS).forEach(function (k) {
      try { window.localStorage.removeItem(k); } catch (e) { /* storage blocked */ }
    });
    window.location.replace('/index.html');
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', notices);
  else notices();

  window.Live = {
    TOKEN_KEYS: TOKEN_KEYS,
    NOTICE: NOTICE,
    esc: esc,
    api: api,
    session: session,
    notices: notices,
    empty: empty,
    gate: gate,
    roster: roster,
    sealed: sealed,
    signOut: signOut
  };
})(window, document);

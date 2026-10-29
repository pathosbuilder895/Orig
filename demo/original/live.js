/* live.js: the one shared script of the live navy suite (demo/original/).
   No dependencies, no build step. Each page loads it with
   <script src="live.js"></script> before its own script and uses only
   window.Live for data, sign-in state and the testing-phase label.

   Live.TOKEN_KEYS   localStorage keys a sign-in leaves behind
   Live.NOTICE       the testing-phase label, verbatim (the ONLY copy in the suite)
   Live.esc(s)       HTML-escape any value before it goes into innerHTML
   Live.api(p, o)    same-origin fetch with the bearer token (a teacher's principal
                     token, else a student's session token); never throws
   Live.session()    who is looking: demo, signed-in or signed-out
   Live.STUDENT_NOTICE  the testing-phase label the student pages show (the only copy)
   Live.notices()    fills every [data-testing-notice] with the label, and every
                     [data-student-notice] with the student label
   Live.empty(el,t)  an honest empty state inside a card
   Live.gate(el, o)  sign-in / "Original is off" panel, or the session; with
                     {audience:'student'} the same for the student pages
   Live.roster()     the teacher's students with the server's baseline verdicts
   Live.VERDICT_WORDS  the server's baseline verdict in the one set of words every page
                     uses: ready Ready, developing Building, insufficient Needs more
   Live.verdictWord(v) that word, or "Not available" for a missing or unknown verdict
   Live.sealed()     the teacher's sealed exams, copied through one allowlist
   Live.signOut()    forget the session and the kept papers, go to the sign-in page
                     (a student's is Collections', a teacher's the main one)
   Live.keepSignIn(d) keep the fresh sign-in a password change returns; the
                     change ends every earlier one, this page's included (T-79) */
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

  // Papers the Writing State page keeps on this computer (the full text and the
  // results, one key per student, original_portfolio_<id>) and its last result
  // (sessionStorage). On a shared computer they must not outlive the session.
  var PORTFOLIO_PREFIX = 'original_portfolio_';
  var LAST_RESULT_KEY = 'original_last_result';

  var NOTICE = 'Testing phase: Original is not yet validated on real student writing. Treat any result as a reason for a conversation, never as evidence.';

  // The label on the student pages (voice.html, my-work.html): the same
  // testing-phase warning, plus what NORTH_STAR rule 10 says a student must be
  // told about their sealed work. A student never sees the teacher's sentence.
  var STUDENT_NOTICE = 'Testing phase: Original is not yet validated on real student writing. Your teacher may approve your sealed Collections work as reference writing for it, and can undo that approval.';

  var ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return ESCAPES[c]; });
  }

  function read(key) {
    try { return window.localStorage.getItem(key) || ''; } catch (e) { return ''; }
  }

  // Only the token the server returned is kept, never anything typed.
  function keepSignIn(data) {
    if (!data || !data.token) return;
    var key = data.role === 'student' ? 'original_session_token' : 'original_principal_token';
    try { window.localStorage.setItem(key, data.token); } catch (e) { /* storage blocked */ }
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
      // A teacher carries a principal token. A student carries a session token
      // (an account sign-in, or a Bluebook launch link) and never a principal
      // token; the /me/* routes resolve the student from it. Same order as
      // Bluebook's own client.
      var tok = read('original_principal_token') || read('original_session_token');
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

  // Fills every node carrying `attr` with a label: its first sentence in bold.
  function fillNotices(attr, text) {
    var cut = text.indexOf(':') + 1;
    var html = '<b>' + esc(text.slice(0, cut)) + '</b>' + esc(text.slice(cut));
    var nodes = document.querySelectorAll('[' + attr + ']');
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      n.classList.add('live-testing');
      // A value on the attribute names a variant class, e.g. "on-paper".
      (n.getAttribute(attr) || '').split(/\s+/).forEach(function (c) {
        if (c) n.classList.add(c);
      });
      n.setAttribute('role', 'note');
      n.innerHTML = html;
    }
  }

  function notices() {
    fillNotices('data-testing-notice', NOTICE);
    fillNotices('data-student-notice', STUDENT_NOTICE);
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
  // right panel into el (or sends the visitor to the right page) and resolves null.
  //
  // opts.audience 'student' is for the student pages: a student session is
  // allowed (its products are not known here, so a workspace without Original
  // answers 403 to the page's first /me/ call, which the page words itself), a
  // teacher or other staff member is sent to the teacher pages, and anyone else
  // gets the sign-in panel pointing at Bluebook's sign-in: nobody signed in, the
  // open demo (it has no student account), and a launch-link student who holds
  // a student id but no session token (the /me/ routes cannot know who they are).
  function gate(el, opts) {
    var student = !!(opts && opts.audience === 'student');
    return session().then(function (s) {
      if (student) {
        if (s.role === 'student' && read('original_session_token')) return s;
        if (s.mode === 'signed-in' && s.role !== 'student') {
          window.location.replace('index.html');
          return null;
        }
        panel(el, 'Sign in to continue',
          'This page shows your own writing, so it needs you to be signed in as a student.',
          '/bluebook/', 'Sign in to Collections');
        return null;
      }
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
          'Your workspace uses Collections only. Your classes and sealed exams are in Collections.',
          '/bluebook/', 'Open Collections');
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
  //                  that is not a list of sealed exams, including a list with
  //                  a row that is not an object (a half-read list would
  //                  undercount "to review", so none of it is used)
  //   submissions[]  one object per sealed exam, holding exactly SEALED_FIELDS
  //                  plus two derived values: course_id (the exam record's,
  //                  else null) and warning_count (a number: how many warnings
  //                  the sitting recorded). Every copied value is a string, a
  //                  number or a boolean, else null, so a field that arrives as
  //                  an object cannot carry nested keys through the allowlist.
  //                  Nothing else Bluebook sent about a submission (its
  //                  integrity readings, a status label, the warnings
  //                  themselves, the grader, the feedback, the paper text) is
  //                  ever copied out
  //   names          Map(student_id -> name) from Bluebook's rosters
  //   exams          Map(exam_id -> {title, course, course_id})
  //
  // Memoised: the three requests are made once per page load, whoever asks, so
  // every caller gets the same object. It is frozen (the result, the array and
  // each row) and a page copies before it sorts or adds a field. The two Maps
  // cannot be frozen; read them with get() and has() only.
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

  // A value that may leave a Bluebook response: a string, a number or a
  // boolean. Anything else (an object, an array, null) becomes null.
  function scalar(v) {
    var t = typeof v;
    if (t === 'string' || t === 'boolean') return v;
    return (t === 'number' && isFinite(v)) ? v : null;
  }

  // Freezes a list and every object in it. Shared results are read by every
  // page script, so none of them may change what another reads.
  function freezeList(list) {
    list.forEach(function (x) { if (x && typeof x === 'object') Object.freeze(x); });
    return Object.freeze(list);
  }

  function isRow(r) {
    return !!r && typeof r === 'object' && !Array.isArray(r);
  }

  function sealedRow(raw, exams) {
    var out = {};
    SEALED_FIELDS.forEach(function (k) { out[k] = scalar(raw[k]); });
    var e = exams.get(out.exam_id);
    out.course_id = e ? e.course_id : null;
    // Derived, never copied: how many warnings the sitting recorded, as a
    // number. The warnings themselves stay behind.
    out.warning_count = Array.isArray(raw.warnings) ? raw.warnings.length : 0;
    return out;
  }

  function sealedView(state, submissions, names, exams) {
    return Object.freeze({ bluebook: state, submissions: freezeList(submissions), names: names, exams: exams });
  }

  function sealedState(state) {
    return { view: sealedView(state, [], new Map(), new Map()), students: null };
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
      // A row that is not an object means the list cannot be trusted: say so
      // rather than count the rows around it as if the list were whole.
      if (!sb.data.submissions.every(isRow)) return sealedState('error');

      // Keyed by ids the API sent: a Map, so an id like "constructor" is just an id.
      var names = new Map(), exams = new Map(), students = null;
      if (bs.ok && bs.data && Array.isArray(bs.data.students)) {
        students = bs.data.students.filter(function (x) { return x && typeof x === 'object'; });
        students.forEach(function (x) { if (x.name) names.set(x.student_id, String(x.name)); });
      }
      if (ex.ok && ex.data && Array.isArray(ex.data.exams)) {
        ex.data.exams.forEach(function (e) {
          if (!e || typeof e !== 'object') return;
          exams.set(e.id, Object.freeze({
            title: e.title ? String(e.title) : '',
            course: e.course ? String(e.course) : '',
            course_id: (e.course_id != null && e.course_id !== '') ? String(e.course_id) : null
          }));
        });
      }
      var submissions = sb.data.submissions.map(function (r) { return sealedRow(r, exams); });
      return { view: sealedView('ok', submissions, names, exams), students: students };
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
  // Memoised per page load (one in-flight promise): a second call makes no
  // request. The result is frozen (the result, students, each student's
  // courses, submissions): every page shares the one object, so a page copies
  // before it sorts or adds a field. Resolves, and never rejects:
  //   ok, error      ok is false when the student list itself could not be read
  //   scoped         true when /students carried a roster (names and counts)
  //   students[]     {id, name, email, courses:[{id,code,name}], counted,
  //                   samples, verdict, lastSealed, sealed, pending}
  //                  counted is the server's authenticated_count: every sample it
  //                  weighs above zero, a teacher-approved one or a student's own
  //                  upload. It is never "approved"; call it counted. The roster
  //                  carries no provenance, so no approved count exists here.
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

  // The server's baseline verdict (GET /students/{id}/readiness) in the one set of
  // words the whole suite shows. A page never keeps a map of its own and never prints
  // the raw verdict. A missing or unrecognised verdict is "Not available".
  var VERDICT_WORDS = Object.freeze({ ready: 'Ready', developing: 'Building', insufficient: 'Needs more' });
  var VERDICT_UNKNOWN = 'Not available';

  function verdictWord(v) {
    return (typeof v === 'string' && Object.prototype.hasOwnProperty.call(VERDICT_WORDS, v))
      ? VERDICT_WORDS[v] : VERDICT_UNKNOWN;
  }

  function count(v) {
    return (typeof v === 'number' && isFinite(v)) ? v : null;
  }

  // Words across all of a student's reference papers, from a readiness answer:
  // its word_stats mean over sample_count papers. 0 for no papers; null when
  // the answer does not say.
  function wordsIn(d) {
    var n = count(d && d.sample_count);
    if (n === 0) return 0;
    var ws = d && d.word_stats;
    var mean = ws && typeof ws === 'object' ? count(ws.mean) : null;
    return n === null || mean === null ? null : Math.round(mean * n);
  }

  // The least reference writing a student needs before Original's reading of
  // a new piece means anything: 3 papers and 300 words in all. Below it the
  // reading is inconclusive (NORTH_STAR rule 3). It is the rule the alpha
  // test's batch reading uses (docs/alpha/scoring_plan.md, alpha-test-kit
  // branch), and its 3 papers are the floor a sealed exam is held to
  // (Bluebook records INCONCLUSIVE below 3 teacher-approved samples). Returns
  // { met, tone, short, text } for a count of papers and of words.
  var MIN_PAPERS = 3, MIN_WORDS = 300;
  var MIN_RULE = 'at least ' + MIN_PAPERS + ' papers and ' + MIN_WORDS + ' words in all';
  function referenceStatus(papers, words) {
    var p = count(papers), w = count(words);
    var nPapers = function (n) { return n + ' paper' + (n === 1 ? '' : 's'); };
    if (p === null) return { met: null, tone: 'off', short: 'Not known', text: 'The number of papers could not be read just now.' };
    if (p === 0) return { met: false, tone: 'bad', short: 'No papers yet', need: 'Needs ' + MIN_RULE + '.', text: 'No reference papers yet. Add ' + MIN_RULE + '.' };
    var needP = Math.max(0, MIN_PAPERS - p);
    var needW = w === null ? null : Math.max(0, MIN_WORDS - w);
    var have = nPapers(p) + (w === null ? '' : ', ' + w + ' word' + (w === 1 ? '' : 's'));
    if (needP === 0 && needW === 0) {
      return { met: true, tone: 'ok', short: 'Meets the minimum', text: have + ': meets the minimum of ' + MIN_RULE + '.' };
    }
    var adds = [];
    if (needP) adds.push(needP + ' more paper' + (needP === 1 ? '' : 's'));
    if (needW) adds.push('at least ' + needW + ' more word' + (needW === 1 ? '' : 's'));
    if (needW === null && !needP) {
      return { met: null, tone: 'off', short: 'Words not known', text: have + '. The word count could not be read, so check the papers come to 300 words or more.' };
    }
    return {
      met: false, tone: 'warn', short: 'Below the minimum', need: 'Needs ' + adds.join(' and ') + '.',
      text: have + '. Below the minimum of ' + MIN_RULE + ': add ' + adds.join(' and ') + '. Until then Original’s reading is inconclusive.'
    };
  }

  function rosterFailure() {
    return Object.freeze({
      ok: false, error: 'Could not load your students', scoped: false, students: freezeList([]),
      sealedToReview: null, bluebook: 'error', bluebookOff: false,
      courseCount: 0, beyondCap: 0, submissions: freezeList([])
    });
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
            return { id: String(r.id), name: r.name, ac: count(r.authenticated_count), sc: count(r.sample_count), words: null, verdict: null };
          })
        : ids.map(function (id) { return { id: String(id), name: '', ac: null, sc: null, words: null, verdict: null }; });

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
          r.words = wordsIn(d);
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
            courses: freezeList(courses),
            counted: r.ac,
            samples: r.sc,
            words: r.words,
            verdict: r.verdict,
            lastSealed: bluebook === 'ok' ? ((b && b.last_submitted_at) || (e && e.last) || null) : null,
            sealed: bluebook === 'ok' ? (e ? e.n : 0) : null,
            pending: bluebook === 'ok' ? (e ? e.pending : 0) : null
          };
        });

        return Object.freeze({
          ok: ok,
          error: ok ? null : 'Could not load your students',
          scoped: rows !== null,
          students: freezeList(students),
          sealedToReview: bluebook === 'ok' ? subs.filter(pendingReview).length : null,
          bluebook: bluebook,
          bluebookOff: bluebook === 'off',
          courseCount: courseIds.size,
          beyondCap: base.length - asked.length,
          submissions: freezeList(subs)
        });
      });
    });
  }

  // Memoised like Live.sealed: the first call starts the load, every later call
  // in the same page load gets the same answer without a request. The result is
  // frozen because it is shared by every caller.
  var rosterPromise = null;
  function roster() {
    if (!rosterPromise) rosterPromise = session().then(loadRoster).then(null, rosterFailure);
    return rosterPromise;
  }

  // Every localStorage key that starts with the prefix. The keys are collected
  // first and removed afterwards: removing while counting skips entries.
  function keptPaperKeys() {
    var found = [];
    try {
      var ls = window.localStorage;
      for (var i = 0; i < ls.length; i++) {
        var k = ls.key(i);
        if (k && k.indexOf(PORTFOLIO_PREFIX) === 0) found.push(k);
      }
    } catch (e) { /* storage blocked */ }
    return found;
  }

  // A student holds a session token (an account sign-in) or a launch binding (a
  // Bluebook link), never a principal token: the same test loadSession() makes.
  function leavingStudent() {
    if (read('original_principal_token')) return false;
    return read('original_role') === 'student' || !!read('original_session_token') || !!read('bluebook_student_id');
  }

  function signOut() {
    // Ask who is leaving before the keys that say so are removed. A student's
    // way back in is Bluebook's sign-in, not the teachers' page.
    var next = leavingStudent() ? '/bluebook/' : '/index.html';
    TOKEN_KEYS.concat(EXTRA_KEYS, keptPaperKeys()).forEach(function (k) {
      try { window.localStorage.removeItem(k); } catch (e) { /* storage blocked */ }
    });
    try { window.sessionStorage.removeItem(LAST_RESULT_KEY); } catch (e) { /* storage blocked */ }
    window.location.replace(next);
  }

  // On a narrow screen the page's pill strip scrolls inside itself, and the pills past the edge are
  // out of sight. A fade on the edge that has more pills says so (the .fade-start and .fade-end
  // classes, drawn in suite.css), and the strip opens with the current page's pill in view.
  var FADE_SLACK = 4;
  function updateFade(strip) {
    var start = strip.scrollLeft > FADE_SLACK;
    var end = strip.scrollWidth - strip.clientWidth - strip.scrollLeft > FADE_SLACK;
    strip.classList.toggle('fade-start', start);
    strip.classList.toggle('fade-end', end);
  }
  function pillFade() {
    var strips = document.querySelectorAll('.pills');
    for (var i = 0; i < strips.length; i++) {
      (function (strip) {
        var here = strip.querySelector('[aria-current="page"]');
        if (here && strip.scrollWidth > strip.clientWidth) {
          var room = strip.clientWidth - here.offsetWidth;
          strip.scrollLeft = Math.max(0, here.offsetLeft - strip.offsetLeft - room / 2);
        }
        updateFade(strip);
        strip.addEventListener('scroll', function () { updateFade(strip); });
        if (typeof window.addEventListener === 'function') window.addEventListener('resize', function () { updateFade(strip); });
      })(strips[i]);
    }
  }

  function ready() { notices(); pillFade(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready);
  else ready();

  window.Live = {
    TOKEN_KEYS: TOKEN_KEYS,
    NOTICE: NOTICE,
    STUDENT_NOTICE: STUDENT_NOTICE,
    esc: esc,
    api: api,
    session: session,
    notices: notices,
    empty: empty,
    gate: gate,
    roster: roster,
    VERDICT_WORDS: VERDICT_WORDS,
    verdictWord: verdictWord,
    referenceStatus: referenceStatus,
    referenceWords: wordsIn,
    REFERENCE_MINIMUM: MIN_RULE,
    sealed: sealed,
    signOut: signOut,
    keepSignIn: keepSignIn
  };
})(window, document);

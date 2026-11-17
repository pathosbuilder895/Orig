/* paper-profile.js: the teacher-only "About the papers" table (paper_profile,
   original/paper_profile.py), the same builder on Writing State and the
   side-by-side page (evidence.html).

   Descriptive only: how each paper's heading block, section headings,
   citations, quotations and list of sources look. None of it is part of the
   comparison. The server sends evidence.paper_profile only to staff and only
   when PAPER_PROFILE_ENABLED is on; without it, nothing is drawn.

   Every word here is plain; numbers come from the server; nothing from the
   paper's own text is shown. Loaded as window.PaperProfile; node's unit tests
   load it through require(). */
(function (root) {
  'use strict';

  var num = function (v) { return typeof v === 'number' && isFinite(v) ? v : null; };
  var isObj = function (v) { return !!v && typeof v === 'object' && !Array.isArray(v); };
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : (many || one + 's')); }
  function pastLabel(p) {
    var m = typeof p.paper === 'string' ? /^past paper (\d+)$/.exec(p.paper) : null;
    return m ? 'Past paper ' + m[1] : (typeof p.paper === 'string' && p.paper ? p.paper : 'Past paper');
  }

  // One row per fact: [label, function(profile) -> plain text].
  var ROWS = [
    ['List of sources', function (p) {
      var s = isObj(p.sources) ? p.sources : {};
      var n = num(s.count);
      if (!n) return 'None found';
      return plural(n, 'source') + (typeof s.list_heading === 'string' && s.list_heading ? ' under \u201c' + s.list_heading + '\u201d' : '');
    }],
    ['Years of sources', function (p) {
      var s = isObj(p.sources) ? p.sources : {};
      var a = num(s.earliest_year), b = num(s.latest_year);
      if (a == null || b == null) return '\u2013';
      return a === b ? String(a) : a + ' to ' + b;
    }],
    ['Kinds of source', function (p) {
      var k = isObj(p.sources) && isObj(p.sources.kinds) ? p.sources.kinds : {};
      var parts = Object.keys(k).sort().filter(function (name) { return num(k[name]); })
        .map(function (name) { return k[name] + ' ' + name; });
      return parts.length ? parts.join(', ') : '\u2013';
    }],
    ['Citation style', function (p) {
      var c = isObj(p.citation_style) ? p.citation_style : {};
      return typeof c.words === 'string' ? c.words : '\u2013';
    }],
    ['In-text citations', function (p) {
      var c = isObj(p.in_text_citations) ? p.in_text_citations : {};
      var n = num(c.count), r = num(c.per_100_words);
      if (n == null) return '\u2013';
      return n === 0 ? 'None' : n + (r != null ? ' (' + r.toFixed(2) + ' per 100 words)' : '');
    }],
    ['Footnote markers', function (p) { var n = num(p.footnote_markers); return n == null ? '\u2013' : (n === 0 ? 'None' : String(n)); }],
    ['Section headings', function (p) { var n = num(p.headings); return n == null ? '\u2013' : (n === 0 ? 'None' : String(n)); }],
    ['Heading block at the top', function (p) {
      var n = num(p.front_matter_words);
      return n == null ? '\u2013' : (n === 0 ? 'None' : plural(n, 'word'));
    }],
    ['Quotations', function (p) {
      var q = isObj(p.quotes) ? p.quotes : {};
      var s = num(q.short_quotes), b = num(q.block_quote_words);
      if (s == null && b == null) return '\u2013';
      var parts = [];
      parts.push(s ? plural(s, 'short quote') : 'No short quotes');
      if (b) parts.push(plural(b, 'word') + ' in block quotes');
      return parts.join(', ');
    }],
  ];

  // The signs a style guess rests on, for the cell's tooltip.
  function signsOf(p) {
    var c = isObj(p.citation_style) ? p.citation_style : {};
    var signs = Array.isArray(c.signs) ? c.signs.filter(function (s) { return typeof s === 'string'; }) : [];
    return signs.length ? 'Signs: ' + signs.join('; ') + '.' : '';
  }

  // opts.tableClass / opts.noteClass: the page's own classes.
  function table(profile, opts) {
    if (!isObj(profile) || !isObj(profile.this_paper)) return '';
    var o = isObj(opts) ? opts : {};
    var papers = [{ label: 'This paper', p: profile.this_paper }].concat(
      (Array.isArray(profile.past_papers) ? profile.past_papers : []).filter(isObj)
        .map(function (p) { return { label: pastLabel(p), p: p }; }));
    var head = '<tr><th scope="col">About the paper</th>' +
      papers.map(function (c) { return '<th scope="col">' + esc(c.label) + '</th>'; }).join('') + '</tr>';
    var body = ROWS.map(function (row) {
      return '<tr><th scope="row">' + esc(row[0]) + '</th>' + papers.map(function (c) {
        var tip = row[0] === 'Citation style' ? signsOf(c.p) : '';
        return '<td' + (tip ? ' title="' + esc(tip) + '"' : '') + '>' + esc(row[1](c.p)) + '</td>';
      }).join('') + '</tr>';
    }).join('');
    var caveat = isObj(profile.this_paper.citation_style) && typeof profile.this_paper.citation_style.caveat === 'string'
      ? profile.this_paper.citation_style.caveat : '';
    var note = typeof profile.note === 'string' ? profile.note : '';
    return '<table class="' + esc(o.tableClass || 'pp-table') + '"><thead>' + head + '</thead><tbody>' + body + '</tbody></table>' +
      ((note || caveat) ? '<p class="' + esc(o.noteClass || 'pp-note') + '">' + esc([note, caveat ? 'Citation style: ' + caveat.charAt(0).toLowerCase() + caveat.slice(1) : ''].filter(Boolean).join(' ')) + '</p>' : '');
  }
  function has(ev) { return isObj(ev) && isObj(ev.paper_profile) && isObj(ev.paper_profile.this_paper); }

  var api = { table: table, has: has, rows: ROWS.map(function (r) { return r[0]; }) };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.PaperProfile = api;
})(this);

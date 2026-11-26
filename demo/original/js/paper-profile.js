/* paper-profile.js: the teacher-only "About the papers" table (paper_profile,
   original/paper_profile.py), the same builder on Writing State and the
   side-by-side page (evidence.html), and the "Parts of this paper" list with
   the teacher's own control (Writing State, Voice baseline).

   Descriptive only: how each paper's heading block, section headings,
   citations, quotations and list of sources look. None of it is part of the
   comparison. The server sends evidence.paper_profile only to staff and only
   when PAPER_PROFILE_ENABLED is on; without it, nothing is drawn. The parts
   of each paper (title page, abstract, list of sources, notes, an appendix,
   and the "possible" parts the rules were unsure of and measured) come only
   when MATTER_SPLITTER_ENABLED is on too; without them, nothing new is drawn.

   Every word here is plain; numbers come from the server. The only words
   from a paper's own text are a part's first line (short), so the teacher can
   tell which part is which. Loaded as window.PaperProfile; node's unit tests
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

  // ── Parts of the paper (paper_profile.parts) ──
  // One part in plain words: "Title page: set aside, 34 words",
  // "Possible notes: measured, 40 words", "Abstract: measured (your choice), 182 words".
  function partName(part) {
    var label = typeof part.label === 'string' && part.label ? part.label : 'Part';
    return part.possible === true ? 'Possible ' + label.charAt(0).toLowerCase() + label.slice(1) : label;
  }
  function partWords(part) {
    if (!isObj(part)) return '';
    var what = part.status === 'set_aside' ? 'set aside' : 'measured';
    if (part.by === 'teacher') what += ' (your choice)';
    var n = num(part.words);
    return partName(part) + ': ' + what + (n == null ? '' : ', ' + plural(n, 'word'));
  }
  function partsOf(p) { return isObj(p) && Array.isArray(p.parts) ? p.parts.filter(isObj) : null; }
  function partsCell(p) {
    var parts = partsOf(p);
    if (!parts) return '\u2013';
    return parts.length ? parts.map(function (x) { return '<div class="pp-pl">' + esc(partWords(x)) + '</div>'; }).join('') : 'Nothing set aside';
  }

  // Ranges as sorted, merged [start, end] pairs.
  function rangesOf(v) {
    return (Array.isArray(v) ? v : []).filter(function (r) {
      return Array.isArray(r) && r.length === 2 && num(r[0]) != null && num(r[1]) != null && r[0] < r[1];
    }).map(function (r) { return [r[0], r[1]]; });
  }
  function union(ranges) {
    var out = [];
    rangesOf(ranges).sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; }).forEach(function (r) {
      var last = out[out.length - 1];
      if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1]);
      else out.push([r[0], r[1]]);
    });
    return out;
  }
  function minus(kept, cut) {
    var out = [];
    var c = union(cut);
    union(kept).forEach(function (r) {
      var pos = r[0];
      c.forEach(function (x) {
        if (x[1] <= pos || x[0] >= r[1]) return;
        if (x[0] > pos) out.push([pos, x[0]]);
        pos = Math.max(pos, x[1]);
      });
      if (pos < r[1]) out.push([pos, r[1]]);
    });
    return out;
  }
  // The teacher's choice in force for a paper, as the server sent it with the
  // parts (paper_profile.choice, or the past-paper parts answer itself).
  function choiceOf(p) {
    var c = isObj(p) && isObj(p.choice) ? p.choice : (isObj(p) ? p : {});
    return { exclude_ranges: union(c.exclude_ranges), include_ranges: union(c.include_ranges) };
  }
  // The choice after the teacher clicks one part's button. action: 'set_aside' or 'measured'.
  // Back to what the rules do for that part: its ranges leave both lists.
  function nextChoice(current, part, action) {
    var cur = isObj(current) ? current : {};
    var ex = rangesOf(cur.exclude_ranges), inc = rangesOf(cur.include_ranges);
    var mine = rangesOf(isObj(part) ? part.ranges : null);
    ex = minus(ex, mine); inc = minus(inc, mine);
    if (action !== part.rules_status) {
      if (action === 'set_aside') ex = union(ex.concat(mine));
      else inc = union(inc.concat(mine));
    }
    return { exclude_ranges: union(ex), include_ranges: union(inc) };
  }
  // The list with a button per part. opts.listClass / opts.idPrefix: the page's own.
  function partsList(parts, opts) {
    var o = isObj(opts) ? opts : {};
    var list = (Array.isArray(parts) ? parts : []).filter(isObj);
    if (!list.length) return '';
    return '<ul class="' + esc(o.listClass || 'pp-parts') + '">' + list.map(function (p, i) {
      var next = p.status === 'set_aside' ? 'measured' : 'set_aside';
      var line = typeof p.first_line === 'string' && p.first_line ? '<span class="pp-part-line">\u201c' + esc(p.first_line) + '\u201d</span>' : '';
      return '<li class="pp-part' + (p.status === 'set_aside' ? ' aside' : ' kept') + (p.possible === true ? ' maybe' : '') + '">' +
        '<span class="pp-part-what">' + esc(partWords(p)) + '</span>' + line +
        (o.control === false ? '' : '<button type="button" class="pp-part-btn" data-part="' + i + '" data-act="' + next + '">' +
          (next === 'set_aside' ? 'Set this part aside' : 'Measure this part') + '</button>') +
        '</li>';
    }).join('') + '</ul>';
  }

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
    // Parts of the paper: only when the server listed them (splitter on).
    if (papers.some(function (c) { return partsOf(c.p); })) {
      body = '<tr class="pp-parts-row"><th scope="row">Parts of the paper</th>' +
        papers.map(function (c) { return '<td>' + partsCell(c.p) + '</td>'; }).join('') + '</tr>' + body;
    }
    var caveat = isObj(profile.this_paper.citation_style) && typeof profile.this_paper.citation_style.caveat === 'string'
      ? profile.this_paper.citation_style.caveat : '';
    var note = typeof profile.note === 'string' ? profile.note : '';
    return '<table class="' + esc(o.tableClass || 'pp-table') + '"><thead>' + head + '</thead><tbody>' + body + '</tbody></table>' +
      ((note || caveat) ? '<p class="' + esc(o.noteClass || 'pp-note') + '">' + esc([note, caveat ? 'Citation style: ' + caveat.charAt(0).toLowerCase() + caveat.slice(1) : ''].filter(Boolean).join(' ')) + '</p>' : '');
  }
  function has(ev) { return isObj(ev) && isObj(ev.paper_profile) && isObj(ev.paper_profile.this_paper); }

  function hasParts(ev) { return has(ev) && !!partsOf(ev.paper_profile.this_paper); }

  var api = {
    table: table, has: has, rows: ROWS.map(function (r) { return r[0]; }),
    hasParts: hasParts, partWords: partWords, partsList: partsList,
    choiceOf: choiceOf, nextChoice: nextChoice,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.PaperProfile = api;
})(this);

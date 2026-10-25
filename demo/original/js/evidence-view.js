/* evidence-view.js: the words on the side-by-side page (evidence.html), built
   only from the numbers in the staff evidence payload (ADR-013, the score
   response's `evidence` field). Nothing here invents a reason or a finding:
   every sentence is a template filled with values the server sent, and every
   sentence passes the banned-wording check before a page shows it.

   Loaded by evidence.html as window.EvidenceView; node's unit tests load the
   same file through require() (demo/bluebook/unit/evidence-view.test.mjs). */
(function (root) {
  'use strict';

  // Wording a teacher page never uses (tests/test_alpha_polish.py BANNED, plus
  // the product's own rules): detection and misconduct words, accuracy claims.
  var BANNED = [
    /\bai[- ]detect/i,
    /\bcheat/i,
    /authorship verification/i,
    /fingerprint/i,
    /\baccura(?:te|cy|tely)\b/i,
    /generated prose/i,
    /misconduct/i,
    /\bAI\b/,
  ];

  function isClean(text) {
    var s = String(text == null ? '' : text);
    for (var i = 0; i < BANNED.length; i++) if (BANNED[i].test(s)) return false;
    return true;
  }
  // The text if it is clean, else the fallback (itself checked; '' if not).
  function clean(text, fallback) {
    if (isClean(text)) return String(text == null ? '' : text);
    return isClean(fallback) ? String(fallback == null ? '' : fallback) : '';
  }

  var num = function (v) { return typeof v === 'number' && isFinite(v) ? v : null; };
  var DASH = '\u2013';

  // Three significant figures without exponent, like the server's ".3g".
  function fmt(v) {
    v = num(v);
    if (v == null) return DASH;
    if (v === 0) return '0';
    var a = Math.abs(v);
    if (a >= 1000) return String(Math.round(v));
    return String(Number(v.toPrecision(3)));
  }
  function signed(v) {
    v = num(v);
    if (v == null) return DASH;
    if (v === 0) return '0';
    return (v > 0 ? '+' : '\u2212') + fmt(Math.abs(v));
  }
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : (many || one + 's')); }

  function listWords(items) {
    if (items.length <= 1) return items.join('');
    if (items.length === 2) return items[0] + ' and ' + items[1];
    return items.slice(0, -1).join(', ') + ' and ' + items[items.length - 1];
  }

  // "past paper 2" -> the stored assignment name, else "Past paper 2".
  function paperName(label, papers) {
    var l = String(label || '');
    if (Array.isArray(papers)) {
      for (var i = 0; i < papers.length; i++) {
        var p = papers[i];
        if (p && p.paper === l && typeof p.assignment === 'string' && p.assignment.trim()) return p.assignment.trim();
      }
    }
    if (l === 'this paper') return 'This paper';
    return l.charAt(0).toUpperCase() + l.slice(1);
  }

  var ACTIVE = { located: true, whole_text: true };
  function isActive(f) { return !!f && ACTIVE[f.kind] === true; }

  // A comparison measurement (kind "placeholder") that has a value of its own
  // for this paper while every past paper has the same one: on the live
  // scoring path Original computes these for the new paper against the past
  // papers, and a past paper gets the placeholder. The two numbers are not
  // measured the same way, so they are listed with that said, never counted.
  function isOneSided(f) {
    if (!f || f.kind !== 'placeholder') return false;
    var eng = f.engine_scale || {};
    var mine = num(eng.this_paper);
    var past = Array.isArray(eng.past_papers) ? eng.past_papers : [];
    if (mine == null || !past.length) return false;
    var first = num(past[0] && past[0].value);
    if (first == null) return false;
    for (var i = 1; i < past.length; i++) if (num(past[i] && past[i].value) !== first) return false;
    return mine !== first;
  }
  // Every paper, this one and the past ones, has the same value.
  function isConstant(f) {
    var eng = (f && f.engine_scale) || {};
    var vals = [num(eng.this_paper)].concat((eng.past_papers || []).map(function (p) { return num(p && p.value); }));
    for (var i = 1; i < vals.length; i++) if (vals[i] !== vals[0]) return false;
    return true;
  }
  // On the page's full list: compared measurements, plus any other whose
  // papers do not all share one value (so it is not hidden as "not used").
  function isListed(f) { return isActive(f) || (!!f && typeof f === 'object' && !isConstant(f)); }
  function oneSidedNote(f) {
    var eng = f.engine_scale || {};
    var n = (eng.past_papers || []).length;
    return 'This paper: ' + fmt(eng.this_paper) + ' (on Original\u2019s 0 to 1 scale). ' +
      (n === 1 ? 'The past paper has ' : 'Every past paper has ') + fmt(eng.past_papers[0].value) +
      ', the placeholder Original gives a paper when this comparison is not computed for it. ' +
      'The two numbers are not measured the same way, so this gap says little on its own.';
  }

  // The numbers a sentence about one measurement may use: plain units when the
  // server sent them, else Original's 0 to 1 scale.
  function numbersOf(f) {
    var eng = f.engine_scale || {};
    var pl = f.plain && typeof f.plain === 'object' ? f.plain : null;
    var src = pl || { this_paper: eng.this_paper, past_papers: eng.past_papers, past_range: eng.past_range };
    var past = Array.isArray(src.past_papers) ? src.past_papers.filter(function (p) { return p && num(p.value) != null; }) : [];
    var range = Array.isArray(src.past_range) ? src.past_range : null;
    return {
      unit: pl ? String(pl.unit || '') : 'on Original\u2019s 0 to 1 scale',
      plain: !!pl,
      thisValue: num(src.this_paper),
      past: past,
      lo: range ? num(range[0]) : null,
      hi: range ? num(range[1]) : null,
    };
  }

  // Where this paper sits against the past papers, by the engine's own flag
  // (computed on the 0 to 1 scale the score used) and its direction.
  function position(f) {
    var eng = f.engine_scale || {};
    var past = Array.isArray(eng.past_papers) ? eng.past_papers : [];
    if (!past.length) return 'none';
    if (!eng.outside_past_range) return 'within';
    return num(eng.difference) > 0 ? 'above' : 'below';
  }
  function positionSentence(f) {
    var n = ((f.engine_scale || {}).past_papers || []).length;
    var pos = position(f);
    if (pos === 'none') return 'There are no past papers to compare with.';
    if (pos === 'within') return n === 1 ? 'On Original\u2019s 0 to 1 scale this paper matches the past paper.' : 'On Original\u2019s 0 to 1 scale this paper is within the past papers\u2019 range.';
    if (n === 1) return 'On Original\u2019s 0 to 1 scale this paper is ' + (pos === 'above' ? 'above' : 'below') + ' the past paper.';
    return 'On Original\u2019s 0 to 1 scale this paper is ' + (pos === 'above' ? 'above the highest' : 'below the lowest') + ' of the ' + n + ' past papers.';
  }

  function valuesLine(nums, papers) {
    return nums.past.map(function (p) { return paperName(p.paper, papers) + ' ' + fmt(p.value); });
  }

  // One line under a card's title: this paper's number beside the past range.
  function oneLine(f) {
    var n = numbersOf(f);
    var range = n.lo == null ? '' : (n.lo === n.hi ? fmt(n.lo) : fmt(n.lo) + ' to ' + fmt(n.hi));
    var s = 'This paper ' + fmt(n.thisValue) + (range ? '; past papers ' + range : '') + ' (' + n.unit + ').';
    return clean(s, '');
  }

  // "What to notice": counts and values only, then where the paper sits.
  function noteFor(f, papers) {
    if (!f || typeof f !== 'object') return '';
    if (isOneSided(f)) return clean(oneSidedNote(f), '');
    var n = numbersOf(f);
    var parts = [];
    var tp = f.this_paper && typeof f.this_paper === 'object' ? f.this_paper : null;
    var pp = f.past_papers && typeof f.past_papers === 'object' ? f.past_papers : null;
    var ex = tp && Array.isArray(tp.examples) && tp.examples[0];
    var counted = f.kind === 'located' && tp && num(tp.count) != null && pp && Array.isArray(pp.per_paper) &&
      !(ex && num(ex.words) != null) && typeof f.what_is_marked === 'string';
    if (counted) {
      parts.push('Counting each ' + f.what_is_marked + ': this paper has ' + tp.count + (n.thisValue != null ? ' (' + fmt(n.thisValue) + ' ' + n.unit + ')' : '') + '.');
      var each = pp.per_paper.map(function (p) {
        var v = null;
        n.past.forEach(function (q) { if (q.paper === p.paper) v = q.value; });
        return paperName(p.paper, papers) + ' has ' + p.count + (v != null ? ' (' + fmt(v) + ')' : '');
      });
      if (each.length) parts.push(listWords(each) + '.');
    } else {
      parts.push('This paper: ' + fmt(n.thisValue) + ' (' + n.unit + ').');
      var vals = valuesLine(n, papers);
      if (vals.length) parts.push('Past papers: ' + listWords(vals) + '.');
    }
    parts.push(positionSentence(f));
    return clean(parts.join(' '), positionSentence(f));
  }

  // The summary at the top, from the full list's own flags and kinds.
  // groupName(group number) gives a readable name, or '' to leave it out.
  function summarize(ev, groupName) {
    var full = ev && Array.isArray(ev.all_features) ? ev.all_features : [];
    var active = full.filter(isActive);
    var outside = active.filter(function (f) { return f.engine_scale && f.engine_scale.outside_past_range; });
    var unused = full.filter(function (f) { return f && !isListed(f); });
    var off = unused.filter(function (f) { return f.kind === 'off'; }).length;
    var placeholder = unused.filter(function (f) { return f.kind === 'placeholder'; }).length;
    var oneSided = full.filter(isOneSided).length;
    var otherListed = full.filter(function (f) { return isListed(f) && !isActive(f) && !isOneSided(f); }).length;
    var groups = [];
    var byGroup = {};
    active.forEach(function (f) {
      var g = num(f.group);
      var key = String(g);
      if (!byGroup[key]) { byGroup[key] = { group: g, name: groupName ? String(groupName(g) || '') : '', active: 0, outside: 0 }; groups.push(byGroup[key]); }
      byGroup[key].active += 1;
      if (f.engine_scale && f.engine_scale.outside_past_range) byGroup[key].outside += 1;
    });
    groups.sort(function (a, b) { return a.group - b.group; });
    var pastCount = 0;
    if (full.length && full[0].engine_scale && Array.isArray(full[0].engine_scale.past_papers)) pastCount = full[0].engine_scale.past_papers.length;
    return {
      total: full.length, active: active.length, outside: outside.length, within: active.length - outside.length,
      off: off, placeholder: placeholder, oneSided: oneSided, otherListed: otherListed, groups: groups, pastCount: pastCount,
      topCount: Array.isArray(ev && ev.features) ? ev.features.length : 0,
    };
  }

  // opts.groups === false leaves the by-group sentence out (a page showing
  // the same counts as a table).
  function summarySentences(sum, opts) {
    var out = [];
    if (!sum.active) return ['No measurement in this analysis could be compared with past papers.'];
    out.push('This paper is outside the past-paper range on ' + sum.outside + ' of ' + sum.active +
      ' active measurements, and within that range on ' + sum.within + '.');
    if (sum.pastCount) {
      out.push('Each range is simply the lowest to the highest of ' + plural(sum.pastCount, 'past paper') +
        ', so a paper the student wrote can still fall outside it on many measurements, especially with few past papers.');
    }
    var named = sum.groups.filter(function (g) { return g.name; });
    if (named.length && !(opts && opts.groups === false)) {
      out.push('By group: ' + named.map(function (g) { return g.name + ' ' + g.outside + ' of ' + g.active + ' outside'; }).join('; ') + '.');
    }
    if (sum.oneSided) {
      out.push(plural(sum.oneSided, 'comparison measurement') + ' had a value for this paper only, with every past paper on the placeholder value, so ' +
        (sum.oneSided === 1 ? 'it is' : 'they are') + ' listed below but not counted here.');
    }
    if (sum.otherListed) {
      out.push(plural(sum.otherListed, 'measurement') + ' that Original does not normally compare had differing values here, so ' +
        (sum.otherListed === 1 ? 'it is' : 'they are') + ' listed below but not counted here.');
    }
    if (sum.off || sum.placeholder) {
      var bits = [];
      if (sum.off) bits.push(plural(sum.off, 'measurement') + ' switched off');
      if (sum.placeholder) bits.push(plural(sum.placeholder, 'measurement') + ' not computed for these papers');
      out.push('Not used in this comparison: ' + listWords(bits) + '.');
    }
    return out.map(function (s) { return clean(s, ''); }).filter(Boolean);
  }

  // Where it held steady: active measurements inside the past range, closest
  // to the past-paper average first. Up to `located` text cards (both sides
  // have a sentence to show) and up to `whole` whole-text ones.
  function steady(ev, located, whole) {
    var full = ev && Array.isArray(ev.all_features) ? ev.all_features : [];
    var inside = full.filter(function (f) {
      return isActive(f) && f.engine_scale && !f.engine_scale.outside_past_range &&
        (f.engine_scale.past_papers || []).length > 0;
    }).slice();
    inside.sort(function (a, b) {
      return Math.abs(num(a.engine_scale.difference) || 0) - Math.abs(num(b.engine_scale.difference) || 0) || a.rank - b.rank;
    });
    var withText = function (f) {
      return f.kind === 'located' && f.this_paper && f.past_papers &&
        (f.this_paper.examples || []).length > 0 && (f.past_papers.examples || []).length > 0;
    };
    var a = inside.filter(withText).slice(0, located == null ? 3 : located);
    var b = inside.filter(function (f) { return f.kind === 'whole_text'; }).slice(0, whole == null ? 2 : whole);
    return a.concat(b);
  }

  // A quote cut into the text before, the counted words and the text after.
  // The counted words are used only when they are exactly the slice of the
  // passage the offsets name; otherwise nothing is marked.
  function markParts(q) {
    var p = String(q && q.passage || '');
    var a = num(q && q.match_start) - num(q && q.passage_start);
    var b = num(q && q.match_end) - num(q && q.passage_start);
    var ok = isFinite(a) && isFinite(b) && a >= 0 && b > a && b <= p.length && p.slice(a, b) === q.match;
    if (!ok) return { before: p, mark: '', after: '' };
    return { before: p.slice(0, a), mark: p.slice(a, b), after: p.slice(b) };
  }

  var API = {
    BANNED: BANNED, isClean: isClean, clean: clean, fmt: fmt, signed: signed, plural: plural,
    paperName: paperName, isActive: isActive, isOneSided: isOneSided, isConstant: isConstant, isListed: isListed, numbersOf: numbersOf, position: position,
    positionSentence: positionSentence, oneLine: oneLine, noteFor: noteFor,
    summarize: summarize, summarySentences: summarySentences, steady: steady, markParts: markParts,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
  else root.EvidenceView = API;
})(this);

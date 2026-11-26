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

  // A comparison measurement (kind "not_compared"): Original computes it for
  // this paper against the past papers, but past papers have no value for it,
  // so the score leaves it out and so does this page's comparison.
  var NOT_COMPARED_WORDS = 'not compared: past papers have no value for this';
  // The same words as a sentence on their own: "Not compared: ... this."
  var NOT_COMPARED_LINE = NOT_COMPARED_WORDS.charAt(0).toUpperCase() + NOT_COMPARED_WORDS.slice(1) + '.';
  function isNotCompared(f) { return !!f && f.kind === 'not_compared'; }
  // Every paper, this one and the past ones, has the same value.
  function isConstant(f) {
    var eng = (f && f.engine_scale) || {};
    var vals = [num(eng.this_paper)].concat((eng.past_papers || []).map(function (p) { return num(p && p.value); }));
    for (var i = 1; i < vals.length; i++) if (vals[i] !== vals[0]) return false;
    return true;
  }
  // On the page's full list: compared measurements, plus any other whose
  // papers do not all share one value (so it is not hidden as "not used").
  // Not-compared measurements are never listed, whatever their numbers.
  function isListed(f) {
    return isActive(f) || (!!f && typeof f === 'object' && !isNotCompared(f) && !isConstant(f));
  }
  function notComparedNote(f) {
    return NOT_COMPARED_LINE;
  }

  // ── Numbers a teacher can read (one formatter for every page) ──
  // The server's `display` (original/evidence_features.py display_info) says
  // how a habit's number is shown:
  //   percent:  a true proportion, "38% of sentences" (one decimal under 10%);
  //   unit:     a count rate or everyday measure, "2.4 commas per 100 words";
  //   category: a code for a kind, "numbered lists";
  //   compare:  no everyday unit and no true share: only a plain comparison
  //             with the past papers ("higher than all 3 past papers"), the
  //             exact position kept for a details line, never as a percent;
  //   hidden:   not shown to teachers.
  // The plain (raw) values the server sent are used when present; otherwise
  // the engine's own value only where it IS the raw value (engine_is_raw).
  // Any other case falls back to compare. No value is changed, only written.
  function displayOf(f) {
    var d = f && f.display;
    return d && typeof d === 'object' && !Array.isArray(d) ? d : { style: 'compare' };
  }
  // The habits never shown to a teacher, also when no `display` was sent (the
  // numbers-only pages): original/evidence_features.py HIDDEN_CODES, kept
  // equal by tests/test_evidence_display.py.
  var HIDDEN_CODES = ['conclusion_strategy_score'];
  function isHidden(f) {
    return displayOf(f).style === 'hidden' || (!!f && HIDDEN_CODES.indexOf(f.code) >= 0);
  }

  // A percent: whole number, one decimal under 10% (never "-0%").
  function pct(v) {
    v = num(v);
    if (v == null) return DASH;
    var p = v * 100;
    if (Math.abs(p) < 0.05) return '0%';
    if (Math.abs(p) < 10) return String(Math.round(p * 10) / 10) + '%';
    return String(Math.round(p)) + '%';
  }
  // A plain-unit number: whole numbers from 100, one decimal from 1, else two
  // significant figures ("18.4", "2.4", "0.43").
  function unitNum(v) {
    v = num(v);
    if (v == null) return DASH;
    var a = Math.abs(v);
    if (a === 0) return '0';
    if (a >= 100) return String(Math.round(v));
    if (a >= 1) return v.toFixed(1);
    return String(Number(v.toPrecision(2)));
  }

  // { mode, unit, plain, thisValue, past, lo, hi, show(v), words(v) }
  // `plain` is true when the numbers mean something to a teacher as they are
  // (mode percent, unit or category); for compare it is false and the page
  // says where this paper sits in words (compareWords) instead.
  function readable(f) {
    var spec = displayOf(f);
    var eng = (f && f.engine_scale) || {};
    var pl = f && f.plain && typeof f.plain === 'object' ? f.plain : null;
    var style = spec.style || 'compare';
    var src = pl;
    if (!src && spec.engine_is_raw === true && (style === 'percent' || style === 'unit' || style === 'category')) {
      src = { this_paper: eng.this_paper, past_papers: eng.past_papers, past_range: eng.past_range };
    }
    if (!src || style === 'compare' || style === 'hidden') {
      src = { this_paper: eng.this_paper, past_papers: eng.past_papers, past_range: eng.past_range };
      style = style === 'hidden' ? 'hidden' : 'compare';
    }
    var past = Array.isArray(src.past_papers) ? src.past_papers.filter(function (p) { return p && num(p.value) != null; }) : [];
    var range = Array.isArray(src.past_range) ? src.past_range : null;
    var lo = range ? num(range[0]) : null, hi = range ? num(range[1]) : null;
    var unit = '', show;
    if (style === 'percent') {
      unit = String(spec.of || '');
      show = pct;
    } else if (style === 'unit') {
      unit = String(spec.unit || (pl && pl.unit) || '');
      var scale = num(spec.scale), cap = num(spec.cap);
      show = function (v) {
        v = num(v);
        if (v == null) return DASH;
        if (scale == null) return unitNum(v);
        if (cap != null && v >= cap) return unitNum(cap * scale) + ' or more';
        return unitNum(v * scale);
      };
    } else if (style === 'category') {
      var labels = spec.labels && typeof spec.labels === 'object' ? spec.labels : {};
      show = function (v) {
        v = num(v);
        if (v == null) return DASH;
        var key = String(Number(v.toFixed(4)));
        return Object.prototype.hasOwnProperty.call(labels, key) ? String(labels[key]) : 'a mix of list styles';
      };
    } else {
      show = function (v) { return fmt(v); };
    }
    var words = function (v) {
      var t = show(v);
      if (style === 'category' || !unit || t === DASH) return t;
      return t + ' ' + unit;
    };
    return {
      mode: style, unit: unit, plain: style === 'percent' || style === 'unit' || style === 'category',
      thisValue: num(src.this_paper), past: past, lo: lo, hi: hi, show: show, words: words,
      neutral: typeof spec.neutral === 'string' ? spec.neutral : '',
    };
  }
  // One plain value in words, for a page holding a habit's `display` and its
  // plain value but no full entry (Writing State's past-paper mode).
  function valueWords(display, unit, v) {
    return readable({ display: display, plain: { unit: unit, this_paper: v, past_papers: [] } }).words(v);
  }
  // Kept name: every page reads a habit's numbers through this.
  function numbersOf(f) { return readable(f); }

  // A range of shown values, "20% to 25%" (one value when they are equal).
  function rangeText(n) {
    if (n.lo == null || n.hi == null) return '';
    var a = n.show(n.lo), b = n.show(n.hi);
    return a === b ? a : a + ' to ' + b;
  }
  function rangeWords(n) {
    var r = rangeText(n);
    if (!r || n.mode === 'category' || !n.unit) return r;
    return r + ' ' + n.unit;
  }
  // The neutral sentence, only when a shown value is exactly the 0.5 an
  // extractor records when there is nothing to count.
  function neutralNote(n) {
    if (!n.neutral) return '';
    var vals = [n.thisValue].concat(n.past.map(function (p) { return num(p.value); }));
    return vals.some(function (v) { return v === 0.5; }) ? n.neutral : '';
  }

  // Where this paper sits against each past paper, in words, from the
  // engine's own values (the same order as any plain value: NORM_BOUNDS is
  // a straight line). "higher than all 3 past papers", "lower than 2 of 3
  // past papers", "within the range of the past papers".
  function compareWords(f) {
    var eng = (f && f.engine_scale) || {};
    var t = num(eng.this_paper);
    var past = (Array.isArray(eng.past_papers) ? eng.past_papers : []).map(function (p) { return num(p && p.value); })
      .filter(function (v) { return v != null; });
    var n = past.length;
    if (t == null || !n) return '';
    var eps = 1e-9, above = 0, below = 0;
    past.forEach(function (v) { if (t > v + eps) above += 1; else if (t < v - eps) below += 1; });
    if (n === 1) return above ? 'higher than the past paper' : below ? 'lower than the past paper' : 'the same as the past paper';
    var all = n === 2 ? 'both past papers' : 'all ' + n + ' past papers';
    if (above === n) return 'higher than ' + all;
    if (below === n) return 'lower than ' + all;
    if (!above && !below) return 'the same as ' + all;
    if (above > below) return 'higher than ' + above + ' of ' + n + ' past papers';
    if (below > above) return 'lower than ' + below + ' of ' + n + ' past papers';
    return 'within the range of the past papers';
  }
  // The exact numbers behind a plain comparison, worded as a position (never a
  // share or a percent). For a details line or a tooltip only.
  function positionDetail(f) {
    var eng = (f && f.engine_scale) || {};
    var t = num(eng.this_paper);
    if (t == null) return '';
    var past = (Array.isArray(eng.past_papers) ? eng.past_papers : []).map(function (p) { return num(p && p.value); })
      .filter(function (v) { return v != null; });
    var two = function (v) { return v.toFixed(2); };
    var lo = past.length ? Math.min.apply(null, past) : null, hi = past.length ? Math.max.apply(null, past) : null;
    var pastText = lo == null ? '' : '; past papers ' + (two(lo) === two(hi) ? two(lo) : two(lo) + ' to ' + two(hi));
    return clean('Exact position in the range Original expects for this habit (low end 0.00, high end 1.00; a position, not a share or a count): this paper ' +
      two(t) + pastText + '.', '');
  }

  // Where this paper sits against the past papers, by the engine's own flag
  // (computed on the scale the score used) and its direction.
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
    if (pos === 'within') return n === 1 ? 'This paper matches the past paper.' : 'This paper is within the past papers’ range.';
    if (n === 1) return 'This paper is ' + (pos === 'above' ? 'above' : 'below') + ' the past paper.';
    return 'This paper is ' + (pos === 'above' ? 'above the highest' : 'below the lowest') + ' of the ' + n + ' past papers.';
  }

  function valuesLine(nums, papers) {
    return nums.past.map(function (p) { return paperName(p.paper, papers) + ' ' + nums.show(p.value); });
  }

  // One line under a card's title: this paper's number beside the past range,
  // or, with no everyday unit, where it sits in words.
  function oneLine(f) {
    var n = readable(f);
    if (!n.plain) {
      var cw = compareWords(f);
      return cw ? clean('This paper is ' + cw + '.', '') : '';
    }
    var range = rangeText(n);
    var s = 'This paper ' + n.show(n.thisValue) + (range ? '; past papers ' + range : '') + (n.unit && n.mode !== 'category' ? ' (' + n.unit + ')' : '') + '.';
    return clean(s, '');
  }

  // "What to notice": counts and values only, then where the paper sits.
  function noteFor(f, papers) {
    if (!f || typeof f !== 'object') return '';
    if (isNotCompared(f)) return clean(notComparedNote(f), '');
    var n = readable(f);
    var parts = [];
    if (!n.plain) {
      var cw = compareWords(f);
      parts.push(cw ? 'This paper is ' + cw + '.' : positionSentence(f));
      return clean(parts.join(' '), '');
    }
    var tp = f.this_paper && typeof f.this_paper === 'object' ? f.this_paper : null;
    var pp = f.past_papers && typeof f.past_papers === 'object' ? f.past_papers : null;
    var ex = tp && Array.isArray(tp.examples) && tp.examples[0];
    var counted = f.kind === 'located' && tp && num(tp.count) != null && pp && Array.isArray(pp.per_paper) &&
      !(ex && num(ex.words) != null) && typeof f.what_is_marked === 'string';
    if (counted) {
      parts.push('Counting each ' + f.what_is_marked + ': this paper has ' + tp.count + (n.thisValue != null ? ' (' + n.words(n.thisValue) + ')' : '') + '.');
      var each = pp.per_paper.map(function (p) {
        var v = null;
        n.past.forEach(function (q) { if (q.paper === p.paper) v = q.value; });
        return paperName(p.paper, papers) + ' has ' + p.count + (v != null ? ' (' + n.show(v) + ')' : '');
      });
      if (each.length) parts.push(listWords(each) + '.');
    } else {
      parts.push('This paper: ' + n.words(n.thisValue) + '.');
      var vals = valuesLine(n, papers);
      if (vals.length) parts.push('Past papers: ' + listWords(vals) + '.');
    }
    parts.push(positionSentence(f));
    var neutral = neutralNote(n);
    if (neutral) parts.push(neutral);
    return clean(parts.join(' '), positionSentence(f));
  }

  // "What to notice", in plain words: which way this paper sits against the
  // past papers, how far (this paper's number beside the past range), and a
  // fixed caution chosen by where it sits. No cause is named that the numbers
  // do not show. noteFor stays the numbers line; this is the sentence above it.
  var CAUTION = 'A shift like this can come from a new topic, genre, length, revision or permitted help; on its own it does not show who wrote the paper.';
  var WHOLE_TEXT_WORDS = 'It is measured across the whole text, so there is no single sentence to quote.';
  // A name inside a sentence: each word loses its capital only when it is an
  // ordinary capitalised word (second letter lowercase), so acronyms ("POS")
  // and the proper nouns below keep theirs.
  var PROPER = { Flesch: true, Kincaid: true, Latin: true, English: true, Greek: true, Hebrew: true };
  function habitName(f) {
    var nm = String(f.name == null ? '' : f.name).trim();
    if (!nm) return 'this habit';
    return nm.replace(/[A-Za-z][A-Za-z.'\u2019]*/g, function (w) {
      if (PROPER[w] || !/^[A-Z][a-z]/.test(w)) return w;
      return w.charAt(0).toLowerCase() + w.slice(1);
    });
  }
  function rangeBrackets(f) {
    var n = readable(f);
    if (!n.plain || n.thisValue == null || n.lo == null || n.hi == null) return '';
    var unit = n.unit && n.mode !== 'category' ? ' ' + n.unit : '';
    return ' (' + n.show(n.thisValue) + ' against ' + rangeText(n) + unit + ')';
  }
  // The sentence a whole-text habit carries: the server's own note (a
  // whole-paper pattern, or why it is numbers only), else the generic words.
  function wholeWords(f) {
    var note = f && typeof f.note === 'string' ? clean(f.note, '') : '';
    return note || WHOLE_TEXT_WORDS;
  }
  function noticeFor(f) {
    if (!f || typeof f !== 'object') return '';
    if (isNotCompared(f)) return clean('Original does not compare this one: past papers have no value for it, so it plays no part in the score.', '');
    if (f.kind === 'off') return clean('This measurement is switched off, so it plays no part in the score.', '');
    if (!isActive(f)) return '';
    var pos = position(f);
    var whole = f.kind === 'whole_text';
    if (pos === 'none') return clean('There are no past papers to compare this with.', '');
    if (pos === 'within') {
      // Original's top list takes habits far from the past papers' usual level
      // (more than one standard deviation), which can still be inside the span
      // from lowest to highest past paper. "In line" would contradict the list.
      var lead = f.in_top_list
        ? 'This paper sits inside the past papers\u2019 range here, but far from where they usually sit.'
        : 'This habit is in line with the past papers.';
      return clean(lead + (whole ? ' ' + wholeWords(f) : ''), '');
    }
    var dir = pos === 'above' ? 'higher' : 'lower';
    var tail = (whole ? ' ' + wholeWords(f) : '') + ' ' + CAUTION;
    // The habit's own name and numbers when they pass the wording check,
    // else the generic name, else no numbers.
    var tries = [
      [habitName(f), rangeBrackets(f)],
      ['this habit', rangeBrackets(f)],
      [habitName(f), ''],
      ['this habit', ''],
    ];
    for (var i = 0; i < tries.length; i++) {
      var s = 'This paper is ' + dir + ' than the past papers on ' + tries[i][0] + tries[i][1] + '.' + tail;
      if (isClean(s)) return s;
    }
    return '';
  }

  // The summary at the top, from the full list's own flags and kinds.
  // groupName(group number) gives a readable name, or '' to leave it out.
  function summarize(ev, groupName) {
    var full = ev && Array.isArray(ev.all_features) ? ev.all_features : [];
    var active = full.filter(isActive);
    var outside = active.filter(function (f) { return f.engine_scale && f.engine_scale.outside_past_range; });
    var unused = full.filter(function (f) { return f && !isListed(f); });
    var off = unused.filter(function (f) { return f.kind === 'off'; }).length;
    var notCompared = unused.filter(isNotCompared).length;
    var otherListed = full.filter(function (f) { return isListed(f) && !isActive(f); }).length;
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
      off: off, notCompared: notCompared, otherListed: otherListed, groups: groups, pastCount: pastCount,
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
    if (sum.otherListed) {
      out.push(plural(sum.otherListed, 'measurement') + ' that Original does not normally compare had differing values here, so ' +
        (sum.otherListed === 1 ? 'it is' : 'they are') + ' listed below but not counted here.');
    }
    if (sum.off || sum.notCompared) {
      var bits = [];
      if (sum.off) bits.push(plural(sum.off, 'measurement') + ' switched off');
      if (sum.notCompared) {
        bits.push(plural(sum.notCompared, 'comparison measurement') + ' not compared, because past papers have no value for ' +
          (sum.notCompared === 1 ? 'it' : 'them'));
      }
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
      return isActive(f) && !isHidden(f) && f.engine_scale && !f.engine_scale.outside_past_range &&
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

  // How this paper differs, in one plain line, for the 23 habits Original
  // counts at places in the text: [higher, lower, none] in the habit's own
  // words. Any other habit gets the generic line. Numbers are the plain ones
  // the server sent (numbersOf), never a new measure.
  var PHRASES = {
    mean_sentence_length: ['writes longer sentences', 'writes shorter sentences'],
    sentence_length_variance: ['varies its sentence lengths more', 'varies its sentence lengths less'],
    passive_voice_ratio: ['has more passive sentences', 'has fewer passive sentences', 'has no passive sentences'],
    modal_verb_ratio: ['uses more modal verbs (can, should, must)', 'uses fewer modal verbs (can, should, must)', 'uses no modal verbs (can, should, must)'],
    discourse_marker_density: ['uses more linking words', 'uses fewer linking words', 'uses no linking words'],
    additive_ratio: ['gives more of its linking words to adding ideas', 'gives fewer of its linking words to adding ideas', 'uses no linking words that add ideas'],
    adversative_ratio: ['gives more of its linking words to contrast', 'gives fewer of its linking words to contrast', 'uses no linking words that contrast'],
    causal_ratio: ['gives more of its linking words to cause and effect', 'gives fewer of its linking words to cause and effect', 'uses no linking words for cause and effect'],
    temporal_ratio: ['gives more of its linking words to sequence', 'gives fewer of its linking words to sequence', 'uses no linking words for sequence'],
    transition_density: ['uses more transition words', 'uses fewer transition words', 'uses no transition words'],
    hedging_density: ['uses more softening words (perhaps, might, seems)', 'uses fewer softening words (perhaps, might, seems)', 'uses no softening words (perhaps, might, seems)'],
    assertion_density: ['uses more confident-statement words (clearly, certainly)', 'uses fewer confident-statement words (clearly, certainly)', 'uses no confident-statement words (clearly, certainly)'],
    claim_density: ['uses more claim markers (therefore, this shows)', 'uses fewer claim markers (therefore, this shows)', 'uses no claim markers (therefore, this shows)'],
    question_ratio: ['asks more questions', 'asks fewer questions', 'asks no questions'],
    first_person_ratio: ['uses I, me and my for more of its pronouns', 'uses I, me and my for fewer of its pronouns', 'uses no first-person pronouns'],
    appeal_to_authority_density: ['uses more source phrases (according to, argues)', 'uses fewer source phrases (according to, argues)', 'uses no source phrases (according to, argues)'],
    comma_rate: ['uses more commas', 'uses fewer commas', 'uses no commas'],
    semicolon_colon_rate: ['uses more semicolons and colons', 'uses fewer semicolons and colons', 'uses no semicolons or colons'],
    parenthetical_rate: ['uses more brackets', 'uses fewer brackets', 'uses no brackets'],
    dash_rate: ['uses more dashes', 'uses fewer dashes', 'uses no dashes'],
    quote_rate: ['uses more quotation marks', 'uses fewer quotation marks', 'uses no quotation marks'],
    contraction_rate: ['uses more contractions', 'uses fewer contractions', 'uses no contractions'],
    sentence_initial_conjunction_rate: ['starts more sentences with and, but or so', 'starts fewer sentences with and, but or so', 'starts no sentence with and, but or so'],
  };
  function differenceLine(f) {
    if (!isActive(f)) return '';
    var n = readable(f);
    var pos = position(f);
    if (pos === 'none') return '';
    // A kind, not an amount: say which kind each side uses.
    if (n.mode === 'category') return oneLine(f);
    // No everyday unit: where it sits, in words only (compareWords).
    if (!n.plain) {
      var cw = compareWords(f);
      if (!cw) return '';
      return clean('This paper is ' + cw + ' on ' + habitName(f) + '.', clean('This paper is ' + cw + ' on this habit.', ''));
    }
    if (n.thisValue == null || n.lo == null || n.hi == null) return '';
    var nums = n.show(n.thisValue) + ' vs ' + rangeText(n) + (n.unit ? ' ' + n.unit : '');
    // Which way, from the plain numbers (they are what the line shows).
    var dir = n.thisValue > n.hi ? 'above' : n.thisValue < n.lo ? 'below' : 'within';
    if (dir === 'within') {
      var where = f.in_top_list || pos !== 'within'
        ? 'This paper sits inside the past papers\u2019 range, but far from where they usually sit: '
        : 'This paper sits within the past papers\u2019 range: ';
      return clean(where + nums + '.', '');
    }
    var up = dir === 'above';
    var far = up ? (n.hi > 0 ? n.thisValue >= 2 * n.hi : n.thisValue > 0) : n.thisValue <= n.lo / 2;
    var ph = PHRASES[f.code];
    var line;
    if (ph && !up && n.thisValue === 0 && ph[2]) line = 'This paper ' + ph[2] + ': ' + nums + '.';
    else if (ph) {
      var phrase = up ? ph[0] : ph[1];
      if (far) phrase = phrase.replace(/\b(more|fewer|longer|shorter|less)\b/, 'far $1');
      line = 'This paper ' + phrase + ': ' + nums + '.';
    } else {
      line = 'This paper is ' + (far ? 'far ' : '') + (up ? 'higher' : 'lower') + ' than the past papers on ' + habitName(f) + ': ' + nums + '.';
    }
    return clean(line, clean('This paper is ' + (up ? 'higher' : 'lower') + ' than the past papers: ' + nums + '.', ''));
  }

  // The line above a side's unmarked sentences: the server sends a side's
  // longest sentences when that side never uses a habit the other side does.
  function unmarkedLead(f, side) {
    var what = String((f && f.what_is_marked) || '').trim();
    var whose = side === 'this' ? 'This paper\u2019s longest sentences' : 'The past papers\u2019 longest sentences';
    var article = /^[aeiou]/i.test(what) ? 'an ' : 'a ';
    return clean(whose + (what ? ', none with ' + article + what : '') + ':', whose + ':');
  }

  // A quote cut into the text before, the counted words and the text after.
  // The counted words are used only when they are exactly the slice of the
  // passage the offsets name; otherwise nothing is marked.
  function markParts(q) {
    var p = String(q && q.passage || '');
    var a = num(q && q.match_start) - num(q && q.passage_start);
    var b = num(q && q.match_end) - num(q && q.passage_start);
    var ok = isFinite(a) && isFinite(b) && a >= 0 && b > a && b <= p.length && p.slice(a, b) === q.match;
    if (!ok) return { before: p, mark: '', after: '', tiny: false };
    var mark = p.slice(a, b);
    return { before: p.slice(0, a), mark: mark, after: p.slice(b), tiny: isShortMatch(mark) };
  }

  // A counted match too short to see in the highlight alone (a comma, "of"):
  // the page marks it smaller and spells it out on the source line.
  function isShortMatch(m) {
    var s = String(m == null ? '' : m);
    return !!s && (s.trim().length <= 3 || !/[A-Za-z0-9]/.test(s));
  }

  // A stored date ("2025-01-24" or a full timestamp) as the calendar day it
  // names, e.g. "24 Jan 2025" in the reader's locale; '' when there is none.
  function dayOf(s) {
    var m = /^(\d{4})-(\d{2})-(\d{2})(?:$|T|\s)/.exec(String(s == null ? '' : s));
    if (!m) return '';
    var d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    if (isNaN(d.getTime())) return '';
    return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
  }

  // One separator for every source line on the three pages.
  var SEP = ' \u00b7 ';

  // A past paper's source: its stored title (else "Past paper N") and its day.
  function pastSource(label, papers) {
    var p = null;
    if (Array.isArray(papers)) {
      for (var i = 0; i < papers.length; i++) {
        if (papers[i] && typeof papers[i] === 'object' && papers[i].paper === label) { p = papers[i]; break; }
      }
    }
    var day = p ? dayOf(p.submitted_at) : '';
    // A paper the server described but stored no date for says so; one it
    // did not describe at all keeps the bare name.
    return paperName(label, papers) + (day ? SEP + day : p ? SEP + 'date not recorded' : '');
  }

  // This paper's source: "This paper", its title when there is one, and the
  // day it was analysed (the day it reached Original; a pasted paper carries
  // no other date).
  function thisSource(assignment, analysedAt) {
    var title = String(assignment == null ? '' : assignment).trim();
    var day = dayOf(analysedAt);
    return ['This paper', title, day ? 'analysed ' + day : ''].filter(Boolean).join(SEP);
  }

  // A quote's source line: where it is from, its length, a short match spelled
  // out, and whether it runs into text set aside. `label` names the paper.
  function quoteSource(q, label) {
    var parts = markParts(q);
    var src = [String(label == null ? '' : label)];
    if (num(q && q.words) != null) src.push(plural(q.words, 'word'));
    if (parts.tiny) src.push('Counted: \u201c' + parts.mark.trim() + '\u201d');
    if (q && q.crosses_set_aside) src.push('runs into text set aside from measuring');
    return src.filter(Boolean).join(SEP);
  }

  var API = {
    BANNED: BANNED, isClean: isClean, clean: clean, fmt: fmt, signed: signed, plural: plural,
    paperName: paperName, isActive: isActive, isNotCompared: isNotCompared, NOT_COMPARED_WORDS: NOT_COMPARED_WORDS, isConstant: isConstant, isListed: isListed, numbersOf: numbersOf, position: position,
    positionSentence: positionSentence, oneLine: oneLine, noteFor: noteFor, noticeFor: noticeFor,
    summarize: summarize, summarySentences: summarySentences, steady: steady, markParts: markParts,
    NOT_COMPARED_LINE: NOT_COMPARED_LINE, habitName: habitName, isShortMatch: isShortMatch, dayOf: dayOf,
    SEP: SEP, pastSource: pastSource, quoteSource: quoteSource, thisSource: thisSource,
    differenceLine: differenceLine, unmarkedLead: unmarkedLead, PHRASES: PHRASES,
    displayOf: displayOf, isHidden: isHidden, HIDDEN_CODES: HIDDEN_CODES, readable: readable, pct: pct, unitNum: unitNum,
    rangeText: rangeText, rangeWords: rangeWords, compareWords: compareWords, positionDetail: positionDetail,
    valueWords: valueWords,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
  else root.EvidenceView = API;
})(this);

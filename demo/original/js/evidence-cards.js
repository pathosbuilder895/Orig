/* evidence-cards.js: one habit, this paper beside the past papers, as the
   same card on all three staff pages (ADR-013): Writing State after an
   analysis, the side-by-side page (evidence.html) and the conversation packet
   (packet.html). One builder means the three show the same quotes, marks,
   labels and lines; the pages only style the classes.

   Every word is EvidenceView's (banned-wording checked); every quote is the
   server's verbatim slice, marked only where its offsets name exactly that
   slice (EvidenceView.markParts). Student text is escaped here, once.

   Loaded after evidence-view.js as window.EvidenceCards; node's unit tests
   load it through require() with EvidenceView passed in. */
(function (root) {
  'use strict';

  function make(EV) {
    var num = function (v) { return typeof v === 'number' && isFinite(v) ? v : null; };
    var isObj = function (v) { return !!v && typeof v === 'object' && !Array.isArray(v); };
    function esc(s) {
      return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
      });
    }
    var quotes = function (block, key) {
      var list = isObj(block) && Array.isArray(block[key]) ? block[key] : [];
      return list.filter(function (q) { return isObj(q) && typeof q.passage === 'string' && q.passage; }).slice(0, 3);
    };

    // ctx.papers: evidence.baseline_papers; ctx.thisSource: this paper's source line.
    function sourceFor(q, ctx) {
      return q.paper === 'this paper' ? (ctx.thisSource || 'This paper') : EV.pastSource(q.paper, ctx.papers);
    }
    function quoteHTML(q, side, ctx) {
      var parts = EV.markParts(q);
      var lead = q.clipped_start ? '… ' : '', tail = q.clipped_end ? ' …' : '';
      var body = esc(parts.before) + (parts.mark ? '<mark' + (parts.tiny ? ' class="tiny"' : '') + '>' + esc(parts.mark) + '</mark>' : '') + esc(parts.after);
      // Character offsets stay out of the visible line; they are in the tooltip.
      var at = num(q.start) != null && num(q.end) != null ? ' title="' + esc('characters ' + q.start + ' to ' + q.end) + '"' : '';
      return '<div class="ex-q' + (side === 'base' ? ' base' : '') + (parts.mark ? '' : ' unmarked') + '" data-mark="' + esc(parts.mark) + '">' +
        esc(lead) + body + esc(tail) + '</div>' +
        '<div class="ex-src"' + at + '>' + esc(EV.quoteSource(q, sourceFor(q, ctx))) + '</div>';
    }
    // The column heading: one past paper's name when every quote is from it.
    function baseHeading(list, ctx) {
      var ps = [];
      list.forEach(function (q) { if (ps.indexOf(q.paper) < 0) ps.push(q.paper); });
      return ps.length === 1 ? EV.paperName(ps[0], ctx.papers) : 'Past papers';
    }
    // Why a side shows no counted quote: the server's note when it names that side.
    function noneWords(f, side) {
      var note = typeof f.note === 'string' ? f.note : '';
      var fits = note && (side === 'this' ? /this paper/i : /past papers/i).test(note);
      return EV.clean(fits ? note : '', '') || (side === 'this' ? 'None found in this paper.' : 'None found in the past papers.');
    }
    function sideHTML(f, side, ctx) {
      var block = side === 'this' ? f.this_paper : f.past_papers;
      var found = quotes(block, 'examples');
      if (found.length) return found.map(function (q) { return quoteHTML(q, side, ctx); }).join('');
      var none = '<p class="none-line">' + esc(noneWords(f, side)) + '</p>';
      var plain = quotes(block, 'unmarked');
      if (!plain.length) return none;
      return none + '<p class="um-lead">' + esc(EV.unmarkedLead(f, side)) + '</p>' +
        plain.map(function (q) { return quoteHTML(q, side, ctx); }).join('');
    }
    function textCols(f, ctx) {
      var pp = quotes(f.past_papers, 'examples');
      var heading = pp.length ? baseHeading(pp, ctx) : baseHeading(quotes(f.past_papers, 'unmarked'), ctx);
      return '<div class="ex-col"><div class="ex-lbl this">This paper</div>' + sideHTML(f, 'this', ctx) + '</div>' +
        '<div class="ex-col"><div class="ex-lbl base">' + esc(heading) + '</div>' + sideHTML(f, 'base', ctx) + '</div>';
    }
    // The numbers, as EvidenceView.readable writes them: a percent, a plain
    // unit or a kind; with no everyday unit, where this paper sits in words
    // (each past paper above, below or level with it), never the raw position.
    function numberCols(f, ctx) {
      var n = EV.numbersOf(f);
      var unit = n.mode === 'category' ? '' : n.unit;
      if (!n.plain) {
        var t = num((f.engine_scale || {}).this_paper);
        var cw = EV.compareWords(f);
        var rel = function (v) {
          if (t == null || num(v) == null) return '';
          return t > v + 1e-9 ? 'lower than this paper' : t < v - 1e-9 ? 'higher than this paper' : 'level with this paper';
        };
        var eng = f.engine_scale || {};
        var past = (Array.isArray(eng.past_papers) ? eng.past_papers : []).filter(function (p) { return isObj(p) && num(p.value) != null; });
        return '<div class="ex-col"><div class="ex-lbl this">This paper</div>' +
            '<p class="ex-rel">' + esc(cw ? EV.clean('This paper is ' + cw + '.', '') : 'No past papers to compare with.') + '</p></div>' +
          '<div class="ex-col"><div class="ex-lbl base">Past papers</div><ul class="ex-vals">' +
            past.map(function (p) { return '<li><span>' + esc(EV.pastSource(p.paper, ctx.papers)) + '</span><b class="rel">' + esc(rel(p.value)) + '</b></li>'; }).join('') +
            '</ul></div>';
      }
      return '<div class="ex-col"><div class="ex-lbl this">This paper</div><span class="ex-big">' + esc(n.show(n.thisValue)) + '</span>' +
          (unit ? '<div class="ex-unit">' + esc(unit) + '</div>' : '') + '</div>' +
        '<div class="ex-col"><div class="ex-lbl base">Past papers</div><ul class="ex-vals">' +
          n.past.map(function (p) { return '<li><span>' + esc(EV.pastSource(p.paper, ctx.papers)) + '</span><b>' + esc(n.show(p.value)) + '</b></li>'; }).join('') +
          '</ul>' + (unit ? '<div class="ex-unit">' + esc(unit) + '</div>' : '') + '</div>';
    }
    // A whole-paper habit's per-part values (original/evidence.py build_breakdown):
    // one row per paper, a column per part, "too short to measure" where the
    // extractor would record a stand-in; then the closing sentences it reads.
    function breakdownHTML(f, ctx) {
      var b = EV.breakdownOf(f);
      if (!b || !Array.isArray(b.parts)) return '';
      var c = ctx || {};
      var papers = Array.isArray(c.papers) ? c.papers : [];
      var show = b.style === 'percent' ? EV.pct : EV.unitNum;
      var parts = b.parts.map(String);
      var row = function (label, values) {
        var cells = Array.isArray(values)
          ? values.map(function (v) { return '<td>' + esc(show(v)) + '</td>'; }).join('')
          : '<td colspan="' + parts.length + '" class="ex-short">' + esc(EV.clean(b.too_short, 'Too short to measure.')) + '</td>';
        return '<tr><th scope="row">' + esc(label) + '</th>' + cells + '</tr>';
      };
      var rows = row('This paper', b.this_paper) + (Array.isArray(b.past_papers) ? b.past_papers : []).filter(isObj).map(function (p) {
        return row(EV.paperName(p.paper, papers), p.values);
      }).join('');
      var html = '<div class="ex-break"><p class="ex-break-h">' + esc(EV.clean(b.label, '')) + (b.unit ? ' <span>(' + esc(b.unit) + ')</span>' : '') + '</p>' +
        '<div class="ex-break-wrap"><table class="ex-break-t"><thead><tr><th scope="col"></th>' +
        parts.map(function (p) { return '<th scope="col">' + esc(p) + '</th>'; }).join('') + '</tr></thead><tbody>' + rows + '</tbody></table></div>';
      var cl = isObj(b.closing) ? b.closing : null;
      var q = function (list) { return (Array.isArray(list) ? list : []).filter(function (x) { return isObj(x) && typeof x.passage === 'string' && x.passage; }).slice(0, 3); };
      if (cl && (q(cl.this_paper).length || q(cl.past_papers).length)) {
        var side = function (list, base) {
          return q(list).map(function (x) {
            return '<div class="ex-q unmarked' + (base ? ' base' : '') + '">' + esc((x.clipped_start ? '… ' : '') + x.passage + (x.clipped_end ? ' …' : '')) + '</div>' +
              '<div class="ex-src">' + esc(EV.quoteSource(x, x.paper === 'this paper' ? (c.thisSource || 'This paper') : EV.pastSource(x.paper, papers))) + '</div>';
          }).join('') || '<p class="none-line">None to show.</p>';
        };
        html += '<p class="ex-break-h">Closing sentences</p><div class="ex-cols2"><div class="ex-col"><div class="ex-lbl this">This paper</div>' + side(cl.this_paper, false) +
          '</div><div class="ex-col"><div class="ex-lbl base">' + esc(q(cl.past_papers).length ? EV.paperName(q(cl.past_papers)[0].paper, papers) : 'Past papers') + '</div>' + side(cl.past_papers, true) + '</div></div>';
      }
      return html + '</div>';
    }
    // The exact position behind a plain comparison, folded away (never a percent).
    function exactHTML(f) {
      if (EV.numbersOf(f).plain || EV.isNotCompared(f)) return '';
      var d = EV.positionDetail(f);
      return d ? '<details class="ex-exact"><summary>Exact position</summary><p>' + esc(d) + '</p></details>' : '';
    }
    var hasText = function (f) { return f.kind === 'located' && isObj(f.this_paper) && isObj(f.past_papers); };
    // "What to notice": the plain sentence, then the numbers line. `whole` is
    // the server's whole-text note, kept only when the plain sentence is silent.
    function noticeHTML(f, ctx) {
      var whole = f.kind === 'whole_text' ? EV.clean(f.note, '') : '';
      var plain = EV.noticeFor(f, ctx.papers);
      var keepWhole = whole && (!plain || EV.position(f) === 'none');
      // With no everyday unit the numbers line would only repeat the comparison
      // the card already says twice, so it is left out when there is a sentence.
      var repeat = plain && !EV.numbersOf(f).plain && !EV.isNotCompared(f);
      var numbers = repeat ? (keepWhole ? whole : '') : EV.noteFor(f, ctx.papers) + (keepWhole ? ' ' + whole : '');
      return (plain ? '<p><b>What to notice:</b> ' + esc(plain) + '</p>' : '') +
        (numbers ? '<p class="nums-line">' + (plain ? '' : '<b>What to notice:</b> ') + esc(numbers) + '</p>' : '') + exactHTML(f);
    }
    // One habit as a card. The line under its name says how this paper differs
    // in plain words (EvidenceView.differenceLine), else the two numbers.
    // ctx.noHead: a row that already shows the habit's name keeps only the line.
    function card(f, ctx) {
      if (!isObj(f)) return '';
      var c = ctx || {};
      var noHead = !!c.noHead;
      c = { papers: Array.isArray(c.papers) ? c.papers : [], thisSource: c.thisSource || '' };
      var line = EV.differenceLine(f) || EV.oneLine(f);
      var name = noHead ? '' : '<b>' + esc(EV.clean(f.name, f.code)) + '</b>';
      return '<div class="ex" data-code="' + esc(f.code) + '">' +
        '<div class="ex-h">' + name + '<span class="ex-diff">' + esc(line) + '</span></div>' +
        (hasText(f) ? textCols(f, c) : numberCols(f, c)) +
        '<div class="ex-note">' + noticeHTML(f, c) + breakdownHTML(f, c) + '</div></div>';
    }
    // Original's own top list, each entry resolved to its full-list entry (the
    // one with plain numbers and quotes), in the server's order.
    // A habit the server marks hidden (display.style "hidden") is left out.
    function topList(ev) {
      if (!isObj(ev) || !Array.isArray(ev.features)) return [];
      var byCode = {};
      (Array.isArray(ev.all_features) ? ev.all_features : []).forEach(function (f) {
        if (isObj(f) && typeof f.code === 'string') byCode[f.code] = f;
      });
      return ev.features.filter(isObj).map(function (t) {
        return Object.prototype.hasOwnProperty.call(byCode, t.code) ? byCode[t.code] : t;
      }).filter(function (f) { return !EV.isHidden(f); });
    }
    // Lead with the writing: the top list's habits with sentences to quote,
    // then the rest (numbers or a whole-paper pattern) for "Other patterns".
    function splitTop(ev) {
      var top = topList(ev);
      return { quoted: top.filter(hasQuotes), other: top.filter(function (f) { return !hasQuotes(f); }) };
    }
    // "Other patterns": one compact row per habit, its plain line and why
    // there is no sentence to quote, the exact position folded away.
    function otherList(list, ctx) {
      var c = ctx || {};
      c = { papers: Array.isArray(c.papers) ? c.papers : [], thisSource: c.thisSource || '' };
      var rows = (list || []).filter(isObj).map(function (f) {
        var line = EV.differenceLine(f) || EV.oneLine(f);
        var why = f.kind === 'whole_text' && typeof f.note === 'string' ? EV.clean(f.note, '') : '';
        return '<li class="ex-other-row" data-code="' + esc(f.code) + '"><b>' + esc(EV.clean(f.name, f.code)) + '</b>' +
          (line ? '<span class="ex-other-line">' + esc(line) + '</span>' : '') +
          (why ? '<span class="ex-other-why">' + esc(why) + '</span>' : '') + breakdownHTML(f, c) + exactHTML(f) + '</li>';
      });
      return rows.length ? '<ul class="ex-other">' + rows.join('') + '</ul>' : '';
    }
    function papersOf(ev) {
      return isObj(ev) && Array.isArray(ev.baseline_papers) ? ev.baseline_papers.filter(isObj) : [];
    }
    var hasQuotes = function (f) { return isObj(f) && f.kind === 'located' && (quotes(f.this_paper, 'examples').length > 0 || quotes(f.past_papers, 'examples').length > 0); };
    return { card: card, topList: topList, splitTop: splitTop, otherList: otherList, breakdownHTML: breakdownHTML, papersOf: papersOf, hasQuotes: hasQuotes, esc: esc };
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = make;
  else root.EvidenceCards = make(root.EvidenceView);
})(this);

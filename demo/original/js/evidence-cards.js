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
    function numberCols(f, ctx) {
      var n = EV.numbersOf(f);
      return '<div class="ex-col"><div class="ex-lbl this">This paper</div><span class="ex-big">' + esc(EV.fmt(n.thisValue)) + '</span>' +
          '<div class="ex-unit">' + esc(n.unit) + '</div></div>' +
        '<div class="ex-col"><div class="ex-lbl base">Past papers</div><ul class="ex-vals">' +
          n.past.map(function (p) { return '<li><span>' + esc(EV.pastSource(p.paper, ctx.papers)) + '</span><b>' + esc(EV.fmt(p.value)) + '</b></li>'; }).join('') +
          '</ul><div class="ex-unit">' + esc(n.unit) + '</div></div>';
    }
    var hasText = function (f) { return f.kind === 'located' && isObj(f.this_paper) && isObj(f.past_papers); };
    // "What to notice": the plain sentence, then the numbers line. `whole` is
    // the server's whole-text note, kept only when the plain sentence is silent.
    function noticeHTML(f, ctx) {
      var whole = f.kind === 'whole_text' ? EV.clean(f.note, '') : '';
      var plain = EV.noticeFor(f, ctx.papers);
      var keepWhole = whole && (!plain || EV.position(f) === 'none');
      var numbers = EV.noteFor(f, ctx.papers) + (keepWhole ? ' ' + whole : '');
      return (plain ? '<p><b>What to notice:</b> ' + esc(plain) + '</p>' : '') +
        '<p class="nums-line">' + (plain ? '' : '<b>What to notice:</b> ') + esc(numbers) + '</p>';
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
        '<div class="ex-note">' + noticeHTML(f, c) + '</div></div>';
    }
    // Original's own top list, each entry resolved to its full-list entry (the
    // one with plain numbers and quotes), in the server's order.
    function topList(ev) {
      if (!isObj(ev) || !Array.isArray(ev.features)) return [];
      var byCode = {};
      (Array.isArray(ev.all_features) ? ev.all_features : []).forEach(function (f) {
        if (isObj(f) && typeof f.code === 'string') byCode[f.code] = f;
      });
      return ev.features.filter(isObj).map(function (t) {
        return Object.prototype.hasOwnProperty.call(byCode, t.code) ? byCode[t.code] : t;
      });
    }
    function papersOf(ev) {
      return isObj(ev) && Array.isArray(ev.baseline_papers) ? ev.baseline_papers.filter(isObj) : [];
    }
    var hasQuotes = function (f) { return isObj(f) && f.kind === 'located' && (quotes(f.this_paper, 'examples').length > 0 || quotes(f.past_papers, 'examples').length > 0); };
    return { card: card, topList: topList, papersOf: papersOf, hasQuotes: hasQuotes, esc: esc };
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = make;
  else root.EvidenceCards = make(root.EvidenceView);
})(this);

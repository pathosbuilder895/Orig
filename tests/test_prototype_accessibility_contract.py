"""Static contracts for navigation and accessible prototype equivalents."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE_DIR = ROOT / "demo" / "prototypes"
PROTOTYPE = (PROTOTYPE_DIR / "prototype.js").read_text(encoding="utf-8")
STYLES = (PROTOTYPE_DIR / "prototype.css").read_text(encoding="utf-8")
DOCUMENT_STYLES = (PROTOTYPE_DIR / "document-liquid-glass.css").read_text(
    encoding="utf-8"
)
CONSTELLATION = (PROTOTYPE_DIR / "constellation-engine.js").read_text(encoding="utf-8")
NETWORK = (PROTOTYPE_DIR / "network-pulse-engine.js").read_text(encoding="utf-8")
TEMPORAL = (PROTOTYPE_DIR / "temporal-chart.js").read_text(encoding="utf-8")
DOCUMENT = (PROTOTYPE_DIR / "document-intelligence.js").read_text(encoding="utf-8")


def test_prototype_views_have_restorable_hash_routes() -> None:
    assert "function routeView()" in PROTOTYPE
    assert "history[replace ? 'replaceState' : 'pushState']" in PROTOTYPE
    assert "window.addEventListener('popstate', handleRouteChange)" in PROTOTYPE
    assert "window.addEventListener('hashchange', handleRouteChange)" in PROTOTYPE
    assert 'aria-current="page"' in PROTOTYPE
    assert "heading.focus({ preventScroll:true })" in PROTOTYPE


def test_canvas_views_expose_keyboard_equivalents_and_pause_offscreen() -> None:
    assert 'aria-describedby="constellation-keyboard-help"' in PROTOTYPE
    assert 'class="canvas-access-panel"' in PROTOTYPE
    assert 'data-constellation-node="${node.id}"' in PROTOTYPE
    assert "selectById(id)" in CONSTELLATION

    assert 'aria-describedby="pulse-keyboard-help"' in PROTOTYPE
    assert 'data-hierarchy-index aria-label="Galaxy hierarchy"' in PROTOTYPE
    assert 'data-pulse-status role="status"' in PROTOTYPE
    assert "focusInterfaceHeading()" in NETWORK

    for source in (CONSTELLATION, NETWORK):
        assert "visibilitychange" in source
        assert "IntersectionObserver" in source
        assert "inViewport" in source


def test_temporal_chart_uses_roving_focus_and_has_a_data_table() -> None:
    assert 'class="temporal-svg" role="group"' in PROTOTYPE
    assert "data-temporal-table" in PROTOTYPE
    assert "renderDataTable()" in TEMPORAL
    assert "tabindex:index===this.selected?0:-1" in TEMPORAL
    assert "event.key==='ArrowRight'" in TEMPORAL
    assert "event.key==='ArrowLeft'" in TEMPORAL
    assert "event.key==='Home'" in TEMPORAL
    assert "event.key==='End'" in TEMPORAL


def test_text_studio_has_one_concise_live_region_and_reading_focus_toggle() -> None:
    start = PROTOTYPE.index("function documentEditor()")
    end = PROTOTYPE.index("const views=", start)
    editor_markup = PROTOTYPE[start:end]

    assert editor_markup.count('aria-live="polite"') == 1
    assert (
        'data-evidence-status role="status" aria-live="polite" aria-atomic="true"' in editor_markup
    )
    assert 'class="feature-inspector glass-panel" aria-live=' not in editor_markup
    assert (
        'class="paper baseline-paper" aria-label="Selected baseline paper" aria-live='
        not in editor_markup
    )
    assert 'data-passage-inspector role="region" aria-live=' not in editor_markup

    assert 'data-focus-background aria-pressed="${reduceEditorBackground}"' in PROTOTYPE
    assert "'Reduce background detail'" in PROTOTYPE
    assert ".editor-shell.background-reduced .editor-atmosphere" in STYLES
    assert ".editor-shell.background-reduced .glass-panel" in STYLES


def test_text_studio_evidence_inspector_keeps_detail_progressive() -> None:
    start = PROTOTYPE.index("function documentEditor()")
    end = PROTOTYPE.index("const views=", start)
    editor_markup = PROTOTYPE[start:end]

    assert '<details class="inspector-more" data-inspector-more>' in editor_markup
    assert (
        "<summary><span>Method, provenance &amp; related features</span>"
        in editor_markup
    )
    for field in (
        "data-current-label",
        "data-baseline-label",
        "data-method-scope",
        "data-method-measure",
        "data-method-baseline",
    ):
        assert field in editor_markup

    assert "data-pin-evidence" not in editor_markup
    assert "data-deviation-scale" not in editor_markup
    assert 'class="position-scale"' not in editor_markup
    assert "set('[data-current-label]','CURRENT PAPER')" in DOCUMENT
    assert "set('[data-baseline-label]','SELECTED BASELINE PAPER')" in DOCUMENT
    assert (
        "region.setAttribute('aria-label',`${name} division evidence`)" in DOCUMENT
    )


def test_text_studio_occurrence_and_comparison_actions_are_wired() -> None:
    start = PROTOTYPE.index("function documentEditor()")
    end = PROTOTYPE.index("const views=", start)
    editor_markup = PROTOTYPE[start:end]

    for control in (
        "data-passage-prev",
        "data-passage-next",
        "data-passage-position",
        "data-passage-total",
        "data-open-comparison",
    ):
        assert control in editor_markup

    assert "stepPassagePreview(direction)" in DOCUMENT
    assert "this.stepPassagePreview(-1)" in DOCUMENT
    assert "this.stepPassagePreview(1)" in DOCUMENT
    assert "this.toggleCompare(true)" in DOCUMENT


def test_text_studio_comparison_content_starts_hidden_and_inert() -> None:
    start = PROTOTYPE.index("function documentEditor()")
    end = PROTOTYPE.index("const views=", start)
    editor_markup = PROTOTYPE[start:end]

    assert (
        'data-comparison-ribbon aria-hidden="true" hidden' in editor_markup
    )
    assert (
        'class="paper-column baseline-paper-column" '
        'aria-label="Baseline reference paper" aria-hidden="true" hidden'
        in editor_markup
    )
    assert "column.hidden=!this.compare;column.inert=!this.compare" in DOCUMENT
    assert "ribbon.hidden=!this.compare;ribbon.inert=!this.compare" in DOCUMENT


def test_text_studio_evidence_inspector_copy_and_targets_remain_readable() -> None:
    required_rules = (
        ".feature-inspector .inspector-hero>p{margin:0;font-size:16px;"
        "line-height:1.55",
        ".feature-inspector .passage-sample q{font-size:16px;line-height:1.55",
        ".feature-inspector .passage-explanation p{font-size:15px;"
        "line-height:1.55",
        ".passage-occurrence-nav>button{min-width:0;min-height:44px",
        ".inspector-actions>button{width:100%;min-height:48px",
        ".inspector-more>summary{min-height:52px",
    )
    for rule in required_rules:
        assert rule in DOCUMENT_STYLES


def test_primary_operational_controls_keep_large_targets() -> None:
    required_rules = (
        ".graph-hud button{width:44px;height:44px",
        ".pulse-view-tools button{min-height:44px",
        ".sentiment-tabs button{min-height:44px",
        ".playback button{width:44px!important;height:44px!important",
        ".temporal-data-disclosure summary{display:flex;align-items:center",
        "justify-content:center;min-width:118px;min-height:44px",
    )
    for rule in required_rules:
        assert rule in STYLES


def test_text_studio_sanitizes_baseline_markup_before_rendering() -> None:
    assert "renderSafeBaselineMarkup(container,markup)" in DOCUMENT
    assert "const allowedTags=new Set(['P','SPAN','MARK','BLOCKQUOTE','CITE','SMALL'])" in DOCUMENT
    assert "container.replaceChildren(template.content.cloneNode(true))" in DOCUMENT
    assert "body.innerHTML=paper.body" not in DOCUMENT


def test_passage_family_lens_handles_trait_only_sentence_wrappers() -> None:
    assert "legacyMatch||traitMatch" in DOCUMENT
    assert (
        "marks.forEach(mark=>mark.classList.toggle('feature-active',this.traitMatches(mark)))"
        in DOCUMENT
    )
    assert "mark.dataset.feature.split" not in DOCUMENT

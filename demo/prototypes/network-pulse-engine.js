import { SYSTEMS, TIERS, FEATURE_PLANETS, SYSTEM_BY_ID, TIER_BY_ID, FEATURE_BY_CODE } from './feature-universe-data.js?v=production-review-20260722';

const TAU = Math.PI * 2;
const STATUS_COLORS = { positive: '#67c995', neutral: '#9baca5', negative: '#ec786b', emergent: '#d5f36f' };
const STATUS_LABELS = { all: 'ALL', positive: 'ALIGNED', neutral: 'WATCH', negative: 'REVIEW' };
const MACRO_POSITIONS = {
  surface: { x: -.29, y: -.17, z: -.04 },
  discourse: { x: .34, y: -.12, z: .07 },
  rhetoric: { x: .01, y: .30, z: -.02 }
};
const ENTRY_COMPATIBILITY = {
  authorship: 'surface',
  language: 'surface',
  revision: 'surface',
  citation: 'rhetoric',
  integrity: 'rhetoric',
  ai: 'surface'
};
const REVELATION_PAIR = Object.freeze(['semicolon_colon_rate', 'clause_depth_mean']);
const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
const lerp = (a, b, amount) => a + (b - a) * amount;
const ease = (value) => value * value * (3 - 2 * value);
const seeded = (seed = 42871) => () => ((seed = (seed * 16807) % 2147483647) - 1) / 2147483646;
const rgb = (hex) => { const number = parseInt(hex.slice(1), 16); return [(number >> 16) & 255, (number >> 8) & 255, number & 255]; };
const short = (value, length = 25) => value.length > length ? `${value.slice(0, length - 1)}…` : value;
const tierLabel = (tier) => tier === 0 ? 'COMPARISON' : `TIER ${String(tier).padStart(2, '0')}`;
const systemTierSummary = (system) => system.tiers.includes(0) ? `${system.tiers.length - 1} TIERS + COMPARISON` : `${system.tiers.length} TIERS`;
const DIMENSION_MILESTONES = [
  { until: .14, label: 'BASELINE 01 · FIRST COMPARISON PAPER' },
  { until: .29, label: 'BASELINE 06 · VOICE STABILIZED' },
  { until: .44, label: 'DRAFT 01 · INITIAL ARGUMENT' },
  { until: .61, label: 'DRAFT 02 · STRUCTURAL REVISION' },
  { until: .79, label: 'DRAFT 03 · SOURCE INTEGRATION' },
  { until: .94, label: 'FINAL REVISION · CONCLUSION' },
  { until: 1, label: 'CURRENT SUBMISSION · MAY 18' }
];

export class NetworkPulseEngine {
  constructor(canvas, { initialCluster = null } = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.host = canvas.closest('.pulse-stage');
    this.layout = canvas.closest('.pulse-layout');
    this.random = seeded();
    this.nodes = [];
    this.edges = [];
    this.systemSuns = [];
    this.sentiment = 'all';
    this.threshold = 72;
    this.engagement = false;
    this.pointer = { x: -1e3, y: -1e3 };
    this.parallax = { x: 0, y: 0, targetX: 0, targetY: 0 };
    this.camera = { zoom: 1, targetZoom: 1, x: 0, y: 0, targetX: 0, targetY: 0, yaw: 0, targetYaw: 0, pitch: 0, targetPitch: 0, mode: 'orbit' };
    this.dimension = .72;
    this.targetDimension = .72;
    this.dimensionFlow = false;
    this.dimensionDirection = 1;
    this.frame = 0;
    this.lastTime = performance.now();
    this.lastRender = 0;
    this.drag = null;
    this.hover = null;
    this.hoverFreeze = false;
    this.focusEdge = null;
    this.focusTimer = null;
    this.compareBaseline = false;
    this.cameraSnapshots = new Map();
    this.navigationHistory = [];
    const compatibleEntry = ENTRY_COMPATIBILITY[initialCluster] || initialCluster;
    this.level = SYSTEM_BY_ID[compatibleEntry] ? 'system' : 'galaxy';
    this.selectedSystem = SYSTEM_BY_ID[compatibleEntry] ? compatibleEntry : null;
    this.selectedTier = null;
    this.selectedFeature = null;
    this.transitionStarted = 0;
    this.motionQuery = matchMedia('(prefers-reduced-motion: reduce)');
    this.motion = !this.motionQuery.matches;
    this.pageVisible = !document.hidden;
    this.inViewport = true;
    this.abort = new AbortController();
    this.createField();
    this.bind();
    this.resize();
    this.updateInterface();
    const engagement = this.layout.querySelector('[data-engagement]');
    if (engagement) engagement.checked = this.engagement;
    this.loop = this.loop.bind(this);
    this.raf = null;
    this.syncLoop();
  }

  createField() {
    for (const system of SYSTEMS) {
      const systemTiers = TIERS.filter((tier) => tier.system === system.id);
      const macro = MACRO_POSITIONS[system.id];
      const orbitBands = systemTiers.length > 8 ? [.11, .17, .235] : systemTiers.length > 3 ? [.145, .225] : [.19];
      systemTiers.forEach((tier, tierIndex) => {
        const solarBand = tierIndex % orbitBands.length;
        const orbitPeers = Math.ceil((systemTiers.length - solarBand) / orbitBands.length);
        const orbitSlot = Math.floor(tierIndex / orbitBands.length);
        const tierAngle = -Math.PI / 2 + (orbitSlot / orbitPeers) * TAU + solarBand * .22 + (system.id === 'rhetoric' ? .18 : system.id === 'discourse' ? -.12 : 0);
        const tierDistance = orbitBands[solarBand];
        const tierX = macro.x + Math.cos(tierAngle) * tierDistance;
        const tierY = macro.y + Math.sin(tierAngle) * tierDistance * .78;
        const features = FEATURE_PLANETS.filter((feature) => feature.tier === tier.id);
        features.forEach((feature, featureIndex) => {
          const featureAngle = -Math.PI / 2 + (featureIndex / Math.max(features.length, 1)) * TAU + this.random() * .22;
          const featureRadius = .012 + this.random() * .018;
          this.nodes.push({
            id: feature.code,
            feature,
            system: system.id,
            tier: tier.id,
            systemOrder: SYSTEMS.indexOf(system),
            tierOrder: tierIndex,
            featureIndex,
            tierLead: featureIndex === 0,
            solarBand,
            solarRadius: tierDistance,
            solarAngle: tierAngle,
            galaxyX: tierX + Math.cos(featureAngle) * featureRadius,
            galaxyY: tierY + Math.sin(featureAngle) * featureRadius,
            localAngle: featureAngle,
            localRadius: .028 + this.random() * .028,
            z: macro.z + (this.random() - .5) * .55,
            w: (this.random() - .5) * 1.9,
            r: 2.2 + this.random() * 2.4,
            phase: this.random() * TAU,
            energy: .35 + this.random() * .65,
            sentiment: feature.sentiment
          });
        });
        const tierNodes = this.nodes.filter((node) => node.tier === tier.id);
        for (let index = 1; index < tierNodes.length; index += 1) {
          this.edges.push({ a: tierNodes[index], b: tierNodes[Math.max(0, Math.floor((index - 1) / 2))], type: 'feature', strength: .18 + this.random() * .38, phase: this.random() * TAU });
        }
      });
      const leads = this.nodes.filter((node) => node.system === system.id && node.tierLead);
      for (let index = 0; index < leads.length; index += 1) {
        this.edges.push({ a: leads[index], b: leads[(index + 1) % leads.length], type: 'tier', strength: .5, phase: this.random() * TAU });
      }
    }
    const bridgePairs = [
      ['semicolon_colon_rate', 'clause_depth_mean'],
      ['source_integration_style', 'signal_verb_entropy'],
      ['transition_predictability', 'thematic_progression_score'],
      ['revision_depth', 'conclusion_strategy_score'],
      ['error_topology_consistency', 'punctuation_diversity']
    ];
    for (const [first, second] of bridgePairs) {
      const a = this.nodes.find((node) => node.id === first);
      const b = this.nodes.find((node) => node.id === second);
      const isFeaturedRevelation = REVELATION_PAIR.every((code) => code === first || code === second);
      if (a && b) this.edges.push({ a, b, type: 'bridge', strength: .85, relevance: isFeaturedRevelation ? 91 : 76 + Math.round(this.random() * 20), phase: this.random() * TAU, emergent: true });
    }
  }

  bind() {
    const options = { signal: this.abort.signal };
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(this.canvas.parentElement);
    this.move = (event) => {
      const bounds = this.canvas.getBoundingClientRect();
      this.pointer = { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
      if (this.drag) {
        const dx = event.clientX - this.drag.x;
        const dy = event.clientY - this.drag.y;
        this.drag.moved = Math.hypot(dx, dy) > 5;
        if (this.drag.mode === 'orbit') {
          this.camera.targetYaw = this.drag.yaw + dx * .008;
          this.camera.targetPitch = clamp(this.drag.pitch + dy * .006, -1.05, 1.05);
        } else {
          this.camera.targetX = clamp(this.drag.cameraX + dx, -this.w * .65, this.w * .65);
          this.camera.targetY = clamp(this.drag.cameraY + dy, -this.h * .65, this.h * .65);
        }
        this.setHover(null);
        this.canvas.style.cursor = 'grabbing';
        return;
      }
      this.parallax.targetX = clamp((this.pointer.x / bounds.width - .5) * 2, -1, 1);
      this.parallax.targetY = clamp((this.pointer.y / bounds.height - .5) * 2, -1, 1);
      this.setHover(this.closest(this.pointer.x, this.pointer.y));
      this.canvas.style.cursor = this.hover ? 'pointer' : this.camera.mode === 'orbit' ? 'grab' : 'move';
    };
    this.leave = () => { this.setHover(null); this.parallax.targetX = 0; this.parallax.targetY = 0; };
    this.down = (event) => {
      this.setHover(null);
      this.drag = { x: event.clientX, y: event.clientY, cameraX: this.camera.targetX, cameraY: this.camera.targetY, yaw: this.camera.targetYaw, pitch: this.camera.targetPitch, mode: event.shiftKey ? 'pan' : this.camera.mode, moved: false };
      this.canvas.setPointerCapture(event.pointerId);
    };
    this.up = (event) => {
      const wasDrag = this.drag?.moved;
      this.drag = null;
      this.canvas.style.cursor = this.hover ? 'pointer' : this.camera.mode === 'orbit' ? 'grab' : 'move';
      if (!wasDrag) {
        const bounds = this.canvas.getBoundingClientRect();
        this.setHover(this.closest(event.clientX - bounds.left, event.clientY - bounds.top));
        if (this.hover) this.selectNode(this.hover);
      }
    };
    this.wheel = (event) => {
      event.preventDefault();
      this.camera.targetZoom = clamp(this.camera.targetZoom * (event.deltaY > 0 ? .9 : 1.12), .48, 2.75);
      this.updateZoomReadout();
    };
    this.canvas.addEventListener('pointermove', this.move, options);
    this.canvas.addEventListener('pointerleave', this.leave, options);
    this.canvas.addEventListener('pointerdown', this.down, options);
    this.canvas.addEventListener('pointerup', this.up, options);
    this.canvas.addEventListener('wheel', this.wheel, { passive: false, signal: this.abort.signal });
    this.host.querySelector('[data-pulse-back]')?.addEventListener('click', () => this.goBack(), options);
    this.host.querySelector('[data-evidence-close]')?.addEventListener('click', () => this.goBack(), options);
    this.layout.querySelector('[data-pulse-all]')?.addEventListener('click', () => this.openGalaxy(), options);
    this.host.querySelector('[data-pulse-path]')?.addEventListener('click', (event) => {
      const button = event.target.closest('button[data-crumb]');
      if (!button) return;
      if (button.dataset.crumb === 'galaxy') this.openGalaxy();
      if (button.dataset.crumb === 'system') this.openSystem(button.dataset.value, { record: false });
      if (button.dataset.crumb === 'tier') this.openTier(Number(button.dataset.value), { record: false });
    }, options);
    this.layout.querySelector('[data-hierarchy-index]')?.addEventListener('click', (event) => {
      const button = event.target.closest('button[data-hierarchy-type]');
      if (!button) return;
      if (button.dataset.hierarchyType === 'system') this.openSystem(button.dataset.value);
      if (button.dataset.hierarchyType === 'tier') this.openTier(Number(button.dataset.value));
      if (button.dataset.hierarchyType === 'feature') this.openFeature(button.dataset.value);
    }, options);
    this.host.querySelectorAll('[data-related-feature]').forEach((button) => button.addEventListener('click', () => this.openFeature(button.dataset.relatedFeature), options));
    this.layout.querySelectorAll('[data-sentiment]').forEach((button) => button.addEventListener('click', () => {
      this.sentiment = button.dataset.sentiment;
      this.layout.querySelectorAll('[data-sentiment]').forEach((item) => {
        item.classList.toggle('active', item === button);
        item.setAttribute('aria-pressed', String(item === button));
      });
      const value = this.layout.querySelector('[data-sentiment-value]');
      if (value) value.textContent = STATUS_LABELS[this.sentiment] || 'ALL';
    }, options));
    const threshold = this.layout.querySelector('[data-threshold]');
    threshold?.addEventListener('input', (event) => {
      this.threshold = Number(event.target.value);
      const label = this.layout.querySelector('[data-threshold-label]');
      if (label) label.textContent = event.target.value;
    }, options);
    this.layout.querySelector('[data-engagement]')?.addEventListener('change', (event) => { this.engagement = event.target.checked; }, options);
    this.layout.querySelector('[data-focus-revelation]')?.addEventListener('click', () => this.focusRevelation(), options);
    this.host.querySelectorAll('[data-pulse-camera]').forEach((button) => button.addEventListener('click', () => {
      const action = button.dataset.pulseCamera;
      if (action === 'in') this.camera.targetZoom = clamp(this.camera.targetZoom * 1.2, .48, 2.75);
      if (action === 'out') this.camera.targetZoom = clamp(this.camera.targetZoom * .82, .48, 2.75);
      if (action === 'reset') this.resetCamera();
      if (action === 'mode') this.setCameraMode(this.camera.mode === 'orbit' ? 'pan' : 'orbit');
      this.updateZoomReadout();
    }, options));
    this.host.querySelector('[data-pulse-dimension]')?.addEventListener('input', (event) => {
      this.targetDimension = Number(event.target.value) / 100;
      this.updateDimensionReadout();
    }, options);
    this.host.querySelector('[data-pulse-dimension-motion]')?.addEventListener('click', () => {
      if (!this.motion) return;
      this.dimensionFlow = !this.dimensionFlow;
      this.updateDimensionMotion();
    }, options);
    this.host.querySelector('[data-pulse-compare]')?.addEventListener('click', () => {
      this.compareBaseline = !this.compareBaseline;
      const button = this.host.querySelector('[data-pulse-compare]');
      if (button) {
        button.setAttribute('aria-pressed', String(this.compareBaseline));
        button.textContent = this.compareBaseline ? '◩ Comparing' : '◫ Baseline';
      }
    }, options);
    this.motionChange = (event) => {
      this.motion = !event.matches;
      if (!this.motion) {
        this.dimensionFlow = false;
        this.nodes.forEach((node) => { node.trail = []; });
      }
      this.updateDimensionMotion();
    };
    this.motionQuery.addEventListener?.('change', this.motionChange);
    this.visibilityChange = () => { this.pageVisible = !document.hidden; this.syncLoop(); };
    document.addEventListener('visibilitychange', this.visibilityChange, options);
    if ('IntersectionObserver' in window) {
      this.intersectionObserver = new IntersectionObserver(entries => {
        this.inViewport = entries[0]?.isIntersecting !== false;
        this.syncLoop();
      }, { threshold:.01 });
      this.intersectionObserver.observe(this.host);
    }
  }

  syncLoop() {
    const shouldRun = this.pageVisible && this.inViewport;
    if (!shouldRun && this.raf !== null) {
      cancelAnimationFrame(this.raf);
      this.raf = null;
      return;
    }
    if (shouldRun && this.raf === null) {
      this.lastTime = performance.now();
      this.raf = requestAnimationFrame(this.loop);
    }
  }

  focusRevelation() {
    const edge = this.edges.find((candidate) => candidate.emergent
      && REVELATION_PAIR.every((code) => candidate.a.id === code || candidate.b.id === code));
    if (!edge) return;

    this.sentiment = 'all';
    this.layout.querySelectorAll('[data-sentiment]').forEach((button) => {
      const active = button.dataset.sentiment === 'all';
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    const status = this.layout.querySelector('[data-sentiment-value]');
    if (status) status.textContent = 'ALL';

    this.focusEdge = edge;
    this.openFeature(REVELATION_PAIR[0]);
  }

  setHover(node) {
    const wasFrozen = this.hoverFreeze;
    this.hover = node;
    this.hoverFreeze = Boolean(node) && !this.drag;
    if (wasFrozen !== this.hoverFreeze) this.updateDimensionMotion();
  }

  captureTransition() {
    this.saveCameraState();
    this.nodes.forEach((node) => {
      if (node.screen && this.w && this.h) node.transitionFrom = { x: node.screen.x / this.w, y: node.screen.y / this.h, scale: node.screen.scale };
    });
    this.transitionStarted = performance.now();
    this.setHover(null);
  }

  currentViewState() {
    return { level: this.level, system: this.selectedSystem, tier: this.selectedTier, feature: this.selectedFeature };
  }

  viewKey(state = this.currentViewState()) {
    return [state.level, state.system ?? 'all', state.tier ?? 'none', state.feature ?? 'none'].join(':');
  }

  saveCameraState() {
    this.cameraSnapshots.set(this.viewKey(), {
      zoom: this.camera.targetZoom,
      x: this.camera.targetX,
      y: this.camera.targetY,
      yaw: this.camera.targetYaw,
      pitch: this.camera.targetPitch,
      mode: this.camera.mode
    });
  }

  restoreCameraState() {
    const saved = this.cameraSnapshots.get(this.viewKey());
    if (!saved) {
      this.resetCamera(false);
    } else {
      this.camera.targetZoom = saved.zoom;
      this.camera.targetX = saved.x;
      this.camera.targetY = saved.y;
      this.camera.targetYaw = saved.yaw;
      this.camera.targetPitch = saved.pitch;
      this.setCameraMode(saved.mode);
    }
    this.updateZoomReadout();
  }

  applyView(state, { record = true, clearHistory = false } = {}) {
    const previous = this.currentViewState();
    this.captureTransition();
    if (clearHistory) this.navigationHistory = [];
    else if (record && previous.level !== state.level) this.navigationHistory.push(previous);
    this.level = state.level;
    this.selectedSystem = state.system ?? null;
    this.selectedTier = state.tier ?? null;
    this.selectedFeature = state.feature ?? null;
    this.restoreCameraState();
    this.updateInterface();
    this.focusInterfaceHeading();
  }

  focusInterfaceHeading() {
    requestAnimationFrame(() => {
      const target = this.selectedFeature
        ? this.host.querySelector('[data-evidence-title]')
        : this.layout.querySelector('[data-index-title]');
      if (!target) return;
      target.tabIndex = -1;
      target.focus({ preventScroll:true });
    });
  }

  openGalaxy(options = {}) {
    this.applyView({ level: 'galaxy', system: null, tier: null, feature: null }, { record: false, clearHistory: options.clearHistory !== false });
  }

  openSystem(system, options = {}) {
    if (!SYSTEM_BY_ID[system]) return;
    this.applyView({ level: 'system', system, tier: null, feature: null }, options);
  }

  openTier(tier, options = {}) {
    const selected = TIER_BY_ID[tier];
    if (!selected) return;
    this.applyView({ level: 'tier', system: selected.system, tier: selected.id, feature: null }, options);
  }

  openFeature(code, options = {}) {
    const selected = FEATURE_BY_CODE[code];
    if (!selected) return;
    this.applyView({ level: 'evidence', system: selected.system, tier: selected.tier, feature: selected.code }, options);
  }

  goBack() {
    const previous = this.navigationHistory.pop();
    if (previous) {
      this.applyView(previous, { record: false });
      return;
    }
    if (this.level === 'evidence') this.openTier(this.selectedTier, { record: false });
    else if (this.level === 'tier') this.openSystem(this.selectedSystem, { record: false });
    else if (this.level === 'system') this.openGalaxy();
  }

  selectNode(node) {
    if (node?.kind === 'system-sun') {
      this.openSystem(node.system);
      return;
    }
    if (this.level === 'galaxy') this.openTier(node.tier);
    else if (this.level === 'system') this.openTier(node.tier);
    else this.openFeature(node.feature.code);
  }

  resetCamera(update = true) {
    this.camera.targetZoom = 1;
    this.camera.targetX = 0;
    this.camera.targetY = 0;
    this.camera.targetYaw = 0;
    this.camera.targetPitch = 0;
    if (update) this.updateZoomReadout();
  }

  updateZoomReadout() {
    const element = this.host.querySelector('[data-pulse-zoom]');
    if (element) element.textContent = `${Math.round(this.camera.targetZoom * 100)}%`;
  }

  updateDimensionReadout() {
    const value = Math.round(this.targetDimension * 100);
    const element = this.host.querySelector('[data-pulse-dimension-value]');
    const moment = this.host.querySelector('[data-pulse-dimension-moment]');
    const input = this.host.querySelector('[data-pulse-dimension]');
    if (element) element.textContent = `${value}%`;
    if (moment) moment.textContent = DIMENSION_MILESTONES.find((item) => this.targetDimension <= item.until)?.label || DIMENSION_MILESTONES.at(-1).label;
    if (input) input.value = String(value);
  }

  updateDimensionMotion() {
    const button = this.host.querySelector('[data-pulse-dimension-motion]');
    if (!button) return;
    button.textContent = !this.motion
      ? 'Motion reduced'
      : this.hoverFreeze && this.dimensionFlow
        ? '◉ Selection held'
        : this.dimensionFlow
          ? 'Ⅱ Pause time'
          : '▶ Play time';
    button.setAttribute('aria-pressed', String(this.dimensionFlow));
    button.setAttribute('aria-disabled', String(!this.motion));
    this.host.classList.toggle('is-hover-held', this.hoverFreeze && this.dimensionFlow);
  }

  setCameraMode(mode) {
    this.camera.mode = mode;
    const button = this.host.querySelector('[data-pulse-camera="mode"]');
    const label = this.host.querySelector('[data-pulse-mode]');
    const gesture = this.host.querySelector('[data-pulse-gesture]');
    if (button) button.setAttribute('aria-pressed', String(mode === 'orbit'));
    if (label) label.textContent = mode === 'orbit' ? 'Orbit' : 'Pan';
    if (gesture) gesture.textContent = mode === 'orbit' ? 'DRAG TO ORBIT' : 'DRAG TO PAN';
    this.canvas.style.cursor = mode === 'orbit' ? 'grab' : 'move';
  }

  renderBreadcrumb() {
    const path = this.host.querySelector('[data-pulse-path]');
    if (!path) return;
    const parts = [`<button type="button" data-crumb="galaxy">All writing divisions</button>`];
    if (this.selectedSystem) parts.push(`<span>›</span><button type="button" data-crumb="system" data-value="${this.selectedSystem}">${SYSTEM_BY_ID[this.selectedSystem].name}</button>`);
    if (this.selectedTier !== null) parts.push(`<span>›</span><button type="button" data-crumb="tier" data-value="${this.selectedTier}">${TIER_BY_ID[this.selectedTier].name}</button>`);
    if (this.selectedFeature) parts.push(`<span>›</span><b>${FEATURE_BY_CODE[this.selectedFeature].professorLabel}</b>`);
    path.innerHTML = parts.join('');
  }

  renderHierarchyIndex() {
    const list = this.layout.querySelector('[data-hierarchy-index]');
    const title = this.layout.querySelector('[data-index-title]');
    const count = this.layout.querySelector('[data-index-count]');
    const copy = this.layout.querySelector('[data-index-copy]');
    if (!list) return;
    if (this.level === 'galaxy') {
      list.setAttribute('aria-label', 'Surface, Discourse, and Rhetoric writing divisions');
      if (title) title.textContent = 'THREE WRITING DIVISIONS';
      if (count) count.textContent = '103 WRITING TRAITS';
      if (copy) copy.textContent = 'Choose the Surface, Discourse, or Rhetoric sun. Its tier planets appear next, followed by concrete current and baseline examples.';
      list.innerHTML = SYSTEMS.map((system, index) => {
        const featureCount = FEATURE_PLANETS.filter((feature) => feature.system === system.id).length;
        return `<button type="button" data-hierarchy-type="system" data-value="${system.id}" style="--c:${system.color}"><i></i><span><b>0${index + 1} · ${system.name}</b><small>${systemTierSummary(system).toLowerCase()} · ${featureCount} writing traits</small></span><em>↗</em></button>`;
      }).join('');
      return;
    }
    if (this.level === 'system') {
      const system = SYSTEM_BY_ID[this.selectedSystem];
      const tiers = TIERS.filter((tier) => tier.system === system.id);
      list.setAttribute('aria-label', `Trait groups in the ${system.name} division`);
      if (title) title.textContent = system.short;
      if (count) count.textContent = `${systemTierSummary(system)} · ${FEATURE_PLANETS.filter((feature) => feature.system === system.id).length} FEATURES`;
      if (copy) copy.textContent = system.description;
      list.innerHTML = tiers.map((tier) => `<button type="button" data-hierarchy-type="tier" data-value="${tier.id}" style="--c:${system.color}"><i></i><span><b>${tierLabel(tier.id)} · ${tier.name}</b><small>${tier.features.length} writing traits · ${tier.status}</small></span><em>↗</em></button>`).join('');
      return;
    }
    const tier = TIER_BY_ID[this.selectedTier];
    const features = FEATURE_PLANETS.filter((feature) => feature.tier === tier.id);
    list.setAttribute('aria-label', `Writing traits in ${tier.name}`);
    if (title) title.textContent = `${tierLabel(tier.id)} · ${tier.name}`;
    if (count) count.textContent = `${features.length} WRITING TRAITS`;
    if (copy) copy.textContent = tier.description;
    list.innerHTML = features.map((feature, index) => `<button type="button" data-hierarchy-type="feature" data-value="${feature.code}" class="${feature.code === this.selectedFeature ? 'selected-feature' : ''}" ${feature.code === this.selectedFeature ? 'aria-current="true"' : ''} style="--c:${feature.color}"><i>${String(index + 1).padStart(2, '0')}</i><span><b>${feature.professorLabel}</b><small>${feature.technicalLabel} · ${feature.status}</small></span><em>↗</em></button>`).join('');
  }

  updateInterface() {
    const system = this.selectedSystem ? SYSTEM_BY_ID[this.selectedSystem] : null;
    const tier = this.selectedTier !== null ? TIER_BY_ID[this.selectedTier] : null;
    const feature = this.selectedFeature ? FEATURE_BY_CODE[this.selectedFeature] : null;
    const set = (selector, value) => { const element = this.host.querySelector(selector); if (element) element.textContent = value; };
    const labels = { galaxy: 'ALL DIVISIONS', system: 'WRITING DIVISION', tier: 'TRAIT GROUP', evidence: 'WRITING TRAIT' };
    set('[data-pulse-level]', labels[this.level]);
    const instructions = {
      galaxy: 'Select the Surface, Discourse, or Rhetoric sun—or an orbiting tier—to explore.',
      system: 'Select a trait group to reveal its writing traits.',
      tier: 'Select a numbered trait to compare a current example with the baseline.',
      evidence: 'Inspect the current and baseline examples, then open a related trait or the highlighted passage.'
    };
    set('[data-pulse-instruction]', instructions[this.level]);
    this.renderBreadcrumb();
    const back = this.host.querySelector('[data-pulse-back]');
    if (back) {
      back.hidden = this.level === 'galaxy';
      const destination = this.navigationHistory.at(-1)?.level || (this.level === 'evidence' ? 'tier' : this.level === 'tier' ? 'system' : 'galaxy');
      const destinationLabel = destination === 'tier' ? 'trait group' : destination === 'system' ? 'writing division' : 'all divisions';
      back.textContent = `← Back to ${destinationLabel}`;
    }
    const revelation = this.layout.querySelector('[data-revelation]');
    if (revelation) revelation.hidden = this.level !== 'galaxy';
    const allGalaxies = this.layout.querySelector('[data-pulse-all]');
    if (allGalaxies) {
      allGalaxies.hidden = this.level === 'galaxy';
      allGalaxies.textContent = '← View all three writing divisions';
    }
    const evidence = this.host.querySelector('[data-pulse-evidence]');
    if (evidence) evidence.hidden = !feature;
    this.host.classList.toggle('is-evidence', Boolean(feature));
    this.host.dataset.pulseState = this.level;
    this.layout.querySelector('.pulse-controls').dataset.hierarchyLevel = this.level;
    this.renderHierarchyIndex();
    if (feature) {
      set('[data-evidence-kicker]', `${tierLabel(tier.id)} · ${feature.technicalLabel}`);
      set('[data-evidence-title]', feature.professorLabel);
      set('[data-evidence-reading]', feature.reading);
      set('[data-evidence-current]', feature.current);
      set('[data-evidence-baseline]', feature.baseline);
      set('[data-evidence-meaning]', `${feature.professorLabel} is the professor-facing name for ${feature.technicalLabel}. It belongs to ${tier.name} and should be interpreted with connected traits, never as an isolated verdict.`);
      const siblings = FEATURE_PLANETS.filter((item) => item.tier === feature.tier && item.code !== feature.code);
      const related = siblings.length ? [siblings[(feature.index + 1) % siblings.length], siblings[(feature.index + 3) % siblings.length]] : [];
      this.host.querySelectorAll('[data-related-feature]').forEach((button, index) => {
        const item = related[index] || feature;
        button.dataset.relatedFeature = item.code;
        const name = button.querySelector('b');
        const description = button.querySelector('small');
        if (name) name.textContent = item.professorLabel;
        if (description) description.textContent = item.technicalLabel;
      });
    }
    const aria = this.level === 'galaxy'
      ? 'Interactive writing-pattern galaxy with three named suns: Surface, Discourse, and Rhetoric; seventeen orbiting trait groups, one comparison orbit, and 103 writing traits'
      : this.level === 'system'
        ? `${system.name} with ${system.tiers.length} selectable trait groups`
        : this.level === 'tier'
          ? `${tier.name} with ${tier.features.length} selectable writing traits`
          : `${feature.professorLabel}, technical measure ${feature.technicalLabel}, compared with Morgan Lee’s illustrative baseline`;
    this.canvas.setAttribute('aria-label', `${aria}, fourth-dimension time ${Math.round(this.dimension * 100)} percent`);
    const status = this.host.querySelector('[data-pulse-status]');
    if (status) status.textContent = feature
      ? `${feature.professorLabel} opened. Current and illustrative baseline examples are available.`
      : `${labels[this.level]}. ${instructions[this.level]}`;
    this.updateDimensionMotion();
    this.updateDimensionReadout();
    this.setCameraMode(this.camera.mode);
  }

  resize() {
    const bounds = this.canvas.parentElement.getBoundingClientRect();
    this.dpr = Math.min(devicePixelRatio || 1, 2);
    this.w = bounds.width;
    this.h = bounds.height;
    this.canvas.width = Math.round(this.w * this.dpr);
    this.canvas.height = Math.round(this.h * this.dpr);
    this.canvas.style.width = `${this.w}px`;
    this.canvas.style.height = `${this.h}px`;
    this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
  }

  featureRingPosition(node) {
    const nodes = this.nodes.filter((item) => item.tier === node.tier);
    const count = nodes.length;
    let ring = .21;
    let slot = node.featureIndex;
    let ringCount = count;
    if (count > 9) {
      const innerCount = Math.ceil(count / 2);
      if (node.featureIndex < innerCount) {
        ring = .17;
        ringCount = innerCount;
      } else {
        ring = .29;
        slot = node.featureIndex - innerCount;
        ringCount = count - innerCount;
      }
    }
    return { angle: -Math.PI / 2 + (slot / ringCount) * TAU + this.dimension * node.w * .18, ring };
  }

  targetPosition(node) {
    const fourth = (this.dimension - .5) * 2;
    const timeAngle = node.localAngle + this.dimension * node.w * 1.15;
    const shiftX = Math.sin(node.phase + this.dimension * TAU) * node.w * .026;
    const shiftY = Math.cos(node.phase * .8 + this.dimension * TAU) * node.w * .022;
    const depthScale = clamp(1 + node.w * fourth * .15, .7, 1.34);
    if (this.level === 'galaxy') {
      return { x: .5 + (node.galaxyX + shiftX) * .86, y: .48 + (node.galaxyY + shiftY) * .86, scale: (.78 + node.z * .2) * depthScale };
    }
    if (this.level === 'system') {
      const system = SYSTEM_BY_ID[this.selectedSystem];
      const tierCount = system.tiers.length;
      const tierIndex = system.tiers.indexOf(node.tier);
      const systemRotation = system.id === 'surface' ? .32 : system.id === 'rhetoric' ? -.12 : .08;
      const tierAngle = -Math.PI / 2 + (tierIndex / tierCount) * TAU + systemRotation + this.dimension * .08;
      const tierX = Math.cos(tierAngle) * .29;
      const tierY = Math.sin(tierAngle) * .235;
      return {
        x: .5 + tierX + Math.cos(timeAngle) * node.localRadius + shiftX * .32,
        y: .55 + tierY + Math.sin(timeAngle) * node.localRadius + shiftY * .32,
        scale: (node.tierLead ? 1.8 : 1.08) * depthScale
      };
    }
    const ringPosition = this.featureRingPosition(node);
    if (this.level === 'tier') {
      return {
        x: .5 + Math.cos(ringPosition.angle) * ringPosition.ring + shiftX * .25,
        y: .49 + Math.sin(ringPosition.angle) * ringPosition.ring * .82 + shiftY * .25,
        scale: 1.8 * depthScale
      };
    }
    const selected = node.feature.code === this.selectedFeature;
    return selected
      ? { x: .30 + shiftX * .18, y: .48 + shiftY * .18, scale: 3 * depthScale }
      : { x: .30 + Math.cos(ringPosition.angle) * .19 + shiftX * .15, y: .48 + Math.sin(ringPosition.angle) * .16 + shiftY * .15, scale: .78 * depthScale };
  }

  cameraPoint(x, y) {
    const centerX = this.level === 'evidence' ? this.w * .30 : this.w * .5;
    const centerY = this.h * .48;
    return { x: centerX + (x - centerX) * this.camera.zoom + this.camera.x, y: centerY + (y - centerY) * this.camera.zoom + this.camera.y };
  }

  projectSystemSun(system) {
    const macro = MACRO_POSITIONS[system.id];
    let x = macro.x * .86;
    let y = macro.y * .86;
    let z = macro.z * .48;
    let cosine = Math.cos(this.camera.yaw);
    let sine = Math.sin(this.camera.yaw);
    [x, z] = [x * cosine - z * sine, x * sine + z * cosine];
    cosine = Math.cos(this.camera.pitch);
    sine = Math.sin(this.camera.pitch);
    [y, z] = [y * cosine - z * sine, y * sine + z * cosine];
    const perspective = clamp(1 / (1 - z * .28), .65, 1.52);
    const rawX = this.w * (.5 + x * perspective) + this.parallax.x * macro.z * 18;
    const rawY = this.h * (.48 + y * perspective) + this.parallax.y * macro.z * 18;
    const camera = this.cameraPoint(rawX, rawY);
    return { x: camera.x, y: camera.y, scale: this.camera.zoom * perspective, depth: z };
  }

  project(node, now) {
    const target = this.targetPosition(node);
    const duration = this.motion ? 760 : 0;
    const mix = duration ? ease(clamp((now - this.transitionStarted) / duration, 0, 1)) : 1;
    const origin = node.transitionFrom || target;
    const position = { x: lerp(origin.x, target.x, mix), y: lerp(origin.y, target.y, mix), scale: lerp(origin.scale, target.scale, mix) };
    const breathe = this.motion && this.engagement && !this.hoverFreeze ? Math.sin(now * .00042 + node.phase) * .0045 * node.energy : 0;
    const centerNorm = this.level === 'evidence' ? .30 : .5;
    let x = position.x - centerNorm + breathe * Math.cos(node.phase);
    let y = position.y - .48 + breathe * Math.sin(node.phase);
    let z = node.z * .48 + node.w * (this.dimension - .5) * .32;
    let cosine = Math.cos(this.camera.yaw);
    let sine = Math.sin(this.camera.yaw);
    [x, z] = [x * cosine - z * sine, x * sine + z * cosine];
    cosine = Math.cos(this.camera.pitch);
    sine = Math.sin(this.camera.pitch);
    [y, z] = [y * cosine - z * sine, y * sine + z * cosine];
    const perspective = clamp(1 / (1 - z * .28), .65, 1.52);
    const depthShift = this.motion ? node.z * 18 : 0;
    const rawX = this.w * (centerNorm + x * perspective) + this.parallax.x * depthShift;
    const rawY = this.h * (.48 + y * perspective) + this.parallax.y * depthShift;
    const camera = this.cameraPoint(rawX, rawY);
    return { x: camera.x, y: camera.y, scale: position.scale * this.camera.zoom * perspective, depth: z };
  }

  visible(node) {
    if (this.level !== 'galaxy' && node.system !== this.selectedSystem) return false;
    if ((this.level === 'tier' || this.level === 'evidence') && node.tier !== this.selectedTier) return false;
    return this.sentiment === 'all' || node.sentiment === this.sentiment || node.tierLead || node.feature.code === this.selectedFeature;
  }

  closest(x, y) {
    if (this.level === 'galaxy') {
      let sunHit = null;
      let sunDistance = Infinity;
      this.systemSuns.forEach((sun) => {
        const distance = Math.hypot(x - sun.screen.x, y - sun.screen.y);
        if (distance <= sun.radius + 15 && distance < sunDistance) {
          sunDistance = distance;
          sunHit = sun;
        }
      });
      if (sunHit) return sunHit;
      let tierHit = null;
      let tierDistance = 34;
      TIERS.forEach((tier) => {
        const members = this.nodes.filter((node) => node.tier === tier.id && this.visible(node));
        const center = this.screenCenter(members);
        const distance = Math.hypot(x - center.x, y - center.y);
        if (distance < tierDistance) {
          tierDistance = distance;
          tierHit = members.find((node) => node.tierLead) || members[0] || null;
        }
      });
      if (tierHit) return tierHit;
    }
    let best = null;
    let distanceLimit = this.level === 'galaxy' ? 22 : this.level === 'system' ? 29 : 36;
    this.nodes.forEach((node) => {
      if (!node.screen || !this.visible(node)) return;
      const distance = Math.hypot(x - node.screen.x, y - node.screen.y);
      if (distance < distanceLimit) { distanceLimit = distance; best = node; }
    });
    return best;
  }

  glow(x, y, radius, color, alpha) {
    const [red, green, blue] = rgb(color);
    const gradient = this.ctx.createRadialGradient(x, y, 0, x, y, radius);
    gradient.addColorStop(0, `rgba(${red},${green},${blue},${alpha})`);
    gradient.addColorStop(1, `rgba(${red},${green},${blue},0)`);
    this.ctx.fillStyle = gradient;
    this.ctx.beginPath();
    this.ctx.arc(x, y, radius, 0, TAU);
    this.ctx.fill();
  }

  background(now) {
    const context = this.ctx;
    const centerX = this.level === 'evidence' ? this.w * .30 : this.w * .5;
    const gradient = context.createRadialGradient(centerX, this.h * .45, 0, centerX, this.h * .45, this.w * .72);
    gradient.addColorStop(0, '#10291f');
    gradient.addColorStop(.46, '#071711');
    gradient.addColorStop(1, '#020806');
    context.fillStyle = gradient;
    context.fillRect(0, 0, this.w, this.h);
    context.strokeStyle = 'rgba(132,164,149,.075)';
    context.lineWidth = 1;
    for (let ring = 1; ring < 8; ring += 1) {
      context.beginPath();
      context.ellipse(centerX, this.h * .48, ring * Math.min(this.w, this.h) * .074, ring * Math.min(this.w, this.h) * .058, this.camera.yaw * .08, 0, TAU);
      context.stroke();
    }
    const ambientMotion = this.motion && (this.dimensionFlow || this.engagement);
    for (let index = 0; index < 76; index += 1) {
      const x = (index * 97.3) % this.w;
      const y = (index * 53.7) % this.h;
      const alpha = ambientMotion ? .07 + .06 * Math.sin(now * .001 + index) : .1;
      context.fillStyle = `rgba(198,220,208,${alpha})`;
      context.fillRect(x, y, index % 11 === 0 ? 1.5 : 1, index % 11 === 0 ? 1.5 : 1);
    }
  }

  screenCenter(nodes, fallbackX = this.w * .5, fallbackY = this.h * .48) {
    const visible = nodes.filter((node) => node.screen && this.visible(node));
    if (!visible.length) return { x: fallbackX, y: fallbackY, scale: 1 };
    return visible.reduce((sum, node) => ({ x: sum.x + node.screen.x / visible.length, y: sum.y + node.screen.y / visible.length, scale: sum.scale + node.screen.scale / visible.length }), { x: 0, y: 0, scale: 0 });
  }

  drawHierarchy() {
    const context = this.ctx;
    if (this.level === 'galaxy') {
      this.systemSuns = [];
      SYSTEMS.forEach((system) => {
        const members = this.nodes.filter((node) => node.system === system.id);
        const center = this.projectSystemSun(system);
        const sunRadius = clamp(31 * center.scale, 27, 43);
        this.systemSuns.push({ kind: 'system-sun', system: system.id, screen: { x: center.x, y: center.y }, radius: sunRadius });
        this.glow(center.x, center.y, Math.min(this.w, this.h) * .23, system.color, .075);
        const orbitBands = [...new Set(members.map((node) => node.solarRadius))].sort((a, b) => a - b);
        orbitBands.forEach((band, bandIndex) => {
          const radiusX = band * .86 * this.w * center.scale;
          const pitchScale = clamp(.76 + Math.cos(this.camera.pitch) * .2, .6, .96);
          const radiusY = band * .78 * .86 * this.h * center.scale * pitchScale;
          context.strokeStyle = `${system.color}${bandIndex === orbitBands.length - 1 ? '4f' : '33'}`;
          context.lineWidth = bandIndex === orbitBands.length - 1 ? 1.05 : .75;
          context.setLineDash(bandIndex % 2 ? [3, 7] : [1, 5]);
          context.beginPath();
          context.ellipse(center.x, center.y, radiusX, radiusY, this.camera.yaw * .12 - .08, 0, TAU);
          context.stroke();
        });
        context.setLineDash([]);
        TIERS.filter((tier) => tier.system === system.id).forEach((tier) => {
          const tierMembers = this.nodes.filter((node) => node.tier === tier.id);
          const tierCenter = this.screenCenter(tierMembers);
          const tierRadius = (12 + Math.min(tier.features.length, 8) * .7) * clamp(tierCenter.scale, .72, 1.28);
          const hovered = this.hover?.tier === tier.id;
          if (hovered) this.glow(tierCenter.x, tierCenter.y, tierRadius * 2.4, system.color, .16);
          context.strokeStyle = hovered ? `${system.color}b8` : `${system.color}32`;
          context.lineWidth = hovered ? 1.7 : .8;
          context.beginPath();
          context.arc(tierCenter.x, tierCenter.y, tierRadius, 0, TAU);
          context.stroke();
          context.lineWidth = 1;
          context.fillStyle = `${system.color}c2`;
          context.font = `500 ${hovered || this.camera.zoom >= 1.22 ? 10 : 9}px "DM Mono"`;
          context.textAlign = 'center';
          const compactTier = tier.id === 0 ? 'CMP' : `T${String(tier.id).padStart(2, '0')}`;
          const tierText = hovered || this.camera.zoom >= 1.22 ? short(tier.name, 19) : compactTier;
          context.fillText(tierText, tierCenter.x, tierCenter.y + tierRadius + 12);
        });
      });
      return;
    }
    if (this.level === 'system') {
      const system = SYSTEM_BY_ID[this.selectedSystem];
      const center = this.cameraPoint(this.w * .5, this.h * .55);
      const sunRadius = clamp(34 * this.camera.zoom, 29, 52);
      const [red, green, blue] = rgb(system.color);
      this.glow(center.x, center.y, sunRadius * 5.2, system.color, .24);
      const solarSurface = context.createRadialGradient(
        center.x - sunRadius * .34,
        center.y - sunRadius * .38,
        sunRadius * .05,
        center.x,
        center.y,
        sunRadius
      );
      solarSurface.addColorStop(0, 'rgba(255,255,247,.99)');
      solarSurface.addColorStop(.2, `rgba(${red},${green},${blue},1)`);
      solarSurface.addColorStop(.7, `rgba(${Math.round(red * .58)},${Math.round(green * .58)},${Math.round(blue * .58)},1)`);
      solarSurface.addColorStop(1, 'rgba(3,12,8,.98)');
      context.fillStyle = solarSurface;
      context.beginPath();
      context.arc(center.x, center.y, sunRadius, 0, TAU);
      context.fill();
      context.strokeStyle = `${system.color}d8`;
      context.lineWidth = 1.4;
      context.beginPath();
      context.arc(center.x, center.y, sunRadius + 5, 0, TAU);
      context.stroke();
      context.strokeStyle = `${system.color}55`;
      context.lineWidth = .8;
      context.beginPath();
      context.arc(center.x, center.y, sunRadius + 13, 0, TAU);
      context.stroke();
      context.fillStyle = '#07100d';
      context.font = `700 ${clamp(sunRadius * .31, 10.5, 14)}px "DM Mono"`;
      context.textAlign = 'center';
      context.textBaseline = 'middle';
      context.fillText(system.short, center.x, center.y + .5);
      context.textBaseline = 'alphabetic';
      const divisionFeatures = FEATURE_PLANETS.filter((feature) => feature.system === system.id).length;
      const systemSummary = `${systemTierSummary(system)} · ${divisionFeatures} TRAITS`;
      context.font = '600 9px "DM Mono"';
      const summaryWidth = context.measureText(systemSummary).width + 16;
      const summaryY = center.y + sunRadius + 24;
      context.fillStyle = 'rgba(4,13,9,.94)';
      context.fillRect(center.x - summaryWidth / 2, summaryY - 13, summaryWidth, 19);
      context.strokeStyle = `${system.color}58`;
      context.strokeRect(center.x - summaryWidth / 2, summaryY - 13, summaryWidth, 19);
      context.fillStyle = system.color;
      context.fillText(systemSummary, center.x, summaryY + 1);
      TIERS.filter((tier) => tier.system === system.id).forEach((tier) => {
        const members = this.nodes.filter((node) => node.tier === tier.id);
        const tierCenter = this.screenCenter(members);
        const radius = 36 * clamp(tierCenter.scale, .75, 1.35) * this.camera.zoom;
        context.strokeStyle = `${system.color}44`;
        context.setLineDash([3, 7]);
        context.beginPath();
        context.arc(tierCenter.x, tierCenter.y, radius, 0, TAU);
        context.stroke();
        context.setLineDash([]);
        const deltaX = tierCenter.x - center.x;
        const deltaY = tierCenter.y - center.y;
        const distance = Math.max(1, Math.hypot(deltaX, deltaY));
        const labelX = clamp(tierCenter.x + (deltaX / distance) * (radius + 16), 84, this.w - 84);
        const labelY = clamp(tierCenter.y + (deltaY / distance) * (radius + 13), 79, this.h - 30);
        context.fillStyle = '#eef3ef';
        context.font = '500 10px Manrope';
        context.fillText(short(tier.name, 22), labelX, labelY);
        context.fillStyle = system.color;
        context.font = '500 8px "DM Mono"';
        context.fillText(`${tierLabel(tier.id)} · ${tier.features.length}`, labelX, labelY + 14);
      });
      return;
    }
    const tier = TIER_BY_ID[this.selectedTier];
    const system = SYSTEM_BY_ID[tier.system];
    const center = this.cameraPoint(this.w * (this.level === 'evidence' ? .30 : .5), this.h * .49);
    this.glow(center.x, center.y, 68 * this.camera.zoom, system.color, .12);
    context.strokeStyle = `${system.color}55`;
    [46, 92, 144].forEach((radius) => {
      context.beginPath();
      context.ellipse(center.x, center.y, radius * this.camera.zoom, radius * .78 * this.camera.zoom, this.camera.yaw * .12, 0, TAU);
      context.stroke();
    });
    context.fillStyle = system.color;
    context.beginPath();
    context.arc(center.x, center.y, 6 * this.camera.zoom, 0, TAU);
    context.fill();
    if (this.level === 'tier') {
      context.fillStyle = '#f0f5f1';
      context.font = '500 11px "DM Mono"';
      context.textAlign = 'center';
      context.fillText(tierLabel(tier.id), center.x, center.y + 31 * this.camera.zoom);
      context.fillStyle = '#9fb0a7';
      context.font = '400 10px Manrope';
      context.fillText(`${tier.features.length} selectable writing traits`, center.x, center.y + 47 * this.camera.zoom);
    }
    if (this.level === 'evidence') {
      const selected = this.nodes.find((node) => node.feature.code === this.selectedFeature);
      if (selected?.screen) {
        context.fillStyle = '#f0f5f1';
        context.font = '500 12px Manrope';
        context.textAlign = 'center';
        context.fillText(short(selected.feature.professorLabel, 28), selected.screen.x, selected.screen.y - 38);
        context.fillStyle = system.color;
        context.font = '500 9px "DM Mono"';
        context.fillText('CURRENT FEATURE · BASELINE ORBIT', selected.screen.x, selected.screen.y - 22);
      }
    }
  }

  drawGalaxySuns(now) {
    if (this.level !== 'galaxy') return;
    const context = this.ctx;
    this.systemSuns.forEach((sun, index) => {
      const system = SYSTEM_BY_ID[sun.system];
      const featureCount = FEATURE_PLANETS.filter((feature) => feature.system === system.id).length;
      const hovered = this.hover === sun;
      const radius = sun.radius * (hovered ? 1.08 : 1);
      const spin = this.motion && this.dimensionFlow ? now * .00012 : this.dimension * .42 + index * .7;
      this.glow(sun.screen.x, sun.screen.y, radius * (hovered ? 5.4 : 4.5), system.color, hovered ? .32 : .22);
      context.save();
      context.translate(sun.screen.x, sun.screen.y);
      context.rotate(spin);
      context.strokeStyle = `${system.color}${hovered ? 'c8' : '78'}`;
      context.lineWidth = hovered ? 1.4 : .8;
      for (let ray = 0; ray < 16; ray += 1) {
        const angle = ray / 16 * TAU;
        const inner = radius * (1.18 + (ray % 3) * .05);
        const outer = radius * (1.46 + (ray % 4) * .07);
        context.beginPath();
        context.moveTo(Math.cos(angle) * inner, Math.sin(angle) * inner);
        context.lineTo(Math.cos(angle) * outer, Math.sin(angle) * outer);
        context.stroke();
      }
      context.restore();
      const [red, green, blue] = rgb(system.color);
      const surface = context.createRadialGradient(sun.screen.x - radius * .32, sun.screen.y - radius * .36, radius * .06, sun.screen.x, sun.screen.y, radius);
      surface.addColorStop(0, 'rgba(255,255,244,.98)');
      surface.addColorStop(.22, `rgba(${red},${green},${blue},1)`);
      surface.addColorStop(.72, `rgba(${Math.round(red * .58)},${Math.round(green * .58)},${Math.round(blue * .58)},1)`);
      surface.addColorStop(1, 'rgba(3,12,8,.98)');
      context.fillStyle = surface;
      context.beginPath();
      context.arc(sun.screen.x, sun.screen.y, radius, 0, TAU);
      context.fill();
      context.strokeStyle = hovered ? '#f4f8f2' : `${system.color}df`;
      context.lineWidth = hovered ? 2 : 1.1;
      context.beginPath();
      context.arc(sun.screen.x, sun.screen.y, radius + 3, 0, TAU);
      context.stroke();
      context.strokeStyle = `${system.color}5f`;
      context.lineWidth = .8;
      context.beginPath();
      context.arc(sun.screen.x, sun.screen.y, radius + 9, 0, TAU);
      context.stroke();
      context.fillStyle = '#07100d';
      context.font = `700 ${system.id === 'discourse' ? 10 : 11}px "DM Mono"`;
      context.textAlign = 'center';
      context.textBaseline = 'middle';
      context.fillText(system.short, sun.screen.x, sun.screen.y + .5);
      context.textBaseline = 'alphabetic';
      const summary = `${systemTierSummary(system)} · ${featureCount} TRAITS`;
      context.font = '600 8px "DM Mono"';
      const width = context.measureText(summary).width + 14;
      const labelY = sun.screen.y + radius + 19;
      context.fillStyle = 'rgba(4,13,9,.94)';
      context.fillRect(sun.screen.x - width / 2, labelY - 11, width, 17);
      context.strokeStyle = `${system.color}42`;
      context.strokeRect(sun.screen.x - width / 2, labelY - 11, width, 17);
      context.fillStyle = system.color;
      context.fillText(summary, sun.screen.x, labelY + 1);
    });
  }

  drawEdges(now) {
    const context = this.ctx;
    const ambientMotion = this.motion && (this.dimensionFlow || this.engagement);
    this.edges.forEach((edge) => {
      if (!this.visible(edge.a) || !this.visible(edge.b)) return;
      if (this.level === 'galaxy' && !edge.emergent) return;
      const a = edge.a.screen;
      const b = edge.b.screen;
      const focus = edge === this.focusEdge;
      if (edge.emergent && edge.relevance < this.threshold && !focus) return;
      const pulse = ambientMotion ? .5 + .5 * Math.sin(now * .0014 + edge.phase) : .55;
      const systemColor = SYSTEM_BY_ID[edge.a.system].color;
      context.strokeStyle = edge.emergent ? `rgba(213,243,111,${focus ? .92 : .16 + pulse * .22})` : edge.type === 'tier' ? `${systemColor}2e` : 'rgba(122,156,139,.13)';
      context.lineWidth = focus ? 2 : edge.emergent ? 1.2 : edge.type === 'tier' ? .9 : .55;
      context.beginPath();
      context.moveTo(a.x, a.y);
      const bend = (edge.type === 'feature' ? 5 : 17) * Math.sin(edge.phase);
      context.quadraticCurveTo((a.x + b.x) / 2 + bend, (a.y + b.y) / 2 - bend, b.x, b.y);
      context.stroke();
    });
  }

  drawDimensionTrails() {
    const context = this.ctx;
    this.nodes.forEach((node) => {
      if (!this.visible(node) || (!node.tierLead && node.feature.code !== this.selectedFeature) || !node.trail?.length) return;
      context.beginPath();
      node.trail.forEach((point, index) => index ? context.lineTo(point.x, point.y) : context.moveTo(point.x, point.y));
      context.strokeStyle = `${SYSTEM_BY_ID[node.system].color}3d`;
      context.lineWidth = 1;
      context.stroke();
      node.trail.forEach((point, index) => {
        context.globalAlpha = (index + 1) / node.trail.length * .24;
        context.fillStyle = SYSTEM_BY_ID[node.system].color;
        context.beginPath();
        context.arc(point.x, point.y, 1.5, 0, TAU);
        context.fill();
      });
      context.globalAlpha = 1;
    });
  }

  drawBaselineComparison() {
    if (!this.compareBaseline) return;
    const context = this.ctx;
    const candidates = this.nodes.filter((node) => {
      if (!this.visible(node)) return false;
      if (this.level === 'tier') return true;
      if (this.level === 'evidence') return node.feature.code === this.selectedFeature;
      return node.tierLead;
    });
    const timeDistance = Math.max(.08, Math.abs(this.dimension - .08));
    context.setLineDash([2, 5]);
    candidates.forEach((node) => {
      const point = node.screen;
      const systemColor = SYSTEM_BY_ID[node.system].color;
      const ghostX = point.x - (node.w * 26 + Math.cos(node.phase) * 8) * timeDistance * this.camera.zoom;
      const ghostY = point.y + (Math.sin(node.phase) * 13 - node.z * 7) * timeDistance * this.camera.zoom;
      context.strokeStyle = `${systemColor}48`;
      context.lineWidth = .8;
      context.beginPath();
      context.moveTo(ghostX, ghostY);
      context.lineTo(point.x, point.y);
      context.stroke();
      context.fillStyle = `${systemColor}24`;
      context.beginPath();
      context.arc(ghostX, ghostY, this.level === 'tier' ? 4 : 3, 0, TAU);
      context.fill();
      context.strokeStyle = `${systemColor}82`;
      context.beginPath();
      context.arc(ghostX, ghostY, this.level === 'tier' ? 6 : 5, 0, TAU);
      context.stroke();
    });
    context.setLineDash([]);
    context.lineWidth = 1;
  }

  drawNodes() {
    const context = this.ctx;
    [...this.nodes].sort((a, b) => (a.screen?.depth || 0) - (b.screen?.depth || 0)).forEach((node) => {
      if (!this.visible(node)) return;
      const point = node.screen;
      const systemColor = SYSTEM_BY_ID[node.system].color;
      const statusColor = STATUS_COLORS[node.sentiment];
      const hover = node === this.hover;
      const selected = node.feature.code === this.selectedFeature;
      const focused = this.focusEdge && (node === this.focusEdge.a || node === this.focusEdge.b);
      const important = node.tierLead || this.level === 'tier' || selected || focused;
      const tierPlanetScale = this.level === 'galaxy' && node.tierLead ? 1.72 : 1;
      const rawRadius = node.r * point.scale * tierPlanetScale * (hover ? 1.28 : 1) * (selected ? 1.18 : 1);
      const radius = this.level === 'tier' ? Math.max(7.2, rawRadius) : rawRadius;
      if (node.energy > .67 || important) this.glow(point.x, point.y, radius * (selected || focused ? 7 : 4.5), systemColor, selected || focused ? .22 : .1);
      context.globalAlpha = important ? 1 : .38 + node.energy * .45;
      const planetGradient = context.createRadialGradient(point.x - radius * .35, point.y - radius * .4, radius * .1, point.x, point.y, radius * 1.2);
      planetGradient.addColorStop(0, '#f1f7f2');
      planetGradient.addColorStop(.23, systemColor);
      planetGradient.addColorStop(1, '#0a1711');
      context.fillStyle = planetGradient;
      context.beginPath();
      context.arc(point.x, point.y, radius, 0, TAU);
      context.fill();
      context.globalAlpha = 1;
      context.strokeStyle = statusColor;
      context.lineWidth = selected || hover || focused ? 2 : .8;
      context.beginPath();
      context.arc(point.x, point.y, radius + (important ? 6 : 3), 0, TAU);
      context.stroke();
      if (this.level === 'tier') {
        context.fillStyle = '#06100c';
        context.font = '500 7px "DM Mono"';
        context.textAlign = 'center';
        context.textBaseline = 'middle';
        context.fillText(String(node.featureIndex + 1).padStart(2, '0'), point.x, point.y + .5);
        context.textBaseline = 'alphabetic';
      }
      if (hover) {
        context.strokeStyle = '#eef2ed';
        context.lineWidth = 1;
        context.beginPath();
        context.arc(point.x, point.y, radius + 11, 0, TAU);
        context.stroke();
      }
    });
  }

  drawSemanticLabels() {
    if (this.level !== 'tier' || this.camera.zoom < 1.18) return;
    const context = this.ctx;
    const boxes = [];
    const nodes = this.nodes.filter((node) => this.visible(node)).sort((a, b) => a.screen.y - b.screen.y);
    context.font = '500 10px Manrope';
    nodes.forEach((node) => {
      const text = short(node.feature.professorLabel, 22);
      const width = context.measureText(text).width + 12;
      const height = 20;
      const point = node.screen;
      const candidates = [
        { x: point.x + 13, y: point.y - 18 },
        { x: point.x - width - 13, y: point.y - 18 },
        { x: point.x - width / 2, y: point.y + 15 },
        { x: point.x - width / 2, y: point.y - 35 }
      ];
      const placement = candidates.find((candidate) => {
        const box = { x: candidate.x, y: candidate.y, width, height };
        const inBounds = box.x >= 12 && box.x + box.width <= this.w - 12 && box.y >= 76 && box.y + box.height <= this.h - 18;
        const clear = boxes.every((other) => box.x + box.width + 5 < other.x || other.x + other.width + 5 < box.x || box.y + box.height + 4 < other.y || other.y + other.height + 4 < box.y);
        return inBounds && clear;
      });
      if (!placement) return;
      const box = { ...placement, width, height };
      boxes.push(box);
      context.strokeStyle = 'rgba(194,214,203,.28)';
      context.lineWidth = .7;
      context.beginPath();
      context.moveTo(point.x, point.y);
      context.lineTo(clamp(box.x, point.x - 4, point.x + 4), box.y + height / 2);
      context.stroke();
      context.fillStyle = 'rgba(5,15,10,.78)';
      context.fillRect(box.x, box.y, box.width, box.height);
      context.fillStyle = '#eaf1ed';
      context.textAlign = 'left';
      context.textBaseline = 'middle';
      context.fillText(text, box.x + 6, box.y + height / 2 + .5);
      context.textBaseline = 'alphabetic';
    });
  }

  updateTooltip() {
    const tooltip = this.host.querySelector('[data-pulse-tooltip]');
    if (!tooltip) return;
    if (!this.hover) { tooltip.hidden = true; return; }
    tooltip.hidden = false;
    const left = clamp(this.hover.screen.x + 18, 12, this.w - 248);
    const top = clamp(this.hover.screen.y - 22, 72, this.h - 126);
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
    if (this.hover.kind === 'system-sun') {
      const system = SYSTEM_BY_ID[this.hover.system];
      const featureCount = FEATURE_PLANETS.filter((feature) => feature.system === system.id).length;
      tooltip.innerHTML = `<small>WRITING DIVISION · SUN</small><b>${system.name}</b><span>${systemTierSummary(system).toLowerCase()} · ${featureCount} writing traits</span><em>Open solar system →</em>`;
      return;
    }
    const tier = TIER_BY_ID[this.hover.tier];
    const action = this.level === 'galaxy' ? 'Open trait group' : this.level === 'system' ? 'Open trait group' : 'Inspect current vs baseline';
    tooltip.innerHTML = this.level === 'galaxy'
      ? `<small>${SYSTEM_BY_ID[tier.system].name}</small><b>${tierLabel(tier.id)} · ${tier.name}</b><span>${tier.features.length} writing traits</span><em>${action} →</em>`
      : `<small>${tierLabel(tier.id)} · ${tier.name}</small><b>${this.hover.feature.professorLabel}</b><span>${this.hover.feature.technicalLabel}</span><em>${action} →</em>`;
  }

  loop(now) {
    this.raf = null;
    if (!this.pageVisible || !this.inViewport) return;
    if (now - this.lastRender < 27) { this.raf = requestAnimationFrame(this.loop); return; }
    const elapsed = clamp(now - this.lastTime, 0, 80);
    this.lastTime = now;
    this.lastRender = now;
    this.frame += 1;
    if (this.dimensionFlow && !this.hoverFreeze) {
      this.targetDimension += elapsed * .000018 * this.dimensionDirection;
      if (this.targetDimension >= 1) { this.targetDimension = 1; this.dimensionDirection = -1; }
      if (this.targetDimension <= 0) { this.targetDimension = 0; this.dimensionDirection = 1; }
      if (this.frame % 3 === 0) this.updateDimensionReadout();
    }
    this.parallax.x = lerp(this.parallax.x, this.parallax.targetX, .075);
    this.parallax.y = lerp(this.parallax.y, this.parallax.targetY, .075);
    this.camera.zoom = lerp(this.camera.zoom, this.camera.targetZoom, .14);
    this.camera.x = lerp(this.camera.x, this.camera.targetX, .18);
    this.camera.y = lerp(this.camera.y, this.camera.targetY, .18);
    this.camera.yaw = lerp(this.camera.yaw, this.camera.targetYaw, .13);
    this.camera.pitch = lerp(this.camera.pitch, this.camera.targetPitch, .13);
    this.dimension = lerp(this.dimension, this.targetDimension, .09);
    this.nodes.forEach((node) => {
      node.screen = this.project(node, now);
      if (this.motion && this.dimensionFlow && !this.hoverFreeze && this.frame % 4 === 0 && (node.tierLead || node.feature.code === this.selectedFeature)) {
        node.trail = node.trail || [];
        node.trail.push({ x: node.screen.x, y: node.screen.y });
        if (node.trail.length > 8) node.trail.shift();
      }
    });
    this.ctx.clearRect(0, 0, this.w, this.h);
    this.background(now);
    this.drawBaselineComparison();
    this.drawHierarchy();
    this.drawDimensionTrails();
    this.drawEdges(now);
    this.drawNodes();
    this.drawGalaxySuns(now);
    this.drawSemanticLabels();
    this.updateTooltip();
    if (this.frame % 6 === 0) this.canvas.setAttribute('aria-label', `${this.canvas.getAttribute('aria-label').split(', fourth-dimension')[0]}, fourth-dimension time ${Math.round(this.dimension * 100)} percent`);
    this.raf = requestAnimationFrame(this.loop);
  }

  destroy() {
    clearTimeout(this.focusTimer);
    if (this.raf !== null) cancelAnimationFrame(this.raf);
    this.resizeObserver?.disconnect();
    this.intersectionObserver?.disconnect();
    this.motionQuery.removeEventListener?.('change', this.motionChange);
    this.abort.abort();
  }
}

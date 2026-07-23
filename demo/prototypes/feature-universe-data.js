import {
  CODES,
  FEATURES,
  TIER_META,
  LOCALIZATION_KINDS,
  FEATURE_REGISTRY_SOURCE
} from './feature-registry.generated.js?v=production-review-20260722';

export const DIVISION_COLORS = Object.freeze({
  surface: '#d5f36f',
  discourse: '#67c995',
  rhetoric: '#a990ff'
});

const LIVE_CAPTURE_TIER = 17;
const COMPARISON_TIER = 0;
const liveCaptureCodes = CODES.filter((code) => FEATURES[code].tier === LIVE_CAPTURE_TIER);
const comparisonCodes = CODES.filter((code) => FEATURES[code].tier === COMPARISON_TIER);
const localizationCounts = Object.fromEntries(Object.keys(LOCALIZATION_KINDS).map((kind) => [
  kind,
  CODES.filter((code) => FEATURES[code].localizationKind === kind).length
]));

/**
 * Availability and provenance for the prototype feature universe.
 *
 * The 97 default-pilot features are all codes except Tier 17's six behavioral
 * signals, which require live keystroke capture. Values displayed by the
 * prototype are intentionally synthetic examples, never measured student data.
 */
export const FEATURE_UNIVERSE = Object.freeze({
  totalCount: CODES.length,
  defaultActiveCount: CODES.length - liveCaptureCodes.length,
  liveCaptureOnlyCount: liveCaptureCodes.length,
  comparisonOnlyCount: comparisonCodes.length,
  liveCaptureCodes: Object.freeze([...liveCaptureCodes]),
  comparisonCodes: Object.freeze([...comparisonCodes]),
  localizationCounts: Object.freeze(localizationCounts),
  registrySchemaVersion: FEATURE_REGISTRY_SOURCE.schemaVersion,
  dataMode: 'illustrative-prototype',
  isMeasuredStudentData: false,
  disclosure: 'Illustrative prototype values — not measured student data.'
});

export const SYSTEMS = Object.freeze([
  {
    id: 'surface',
    legacyId: 'language',
    name: 'Surface',
    short: 'SURFACE',
    subtitle: 'Form, voice & process',
    color: DIVISION_COLORS.surface,
    tiers: Object.freeze([1, 4, 5, 6, 7, 8, 11, 13, 14, 15, 17, 0]),
    description: 'Observable writing form and recurring mechanics: vocabulary, punctuation, syntax, rhythm, error patterns, and drafting behavior.'
  },
  {
    id: 'discourse',
    legacyId: 'discourse',
    name: 'Discourse',
    short: 'DISCOURSE',
    subtitle: 'Ideas, sequence & cohesion',
    color: DIVISION_COLORS.discourse,
    tiers: Object.freeze([2, 9, 10, 12]),
    description: 'How ideas connect and develop across a document: transitions, reasoning sequence, semantic focus, cohesion, and argument movement.'
  },
  {
    id: 'rhetoric',
    legacyId: 'integrity',
    name: 'Rhetoric',
    short: 'RHETORIC',
    subtitle: 'Claims, stance & sources',
    color: DIVISION_COLORS.rhetoric,
    tiers: Object.freeze([3, 16]),
    description: 'How the writer makes claims and works with sources: stance, register, authority, quotation, paraphrase, and citation.'
  }
].map(Object.freeze));

const TIER_DESCRIPTIONS = {
  0: 'Two comparison-only signals show how far the current illustrative profile moves from its baseline range.',
  1: 'Visible word and sentence habits: vocabulary range, sentence length, function words, and voice.',
  2: 'The connective tissue of an argument: transitions, paragraph movement, cohesion, and topic progression.',
  3: 'How claims sound and behave: certainty, hedging, questions, authority, register, and conclusions.',
  4: 'Fine-grained character and punctuation habits that often operate below conscious attention.',
  5: 'Recurring grammatical sequences and the depth, balance, and nesting of clauses.',
  6: 'Small personal preferences such as contractions, opening conjunctions, lists, and citation consistency.',
  7: 'Burstiness, predictability, repetition, and vocabulary-introduction patterns used only as supporting context.',
  8: 'The audible cadence of prose: stress, sentence endings, and breath-group variation.',
  9: 'The order in which reasoning moves through claims, evidence, qualification, and resolution.',
  10: 'How tightly ideas cluster and how consistently the paper remains near its semantic center.',
  11: 'The writer’s recurring ecology of stumbles, punctuation errors, and error distribution.',
  12: 'The rise, inflection, and resolution of tension across the document’s argument.',
  13: 'Deeper sentence music: clausula shape, sonority, breath regularity, and rhythmic resolution.',
  14: 'Where errors occur and which local error forms recur across the illustrative baseline papers.',
  15: 'How semantic fields, Latinate language, nominalization, and rhetorical figures structure vocabulary.',
  16: 'A source-use fingerprint built from signal verbs, quotation, paraphrase, placement, and citation rhythm.',
  17: 'Typing, pause, paste, deletion, and revision behavior. Available when keystroke evidence is captured.'
};

const systemForTier = (tier) => SYSTEMS.find((system) => system.tiers.includes(tier));

export const TIERS = Object.entries(TIER_META)
  .map(([tier, name]) => {
    const number = Number(tier);
    const system = systemForTier(number);
    const requiresLiveCapture = number === LIVE_CAPTURE_TIER;
    const requiresBaseline = number === COMPARISON_TIER;
    return {
      id: number,
      name,
      system: system.id,
      systemName: system.name,
      color: system.color,
      description: TIER_DESCRIPTIONS[number],
      status: requiresLiveCapture ? 'live capture required' : requiresBaseline ? 'baseline comparison' : 'available',
      availability: requiresLiveCapture ? 'live-capture-only' : requiresBaseline ? 'baseline-comparison' : 'imported-document',
      availableInDefaultPilot: !requiresLiveCapture,
      requiresLiveCapture,
      requiresBaseline,
      features: CODES.filter((code) => FEATURES[code].tier === number)
    };
  })
  .sort((a, b) => (a.id === 0 ? 99 : a.id) - (b.id === 0 ? 99 : b.id));

const hash = (value) => [...value].reduce((total, character) => ((total * 31) + character.charCodeAt(0)) >>> 0, 2166136261);

const SHORT_LABELS = [
  'Word variety','One‑off words','Average sentence length','Sentence length mix','Glue‑word share','Passive sentences','Maybe/should words','Common word share','Word length',
  'Linking phrases','Add‑on links','Contrast links','Cause‑and‑effect links','Time‑order links','Topic flow','Pronoun callbacks','Topic word chains','Paragraph main‑point spot','Paragraph size','Sentence starts variety','Writing “glue” usage','Between‑sentence transitions',
  'Confidence level','Softening words','Firm statements','Quote weaving style','Counter‑arguments','Number of claims','Question use','Instruction phrases','I/we usage','Expert backing','Ending pattern','Theology wording level',
  'Letter pattern variety','Punctuation range','Comma use','Semicolon & colon use','Parenthesis use','Dash use','Quote mark use',
  'Grammar pair variety','Grammar trio variety','Noun vs verb balance','Adjective use','Adverb use','Extra clause use','Clause layering',
  'Don’t vs do not','And/But/So starts','That/which preference','Citation uniformity','List style','Shortened words',
  'Sentence length variety','Word predictability','Repeat spacing','Transition formula‑ness','New word pace','Filler clumping',
  'Syllable rhythm spread','Paired rhythm spread','Ending rhythm pattern','Breath pause variety','Too‑even argument','Usual argument order','Idea spread','Usual topic closeness',
  'New error pattern','Typical error level','Punctuation mistakes','Tension spikiness','Ending rhythm sameness','Breath pacing sameness','Open vs tight vowels','Tension resolution','Rhythm flatness','Ending cadence style',
  'Error placement pattern','Missing a/an/the','Unclear “it/this”','Comma‑only joins','Topic focus','Many “and”s','Mirrored phrasing','Latinate wording','Noun‑ified actions',
  'Source verb variety','Strong vs soft verbs','Favorite authors','Long quotes share','Citation spread','Ibid use','Citation placement','Paraphrase share',
  'Typing smoothness','Burst typing share','Backspace use','Long pauses count','Paste frequency','Edit size','Letter habit drift','Glue‑word drift'
];

export const PROFESSOR_LABEL_BY_CODE = Object.freeze(Object.fromEntries(
  CODES.map((code, index) => [code, SHORT_LABELS[index] || FEATURES[code].plain])
));

const FEATURE_EXAMPLES = {
  semicolon_colon_rate: {
    current: '18.4 marks per 1,000 words · concentrated in two analytical passages',
    baseline: '8.6–12.9 marks per 1,000 words across 12 illustrative baseline papers',
    reading: 'Semicolons and colons appear more often than Morgan’s established range, with the shift concentrated rather than spread across the paper.'
  },
  clause_depth_mean: {
    current: '2.38 mean clause depth · six passages above the expected band',
    baseline: '1.42–1.91 mean clause depth across illustrative baseline work',
    reading: 'The current paper nests more dependent clauses than Morgan usually does, especially where the argument becomes abstract.'
  },
  source_integration_style: {
    current: '3 direct source handoffs without an interpretive lead-in',
    baseline: 'Morgan usually frames the source before quotation in 81% of comparable passages',
    reading: 'Several source transitions move directly into quoted material instead of using Morgan’s customary interpretive bridge.'
  },
  char_trigram_profile_divergence: {
    current: '0.18 profile distance from the illustrative character-pattern field',
    baseline: 'Expected comparison band: 0.09–0.22',
    reading: 'Character-level sequences remain inside Morgan’s cross-paper comparison range.'
  }
};

export const FEATURE_PLANETS = CODES.map((code, index) => {
  const meta = FEATURES[code];
  const tier = TIERS.find((item) => item.id === meta.tier);
  const system = SYSTEMS.find((item) => item.id === tier.system);
  const seed = hash(code);
  const center = 0.28 + (seed % 580) / 1000;
  const width = 0.055 + ((seed >>> 8) % 75) / 1000;
  const deviation = ((seed >>> 15) % 330) / 100 - 1.1;
  const requiresLiveCapture = meta.tier === LIVE_CAPTURE_TIER;
  const requiresBaseline = meta.tier === COMPARISON_TIER;
  const illustrativeSentiment = Math.abs(deviation) > 1.65 ? 'negative' : Math.abs(deviation) < 0.62 ? 'positive' : 'neutral';
  const evidenceStatusOverrides = {
    semicolon_colon_rate: 'review',
    clause_depth_mean: 'review',
    source_integration_style: 'review',
    char_trigram_profile_divergence: 'aligned'
  };
  const signalStatus = requiresLiveCapture
    ? 'not-captured'
    : evidenceStatusOverrides[code]
      || (illustrativeSentiment === 'negative' ? 'review' : illustrativeSentiment === 'positive' ? 'aligned' : 'watch');
  // `sentiment` remains as a compatibility field for the existing canvas.
  // Professor-facing UI uses signalStatus: aligned, watch, review, or not captured.
  const sentiment = signalStatus === 'review' ? 'negative' : signalStatus === 'aligned' ? 'positive' : 'neutral';
  const defaultEvidence = {
    current: `${center.toFixed(2)} current normalized signal · ${deviation >= 0 ? '+' : ''}${deviation.toFixed(1)}σ from baseline`,
    baseline: `${Math.max(0, center - width).toFixed(2)}–${Math.min(1, center + width).toFixed(2)} illustrative range · 12 baseline papers`,
    reading: `${meta.name} tracks ${meta.plain}. The current illustrative value is interpreted beside Morgan’s baseline range and connected features.`
  };
  const evidence = requiresLiveCapture
    ? {
        current: 'Not captured · requires a live writing session',
        baseline: 'Live drafting baseline required',
        reading: `${meta.name} tracks ${meta.plain}. This imported-document prototype has no keystroke evidence for this signal.`
      }
    : { ...defaultEvidence, ...FEATURE_EXAMPLES[code] };
  return {
    code,
    index,
    name: meta.name,
    technicalLabel: meta.name,
    professorLabel: PROFESSOR_LABEL_BY_CODE[code],
    plain: meta.plain,
    localizationKind: meta.localizationKind,
    localizationLabel: meta.localizationLabel,
    localizationGuidance: meta.localizationGuidance,
    supportsInlineHighlight: meta.supportsInlineHighlight,
    shortLabel: PROFESSOR_LABEL_BY_CODE[code],
    tier: meta.tier,
    tierName: tier.name,
    system: system.id,
    systemName: system.name,
    color: system.color,
    sentiment,
    signalStatus,
    status: requiresLiveCapture ? 'live capture required' : requiresBaseline ? 'baseline comparison' : signalStatus,
    availability: requiresLiveCapture ? 'live-capture-only' : requiresBaseline ? 'baseline-comparison' : 'imported-document',
    availableInDefaultPilot: !requiresLiveCapture,
    availableInImportedDocument: !requiresLiveCapture,
    requiresLiveCapture,
    requiresBaseline,
    evidenceProvenance: 'synthetic-demonstration',
    measurementStatus: requiresLiveCapture ? 'not-captured' : 'illustrative',
    isMeasuredStudentData: false,
    disclosure: FEATURE_UNIVERSE.disclosure,
    ...evidence
  };
});

export const SYSTEM_BY_ID = Object.fromEntries(SYSTEMS.map((system) => [system.id, system]));
export const TIER_BY_ID = Object.fromEntries(TIERS.map((tier) => [tier.id, tier]));
export const FEATURE_BY_CODE = Object.fromEntries(FEATURE_PLANETS.map((feature) => [feature.code, feature]));

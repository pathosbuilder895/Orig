import { FEATURE_BY_CODE, TIER_BY_ID, SYSTEM_BY_ID } from './feature-universe-data.js?v=production-review-20260722';

const FEATURES = {
  punctuation:{glyph:';',title:'Punctuation usage',copy:'Semicolons and em dashes appear at nearly twice Morgan’s established rate, concentrating in the argument’s most abstract passages.',current:'18.4',baseline:'8.6—12.9',why:'Punctuation is a low-level motor habit. A clustered change is useful context, but it is not independent evidence of authorship.',related:[['syntax','Sentence architecture','shared clause-boundary behavior'],['cadence','Cadence & pacing','sentence-ending rhythm']]},
  syntax:{glyph:'¶',title:'Sentence architecture',copy:'Clause depth rises in six passages, with subordinate structures clustering around the central theological claim.',current:'2.38',baseline:'1.42—1.91',why:'Sentence construction reflects planning habits and working-memory rhythm. Interpret it alongside genre, revision history, and source use.',related:[['punctuation','Punctuation usage','shared clause boundaries'],['cadence','Cadence & pacing','long-short sentence sequences']]},
  cadence:{glyph:'∿',title:'Cadence & pacing',copy:'Three short emphatic sentences interrupt otherwise extended prose, producing a rhythm uncommon in the baseline.',current:'0.71',baseline:'0.44—0.62',why:'Cadence captures the alternation of sentence lengths and stresses. It can change naturally with rhetorical purpose and should remain contextual.',related:[['syntax','Sentence architecture','sentence-length sequencing'],['punctuation','Punctuation usage','terminal-mark rhythm']]},
  lexical:{glyph:'Aa',title:'Lexical texture',copy:'Topic vocabulary and preferred abstractions remain consistent with Morgan’s prior theology writing.',current:'0.86',baseline:'0.78—0.91',why:'Lexical texture measures patterns of word choice, not subject knowledge. Strong continuity can contextualize changes found elsewhere.',related:[['citation','Citation behavior','source-linked vocabulary'],['transition','Discourse transitions','argument vocabulary']]},
  citation:{glyph:'“”',title:'Citation behavior',copy:'Three sources enter through impersonal claims rather than Morgan’s usual author-led attribution pattern.',current:'3',baseline:'0—1',why:'Citation transitions can reveal changes in research process or genre convention. Source verification remains a separate instructor judgment.',related:[['transition','Discourse transitions','source-entry phrasing'],['lexical','Lexical texture','source-linked vocabulary']]},
  transition:{glyph:'↝',title:'Discourse transitions',copy:'Connective phrases are slightly less varied than usual, though their placement remains consistent with the baseline.',current:'0.63',baseline:'0.66—0.82',why:'Transitions expose how an argument is assembled. Lower variety alone is weak evidence and often reflects assignment structure.',related:[['citation','Citation behavior','source-entry phrasing'],['syntax','Sentence architecture','argument segmentation']]}
};

const GUIDE_LENS_BY_TIER = {
  0:'lexical',1:'lexical',2:'transition',3:'citation',4:'punctuation',5:'syntax',6:'lexical',7:'cadence',8:'cadence',9:'transition',10:'transition',11:'punctuation',12:'transition',13:'cadence',14:'punctuation',15:'lexical',16:'citation',17:'cadence'
};
const guideLensFor = feature => GUIDE_LENS_BY_TIER[feature?.tier] || 'lexical';
const DIVISION_BY_TIER = {0:'surface',1:'surface',2:'discourse',3:'rhetoric',4:'surface',5:'surface',6:'surface',7:'surface',8:'surface',9:'discourse',10:'discourse',11:'surface',12:'discourse',13:'surface',14:'surface',15:'surface',16:'rhetoric',17:'surface'};

const DIVISION_PRESENTATION = {
  surface:{glyph:'S',title:'Surface examples',state:'DIVISION VIEW · FORM & RHYTHM',copy:'Every directly locatable Surface example is visible: word choice, punctuation, sentence structure, cadence, and other observable writing habits.',why:'Surface features describe visible form. They are useful for locating stable habits, but topic, assignment constraints, and revision can change them.'},
  discourse:{glyph:'D',title:'Discourse examples',state:'DIVISION VIEW · IDEA MOVEMENT',copy:'Every directly locatable Discourse example is visible: transitions, topic movement, cohesion, and the order in which the argument develops.',why:'Discourse features show how ideas are connected across a paper. They should be interpreted with the assignment’s structure and the writer’s revision history.'},
  rhetoric:{glyph:'R',title:'Rhetoric examples',state:'DIVISION VIEW · CLAIMS & SOURCES',copy:'Every directly locatable Rhetoric example is visible: softening words, firm claims, source handoffs, expert backing, counter-arguments, and ending strategy.',why:'Rhetoric features describe how a writer calibrates claims and works with sources. They support a conversation about process; they do not determine authorship.'}
};

const TRAIT_PALETTES = {
  surface:['#d5f36f','#6ed7c8','#f1bd69','#7ec6ed','#b6db83'],
  discourse:['#67c995','#64d7cc','#8fc4ff','#b4dc77','#5fb0d6'],
  rhetoric:['#a990ff','#e7a0c8','#efb363','#7fc7ed','#d88f9e']
};

const FAMILY_TRAIT_ROTATIONS = {
  syntax:[['mean_sentence_length','clause_depth_mean','thematic_progression_score'],['clause_depth_mean','subordination_ratio','argument_sequence_likelihood'],['mean_sentence_length','nominalization_density','thematic_progression_score']],
  cadence:[['burstiness','breath_group_variance'],['burstiness','clausulae_consistency'],['breath_group_variance','clausula_shape_preference']],
  lexical:[['type_token_ratio','theological_register_score'],['type_token_ratio','latinate_ratio'],['type_token_ratio','nominalization_density','theological_register_score']],
  transition:[['discourse_marker_density','transition_density'],['transition_density','thematic_progression_score'],['discourse_marker_density','argument_sequence_likelihood'],['transition_density','transition_predictability']],
  citation:[['source_integration_style','appeal_to_authority_density','signal_verb_entropy'],['source_integration_style','paraphrase_density'],['source_integration_style','block_quote_rate','citation_position_pref']]
};

const TRAIT_EVIDENCE = {
  type_token_ratio:{example:'“Augustine’s account of recollection” shows the paper’s recurring theological vocabulary.',baseline:'“Prayer trains perception through return” uses the same compact abstract register.',baselinePaper:'PAPER 03 · THE DISCIPLINE OF ATTENTION',explanation:'Word variety compares how broadly and repeatedly a writer uses vocabulary. Here the example remains close to the baseline register.'},
  mean_sentence_length:{example:'The opening sentence carries one claim across several linked phrases before resolving.',baseline:'“Attention is a moral practice before it becomes an intellectual technique…”',baselinePaper:'PAPER 03 · THE DISCIPLINE OF ATTENTION',explanation:'Average sentence length is a document pattern. The colored sentence is a concrete place where that pattern can be inspected.'},
  semicolon_colon_rate:{example:'“witnessed; it is the chamber…” uses a semicolon to hold two complete thoughts together.',baseline:'“what one learns to notice…; what one is able to love.”',baselinePaper:'PAPER 03 · THE DISCIPLINE OF ATTENTION',explanation:'Semicolon and colon use counts these stronger internal boundaries. The comparison asks whether their rate and placement resemble prior papers.'},
  clause_depth_mean:{example:'“This matters because… it is formed through…” nests the explanation before resolving the main claim.',baseline:'“When institutions preserve conclusions… they make obedience appear simpler…”',baselinePaper:'PAPER 02 · TRADITION AS A LIVING MEMORY',explanation:'Clause layering measures how many dependent ideas are nested inside a sentence. Deeper layering is highlighted as a sentence, not a single word.'},
  burstiness:{example:'“It is not. It accumulates. It returns.” creates a sudden short-sentence burst.',baseline:'“One waits. One receives. One answers.”',baselinePaper:'PAPER 03 · THE DISCIPLINE OF ATTENTION',explanation:'Sentence-length variety looks for changes between long and short sentences. The repeated short sequence is the clearest local example.'},
  discourse_marker_density:{example:'“Indeed,” explicitly signals that the next sentence develops the previous claim.',baseline:'“In this sense,” redirects the baseline argument in the same way.',baselinePaper:'PAPER 03 · THE DISCIPLINE OF ATTENTION',explanation:'Linking phrases are words such as “indeed,” “therefore,” and “consequently” that tell a reader how one idea relates to the next.'},
  transition_density:{example:'“Consequently,” marks the movement from diagnosis to implication.',baseline:'“Therefore,” moves the baseline paper from source discussion to application.',baselinePaper:'PAPER 03 · THE DISCIPLINE OF ATTENTION',explanation:'Between-sentence transitions count explicit handoffs between ideas. Selecting this feature isolates those handoffs.'},
  thematic_progression_score:{example:'“Grace interrupts this conversion… it restores contingency to the future.” develops the paper’s memory-to-grace theme.',baseline:'“Prayer trains perception through return… repetition can disclose difference.”',baselinePaper:'PAPER 03 · THE DISCIPLINE OF ATTENTION',explanation:'Topic flow tracks how a paper carries and transforms its central ideas across sentences rather than repeating isolated keywords.'},
  hedging_density:{currentValue:'0.38',currentUnit:'PER 100 WORDS',baselineValue:'0.49–1.18',statusLabel:'ALIGNED',example:'“as though,” “may,” “should,” and “can” soften or qualify the force of a claim.',baseline:'“A reader… may reproduce the same posture toward neighbors…”',baselinePaper:'PAPER 03 · THE DISCIPLINE OF ATTENTION',explanation:'Softening words calibrate certainty. Words such as “may,” “might,” “should,” “can,” and “as though” leave room for qualification rather than presenting a claim as absolute.'},
  source_integration_style:{currentValue:'3',currentUnit:'VISIBLE SOURCE MOMENTS',baselineValue:'AUTHOR-LED IN 3 / 3',statusLabel:'REVIEW',example:'“As Rowan Williams writes…” names the source before weaving the quotation into the sentence.',baseline:'“Simone Weil calls attention the rarest form of generosity.”',baselinePaper:'PAPER 03 · THE DISCIPLINE OF ATTENTION',explanation:'Quote weaving style describes how a writer introduces, quotes, paraphrases, and then interprets a source. The highlighted handoff is compared with prior source handoffs.'},
  appeal_to_authority_density:{example:'“As Rowan Williams writes…” asks a named scholar to support the developing claim.',baseline:'“Jaroslav Pelikan distinguishes the living faith of the dead…”',baselinePaper:'PAPER 02 · TRADITION AS A LIVING MEMORY',explanation:'Expert backing tracks how often a writer relies on named authorities and where that support enters the argument.'},
  conclusion_strategy_score:{example:'“The question is not whether…; the question is what kind of world…” closes by reframing the paper’s central question.',baseline:'“The disciplined gaze is neither passive nor possessive; it is a readiness to revise…”',baselinePaper:'PAPER 03 · THE DISCIPLINE OF ATTENTION',explanation:'Ending pattern describes how a writer resolves a paper—by summarizing, reframing, extending, or qualifying the argument.'}
};

const CURRENT_SEMANTIC_TOKENS = [
  ['Indeed',['discourse_marker_density','transition_density'],'discourse-link-01'],
  ['Consequently',['discourse_marker_density','transition_density'],'discourse-link-02'],
  ['For this reason',['discourse_marker_density','transition_density'],'discourse-link-03'],
  ['writes',['signal_verb_entropy'],'rhetoric-signal-verb-01'],
  ['not merely',['hedging_density'],'rhetoric-hedge-01'],
  ['as though',['hedging_density'],'rhetoric-hedge-02'],
  ['may be',['hedging_density'],'rhetoric-hedge-03'],
  ['should be',['hedging_density','modal_verb_ratio'],'rhetoric-hedge-04'],
  ['can',['hedging_density','modal_verb_ratio'],'rhetoric-hedge-05'],
  ['but such a claim remains incomplete',['counter_argument_ratio'],'rhetoric-counter-01'],
  ['The question is not whether memory persists',['conclusion_strategy_score','claim_density'],'rhetoric-ending-01'],
  ['the question is what kind of world our remembering permits us to see',['conclusion_strategy_score','assertion_density'],'rhetoric-ending-02']
];

const BASELINE_SEMANTIC_TOKENS = [
  ['Accordingly',['discourse_marker_density','transition_density'],'baseline-link-01'],
  ['Yet',['discourse_marker_density','transition_density'],'baseline-link-02'],
  ['Therefore',['discourse_marker_density','transition_density'],'baseline-link-03'],
  ['For this reason',['discourse_marker_density','transition_density'],'baseline-link-04'],
  ['can be secured',['hedging_density','modal_verb_ratio'],'baseline-hedge-01'],
  ['should not make',['hedging_density','modal_verb_ratio'],'baseline-hedge-02'],
  ['can sustain',['hedging_density','modal_verb_ratio'],'baseline-hedge-03'],
  ['can expose',['hedging_density','modal_verb_ratio'],'baseline-hedge-04'],
  ['may reproduce',['hedging_density','modal_verb_ratio'],'baseline-hedge-05']
];

const TEXT_LOCALIZATION_KINDS = new Set(['token','character','sentence','paragraph']);
const DIRECT_LOCALIZATION_KINDS = new Set(['token','character']);
const localizationKindFor = feature => feature?.localizationKind || (feature?.requiresLiveCapture ? 'behavioral' : 'document');
const canLocateInText = feature => feature?.supportsInlineHighlight ?? TEXT_LOCALIZATION_KINDS.has(localizationKindFor(feature));
const localizationPresentationFor = feature => {
  const kind=localizationKindFor(feature);let presentation;
  if(kind==='token')presentation={label:'DIRECT WORD OR PHRASE',noun:'direct text example',explanation:'This feature can be attached to specific words or phrases.'};
  else if(kind==='character')presentation={label:'DIRECT CHARACTER MARK',noun:'direct character example',explanation:'This feature can be attached to a specific punctuation or character mark.'};
  else if(kind==='sentence')presentation={label:'REPRESENTATIVE SENTENCE',noun:'representative sentence',explanation:'The sentence is a representative place to inspect a pattern measured across the document.'};
  else if(kind==='paragraph')presentation={label:'REPRESENTATIVE PASSAGE',noun:'representative passage',explanation:'The passage is a representative place to inspect a pattern measured across several sentences.'};
  else if(kind==='behavioral')presentation={label:'DRAFTING-SESSION SIGNAL',noun:'session signal',explanation:'This feature comes from writing-process events and cannot be located in imported prose.'};
  else presentation={label:'FULL-DOCUMENT MEASURE',noun:'document-level measure',explanation:'This feature is calculated across the full document and should not be presented as belonging to one phrase.'};
  return {...presentation,label:(feature?.localizationLabel||presentation.label).toUpperCase(),explanation:feature?.localizationGuidance||presentation.explanation};
};

const LABELS = Object.fromEntries(Object.entries(FEATURES).map(([id,f])=>[id,f.title]));
const DEMO_STATUS = 'Illustrative analysis · no records saved';
const hexRgb = hex => {const value=parseInt(hex.slice(1),16);return `${(value>>16)&255},${(value>>8)&255},${value&255}`};
const BASELINES = [
  {
    paper:'01',code:'ML / ST-402 / 01',page:'2 OF 12',course:'SYSTEMATIC THEOLOGY · ESSAY I',title:'Desire and the Common Good',meta:'Morgan Lee · submitted 12 February 2026',date:'ILLUSTRATIVE · 12 FEB 2026',
    body:`<p><span data-baseline-feature="syntax cadence">Desire becomes morally intelligible when it is directed beyond possession and toward participation in a common life.</span> <span data-baseline-feature="lexical">Augustine describes the restless heart</span> not as an appetite that must be extinguished<mark data-baseline-feature="punctuation">,</mark> but as a movement that must learn its proper end<mark data-baseline-feature="punctuation">.</mark> <span data-baseline-feature="transition">Accordingly<mark data-baseline-feature="punctuation">,</mark></span> the question is less whether we desire than whether desire teaches us to recognize another person as a neighbor<mark data-baseline-feature="punctuation">.</mark></p>
      <p><span data-baseline-feature="syntax">A private good can be secured without altering the self<mark data-baseline-feature="punctuation">;</mark> a common good<mark data-baseline-feature="punctuation">,</mark> by contrast<mark data-baseline-feature="punctuation">,</mark> asks each participant to receive flourishing through relationship.</span> <span data-baseline-feature="citation">As Aquinas argues<mark data-baseline-feature="punctuation">,</mark> friendship names a willing of the good for the other</span><mark data-baseline-feature="punctuation">.</mark> <span data-baseline-feature="cadence">This willing takes practice<mark data-baseline-feature="punctuation">.</mark> It takes patience<mark data-baseline-feature="punctuation">.</mark></span></p>
      <blockquote data-baseline-feature="citation lexical"><span class="quote-mark" aria-hidden="true">“</span><p>The good is not diminished when it is shared<mark data-baseline-feature="punctuation">,</mark> because its deepest form is communion<mark data-baseline-feature="punctuation">.</mark></p><cite><span>Seminar notes on charity</span><small>Week three</small></cite></blockquote>
      <p><span data-baseline-feature="transition">Yet<mark data-baseline-feature="punctuation">,</mark></span> this account should not make agreement a condition of belonging<mark data-baseline-feature="punctuation">.</mark> <span data-baseline-feature="syntax cadence">The neighbor remains a claimant upon attention even when recognition is slow<mark data-baseline-feature="punctuation">,</mark> interests diverge<mark data-baseline-feature="punctuation">,</mark> or reconciliation has not yet become possible.</span> The common good begins precisely where convenience ends<mark data-baseline-feature="punctuation">.</mark></p>
      <p><span data-baseline-feature="transition">For this reason<mark data-baseline-feature="punctuation">,</mark></span> Christian ethics must ask how institutions school desire through repeated forms of welcome and refusal<mark data-baseline-feature="punctuation">.</mark> <span data-baseline-feature="lexical">A community becomes truthful when its ordinary practices make room for another’s flourishing</span><mark data-baseline-feature="punctuation">;</mark> its claims about love are credible only when that room can be seen<mark data-baseline-feature="punctuation">.</mark></p>`
  },
  {
    paper:'02',code:'ML / ST-402 / 02',page:'4 OF 12',course:'CHURCH HISTORY · ESSAY II',title:'Tradition as a Living Memory',meta:'Morgan Lee · submitted 06 March 2026',date:'ILLUSTRATIVE · 06 MAR 2026',
    body:`<p><span data-baseline-feature="syntax cadence">Tradition is neither a sealed archive nor the unbroken repetition of a single voice<mark data-baseline-feature="punctuation">;</mark> it is a disciplined argument about what must be remembered.</span> <span data-baseline-feature="lexical">The church receives a history already interpreted by worship</span><mark data-baseline-feature="punctuation">,</mark> conflict<mark data-baseline-feature="punctuation">,</mark> and repair<mark data-baseline-feature="punctuation">.</mark> <span data-baseline-feature="transition">Thus<mark data-baseline-feature="punctuation">,</mark></span> inheritance always carries the responsibility of judgment<mark data-baseline-feature="punctuation">.</mark></p>
      <p><span data-baseline-feature="citation">Jaroslav Pelikan distinguishes the living faith of the dead from the dead faith of the living</span><mark data-baseline-feature="punctuation">.</mark> The distinction matters because memory can sustain both courage and evasion<mark data-baseline-feature="punctuation">.</mark> <span data-baseline-feature="syntax">When institutions preserve conclusions while concealing the disputes that produced them<mark data-baseline-feature="punctuation">,</mark> they make obedience appear simpler than it was.</span></p>
      <blockquote data-baseline-feature="citation lexical"><span class="quote-mark" aria-hidden="true">“</span><p>To remember faithfully is to keep the question open long enough for truth to address the present<mark data-baseline-feature="punctuation">.</mark></p><cite><span>Lecture notes on reception</span><small>Week five</small></cite></blockquote>
      <p><span data-baseline-feature="transition">At the same time<mark data-baseline-feature="punctuation">,</mark></span> novelty is not evidence of wisdom<mark data-baseline-feature="punctuation">.</mark> <span data-baseline-feature="cadence">The past resists us<mark data-baseline-feature="punctuation">.</mark> It also steadies us<mark data-baseline-feature="punctuation">.</mark></span> <span data-baseline-feature="syntax">Its witnesses can expose the narrowness of the present precisely because they do not share all of its assumptions.</span></p>
      <p><span data-baseline-feature="transition">Consequently<mark data-baseline-feature="punctuation">,</mark></span> a living tradition requires practices of patient retrieval<mark data-baseline-feature="punctuation">,</mark> public disagreement<mark data-baseline-feature="punctuation">,</mark> and accountable revision<mark data-baseline-feature="punctuation">.</mark> <span data-baseline-feature="lexical">Memory serves the church when it enlarges the field of attention</span><mark data-baseline-feature="punctuation">;</mark> it fails when it is used only to protect the present from examination<mark data-baseline-feature="punctuation">.</mark></p>`
  },
  {
    paper:'03',code:'ML / ST-402 / 03',page:'5 OF 12',course:'SYSTEMATIC THEOLOGY · ESSAY III',title:'The Discipline of Attention',meta:'Morgan Lee · submitted 02 April 2026',date:'ILLUSTRATIVE · 02 APR 2026',
    body:`<p><span data-baseline-feature="syntax cadence">Attention is a moral practice before it becomes an intellectual technique<mark data-baseline-feature="punctuation">;</mark> what one learns to notice gradually determines what one is able to love.</span> <span data-baseline-feature="lexical">Prayer trains perception through return</span><mark data-baseline-feature="punctuation">,</mark> not through intensity alone<mark data-baseline-feature="punctuation">.</mark> <span data-baseline-feature="transition">In this sense<mark data-baseline-feature="punctuation">,</mark></span> repetition can disclose difference rather than conceal it<mark data-baseline-feature="punctuation">.</mark></p>
      <p><span data-baseline-feature="citation">Simone Weil calls attention the rarest form of generosity</span><mark data-baseline-feature="punctuation">.</mark> Her claim does not romanticize concentration<mark data-baseline-feature="punctuation">;</mark> it identifies the restraint required to let another reality interrupt one’s preferred account<mark data-baseline-feature="punctuation">.</mark> <span data-baseline-feature="cadence">One waits<mark data-baseline-feature="punctuation">.</mark> One receives<mark data-baseline-feature="punctuation">.</mark> One answers<mark data-baseline-feature="punctuation">.</mark></span></p>
      <blockquote data-baseline-feature="citation lexical"><span class="quote-mark" aria-hidden="true">“</span><p>Attention begins when the world is permitted to be more particular than our explanation of it<mark data-baseline-feature="punctuation">.</mark></p><cite><span>Field notes on Weil</span><small>Seminar week six</small></cite></blockquote>
      <p><span data-baseline-feature="transition">Therefore<mark data-baseline-feature="punctuation">,</mark></span> the habits of study cannot be separated from the habits of moral regard<mark data-baseline-feature="punctuation">.</mark> <span data-baseline-feature="syntax">A reader who approaches every text as material to be mastered may reproduce the same posture toward neighbors<mark data-baseline-feature="punctuation">,</mark> traditions<mark data-baseline-feature="punctuation">,</mark> and communities.</span></p>
      <p><span data-baseline-feature="transition">For this reason<mark data-baseline-feature="punctuation">,</mark></span> theological education should cultivate forms of noticing that remain answerable to what they encounter<mark data-baseline-feature="punctuation">.</mark> <span data-baseline-feature="lexical">The disciplined gaze is neither passive nor possessive</span><mark data-baseline-feature="punctuation">;</mark> it is a readiness to revise one’s judgment when reality asks more of it<mark data-baseline-feature="punctuation">.</mark></p>`
  }
];

const EDITOR_STATE = {active:'punctuation',theme:'navy',compare:false,baselineIndex:2,differenceIndex:0,scrollTop:0,scrollLeft:0};

export class DocumentIntelligence {
  constructor(root){
    this.root=root;this.active=EDITOR_STATE.active;this.activeDivision='surface';this.lensMode='division';this.hover=null;this.previewMark=null;this.previewPinned=null;this.evidenceScope='division';this.reviewOnly=true;this.correlationZoom=0;this.compare=false;this.baselineIndex=EDITOR_STATE.baselineIndex;this.differenceIndex=EDITOR_STATE.differenceIndex;this.comparisonPairs=[];this.catalogDivision='surface';this.catalogQuery='';this.catalogFeature=null;this.abort=new AbortController();this.frame=0;this.start=performance.now();this.pointerFrame=0;this.pendingPointer=null;this.canvasVisible=true;
    this.motionPreference=matchMedia('(prefers-reduced-motion: reduce)');this.transparencyPreference=matchMedia('(prefers-reduced-transparency: reduce)');
    this.canvas=root.querySelector('[data-correlation-canvas]');this.ctx=this.canvas?.getContext('2d');
    this.root.dataset.editorTheme=EDITOR_STATE.theme;
    this.annotateCurrentEvidence();this.configureReviewMode();this.renderBaseline();this.bind();this.filterCatalog();this.selectCatalogDivision('surface',{selectFirst:false});this.resize();this.setupAnimationLifecycle();
    this.root.querySelectorAll('[data-theme]').forEach(button=>button.classList.toggle('active',button.dataset.theme===EDITOR_STATE.theme));
    if(EDITOR_STATE.compare)requestAnimationFrame(()=>this.toggleCompare(true,true));
    this.observer=new ResizeObserver(()=>this.resize());if(this.canvas)this.observer.observe(this.canvas);
  }
  annotateFamilyTraits(container,{baseline=false}={}){
    if(!container)return;
    const familyKey=baseline?'baselineFeature':'feature',traitsKey=baseline?'baselineTraits':'traits',counters={},sentenceAssignments=[];
    container.querySelectorAll(`[data-${baseline?'baseline-feature':'feature'}]`).forEach((element,index)=>{
      const existing=(element.dataset[traitsKey]||'').split(' ').filter(Boolean),codes=[...existing];
      for(const family of (element.dataset[familyKey]||'').split(' ').filter(Boolean)){
        if(family==='punctuation'){
          const symbol=element.textContent.trim();
          const punctuation=symbol===';'||symbol===':'?['semicolon_colon_rate','punctuation_diversity']:symbol===','?['comma_rate','punctuation_diversity']:symbol==='—'||symbol==='–'?['dash_rate','punctuation_diversity']:symbol.includes('“')||symbol.includes('”')?['quote_rate','punctuation_diversity']:['punctuation_diversity'];
          codes.push(...punctuation);
          continue;
        }
        const rotations=FAMILY_TRAIT_ROTATIONS[family];if(!rotations?.length)continue;
        const position=counters[family]||0;codes.push(...rotations[position%rotations.length]);counters[family]=position+1;
      }
      const unique=[...new Set(codes)].filter(code=>{const feature=FEATURE_BY_CODE[code],kind=localizationKindFor(feature);return canLocateInText(feature)&&(kind==='sentence'||kind==='paragraph'||(kind==='character'&&element.tagName==='MARK'))}),paragraphCodes=unique.filter(code=>localizationKindFor(FEATURE_BY_CODE[code])==='paragraph'),sentenceCodes=unique.filter(code=>localizationKindFor(FEATURE_BY_CODE[code])==='sentence'),characterCodes=unique.filter(code=>localizationKindFor(FEATURE_BY_CODE[code])==='character'),occurrence=`${baseline?'baseline':'current'}-${String(index+1).padStart(2,'0')}`;
      this.mergeTraitCodes(element,characterCodes,{baseline,occurrence});const block=element.closest('p,blockquote');if(block&&paragraphCodes.length)this.mergeTraitCodes(block,paragraphCodes,{baseline,occurrence:`${occurrence}-paragraph`});if(sentenceCodes.length)sentenceAssignments.push({element,codes:sentenceCodes,occurrence});
    });
    sentenceAssignments.forEach(({element,codes,occurrence})=>{if(!element.isConnected)return;const host=element.matches('blockquote')?(element.querySelector('p')||element):element,walker=document.createTreeWalker(host,NodeFilter.SHOW_TEXT,{acceptNode:node=>node.nodeValue.trim()?NodeFilter.FILTER_ACCEPT:NodeFilter.FILTER_SKIP}),node=walker.nextNode(),phrase=host.textContent.trim();if(node&&phrase)this.wrapSentenceEvidence(node,phrase,codes,occurrence,{baseline})});
  }
  mergeTraitCodes(element,codes,{baseline=false,occurrence}={}){
    if(!element||!codes.length)return element;const traitsKey=baseline?'baselineTraits':'traits',occurrenceKey=baseline?'baselineOccurrence':'traitOccurrence',merged=[...new Set([...(element.dataset[traitsKey]||'').split(' ').filter(Boolean),...codes])];element.dataset[traitsKey]=merged.join(' ');if(!element.dataset[occurrenceKey])element.dataset[occurrenceKey]=occurrence||`${baseline?'baseline':'current'}-evidence`;return element;
  }
  wrapSentenceEvidence(node,phrase,codes,id,{baseline=false}={}){
    if(!node||!codes.length)return null;const existing=node.parentElement?.closest('[data-localization-sentence]');if(existing)return this.mergeTraitCodes(existing,codes,{baseline,occurrence:`${id}-sentence`});const block=node.parentElement?.closest('p');if(!block)return this.mergeTraitCodes(node.parentElement,codes,{baseline,occurrence:`${id}-sentence`});
    const text=block.textContent,phraseIndex=text.toLowerCase().indexOf(phrase.toLowerCase());if(phraseIndex<0)return this.mergeTraitCodes(block,codes,{baseline,occurrence:`${id}-sentence`});let start=phraseIndex,end=phraseIndex+phrase.length;while(start>0&&!/[.!?]/.test(text[start-1]))start-=1;while(start<text.length&&/\s/.test(text[start]))start+=1;while(end<text.length&&!/[.!?]/.test(text[end]))end+=1;if(end<text.length)end+=1;while(end<text.length&&/[”"’]/.test(text[end]))end+=1;
    const nodes=[],walker=document.createTreeWalker(block,NodeFilter.SHOW_TEXT);while(walker.nextNode())nodes.push(walker.currentNode);const boundary=position=>{let offset=0;for(const textNode of nodes){const next=offset+textNode.nodeValue.length;if(position<=next)return {node:textNode,offset:Math.max(0,position-offset)};offset=next}const last=nodes.at(-1);return last?{node:last,offset:last.nodeValue.length}:null},from=boundary(start),to=boundary(end);if(!from||!to)return this.mergeTraitCodes(block,codes,{baseline,occurrence:`${id}-sentence`});
    const range=document.createRange();range.setStart(from.node,from.offset);range.setEnd(to.node,to.offset);const wrapper=document.createElement('span');wrapper.dataset.localizationSentence='';this.mergeTraitCodes(wrapper,codes,{baseline,occurrence:`${id}-sentence`});wrapper.append(range.extractContents());range.insertNode(wrapper);return wrapper;
  }
  wrapEvidencePhrase(container,phrase,codes,id,{baseline=false}={}){
    if(!container||!phrase)return null;
    const localCodes=codes.filter(code=>canLocateInText(FEATURE_BY_CODE[code]));if(!localCodes.length)return null;
    const walker=document.createTreeWalker(container,NodeFilter.SHOW_TEXT,{acceptNode:node=>node.parentElement?.closest('[data-trait-token]')?NodeFilter.FILTER_REJECT:node.nodeValue.toLowerCase().includes(phrase.toLowerCase())?NodeFilter.FILTER_ACCEPT:NodeFilter.FILTER_SKIP});
    const node=walker.nextNode();if(!node)return null;const directCodes=localCodes.filter(code=>DIRECT_LOCALIZATION_KINDS.has(localizationKindFor(FEATURE_BY_CODE[code]))),sentenceCodes=localCodes.filter(code=>localizationKindFor(FEATURE_BY_CODE[code])==='sentence'),paragraphCodes=localCodes.filter(code=>localizationKindFor(FEATURE_BY_CODE[code])==='paragraph'),block=node.parentElement?.closest('p,blockquote');let scoped=null;if(paragraphCodes.length&&block)scoped=this.mergeTraitCodes(block,paragraphCodes,{baseline,occurrence:`${id}-paragraph`});if(sentenceCodes.length)scoped=this.wrapSentenceEvidence(node,phrase,sentenceCodes,id,{baseline})||scoped;if(!directCodes.length)return scoped;
    const start=node.nodeValue.toLowerCase().indexOf(phrase.toLowerCase()),before=node.nodeValue.slice(0,start),match=node.nodeValue.slice(start,start+phrase.length),after=node.nodeValue.slice(start+phrase.length),mark=document.createElement('mark');
    mark.textContent=match;mark.dataset.traitToken='true';this.mergeTraitCodes(mark,directCodes,{baseline,occurrence:id});mark.dataset[baseline?'baselineFeature':'feature']='citation';
    const fragment=document.createDocumentFragment();if(before)fragment.append(document.createTextNode(before));fragment.append(mark);if(after)fragment.append(document.createTextNode(after));node.replaceWith(fragment);return mark;
  }
  annotateCurrentEvidence(){
    const body=this.root.querySelector('[data-paper-body]');if(!body||body.dataset.traitsReady==='true')return;
    this.annotateFamilyTraits(body);CURRENT_SEMANTIC_TOKENS.forEach(([phrase,codes,id])=>this.wrapEvidencePhrase(body,phrase,codes,id));this.cleanupEmptyEvidence(body);body.dataset.traitsReady='true';
    body.querySelectorAll('[data-traits]').forEach(mark=>mark.classList.add('analysis-mark'));
  }
  annotateBaselineEvidence(){
    const body=this.root.querySelector('[data-baseline-body]');if(!body)return;
    this.annotateFamilyTraits(body,{baseline:true});BASELINE_SEMANTIC_TOKENS.forEach(([phrase,codes,id])=>this.wrapEvidencePhrase(body,phrase,codes,id,{baseline:true}));this.cleanupEmptyEvidence(body,{baseline:true});
  }
  cleanupEmptyEvidence(container,{baseline=false}={}){
    const attribute=baseline?'data-baseline-traits':'data-traits';container.querySelectorAll(`[${attribute}]`).forEach(element=>{if(element.textContent.trim())return;if(element.matches('mark,span'))element.remove();else element.removeAttribute(attribute)});container.querySelectorAll('mark,span').forEach(element=>{if(!element.textContent.trim()&&!element.children.length)element.remove()});
  }
  traitCodes(element,{baseline=false}={}){return (element?.dataset?.[baseline?'baselineTraits':'traits']||'').split(' ').filter(code=>FEATURE_BY_CODE[code])}
  traitMatches(element,{baseline=false}={}){
    const codes=this.traitCodes(element,{baseline});
    if(this.lensMode==='all')return codes.length>0;
    if(this.lensMode==='exact')return codes.includes(this.catalogFeature);
    if(this.lensMode==='division')return codes.some(code=>FEATURE_BY_CODE[code]?.system===this.activeDivision);
    const familyKey=baseline?'baselineFeature':'feature',legacyMatch=(element.dataset[familyKey]||'').split(' ').includes(this.active),traitMatch=codes.some(code=>guideLensFor(FEATURE_BY_CODE[code])===this.active);return legacyMatch||traitMatch;
  }
  activeTraitFor(element,{baseline=false}={}){
    const codes=this.traitCodes(element,{baseline});if(this.lensMode==='exact'&&codes.includes(this.catalogFeature))return this.catalogFeature;
    if(this.lensMode==='division')return codes.find(code=>FEATURE_BY_CODE[code]?.system===this.activeDivision)||codes[0];if(this.lensMode==='family')return codes.find(code=>guideLensFor(FEATURE_BY_CODE[code])===this.active)||codes[0];return codes[0];
  }
  applyTraitTone(element,code){
    const feature=FEATURE_BY_CODE[code];if(!feature)return;const palette=TRAIT_PALETTES[feature.system]||TRAIT_PALETTES.surface,color=palette[feature.index%palette.length],second=palette[(feature.index+2)%palette.length];
    element.style.setProperty('--mark-rgb',hexRgb(color));element.style.setProperty('--mark-rgb-2',hexRgb(second));element.style.setProperty('--trait-color',color);element.dataset.activeTrait=code;
  }
  refreshTraitHighlights(){
    const current=[...this.root.querySelectorAll('[data-paper-body] [data-traits]')];
    current.forEach(mark=>{const active=this.traitMatches(mark);mark.classList.toggle('feature-active',active);mark.classList.remove('evidence-selected');if(active)this.applyTraitTone(mark,this.activeTraitFor(mark))});
    this.syncEvidenceRoving(current,{baseline:false});
    this.syncBaselineHighlights();this.buildComparisonPairs();this.updateDifferenceRail(current.filter(mark=>mark.classList.contains('feature-active')));
    return {current:current.filter(mark=>mark.classList.contains('feature-active')),baseline:[...this.root.querySelectorAll('[data-baseline-traits].baseline-feature-active')]};
  }
  evidenceControlCandidates(marks,{baseline=false}={}){
    const activeClass=baseline?'baseline-feature-active':'feature-active';
    return marks.filter(mark=>mark.classList.contains(activeClass)&&!mark.querySelector(`.${activeClass}`));
  }
  syncEvidenceRoving(marks,{baseline=false}={}){
    const activeClass=baseline?'baseline-feature-active':'feature-active',occurrenceKey=baseline?'baselineOccurrence':'traitOccurrence',candidates=this.evidenceControlCandidates(marks,{baseline}),focused=candidates.includes(document.activeElement)?document.activeElement:null,remembered=this[baseline?'baselineRovingOccurrence':'currentRovingOccurrence'],target=focused||candidates.find(mark=>mark.dataset[occurrenceKey]===remembered)||candidates[0]||null;
    marks.forEach(mark=>{
      const interactive=candidates.includes(mark),codes=this.traitCodes(mark,{baseline}),names=codes.map(code=>FEATURE_BY_CODE[code]?.professorLabel).filter(Boolean).join(', ');
      mark.tabIndex=interactive&&mark===target?0:-1;
      if(interactive){mark.setAttribute('role','button');mark.setAttribute('aria-label',`Inspect ${baseline?'baseline ':'writing '}example: ${names}`)}else{mark.removeAttribute('role');mark.removeAttribute('aria-label')}
      if(!mark.classList.contains(activeClass))mark.removeAttribute('aria-current');
    });
    if(target)this[baseline?'baselineRovingOccurrence':'currentRovingOccurrence']=target.dataset[occurrenceKey];
  }
  onEvidenceKeydown(event,baseline=false){
    const activeClass=baseline?'baseline-feature-active':'feature-active',selector=baseline?'[data-baseline-traits]':'[data-traits]',mark=event.target.closest?.(`${selector}.${activeClass}`);if(!mark)return;
    if(event.key==='Enter'||event.key===' '){event.preventDefault();this.inspectTraitOccurrence(mark,baseline);return}
    const direction={ArrowRight:1,ArrowDown:1,ArrowLeft:-1,ArrowUp:-1}[event.key],home=event.key==='Home',end=event.key==='End';if(!direction&&!home&&!end)return;
    const container=this.root.querySelector(baseline?'[data-baseline-body]':'[data-paper-body]'),marks=this.evidenceControlCandidates([...container.querySelectorAll(selector)],{baseline});if(!marks.length)return;
    event.preventDefault();const current=Math.max(0,marks.indexOf(mark)),next=home?0:end?marks.length-1:(current+direction+marks.length)%marks.length,target=marks[next],occurrenceKey=baseline?'baselineOccurrence':'traitOccurrence';
    marks.forEach(item=>item.tabIndex=item===target?0:-1);this[baseline?'baselineRovingOccurrence':'currentRovingOccurrence']=target.dataset[occurrenceKey];target.focus({preventScroll:true});target.scrollIntoView({block:'nearest',inline:'nearest',behavior:this.motionPreference.matches?'auto':'smooth'});
    const code=this.activeTraitFor(target,{baseline});if(code){this.previewMark=target;this.showPassagePreview(target,code,{automatic:true})}
  }
  announce(message){
    const status=this.root.querySelector('[data-evidence-status]');if(!status||status.textContent===message)return;status.textContent=message;
  }
  representedCodes(division){
    const set=new Set();this.root.querySelectorAll('[data-paper-body] [data-traits]').forEach(mark=>this.traitCodes(mark).forEach(code=>{if(FEATURE_BY_CODE[code]?.system===division)set.add(code)}));return set;
  }
  bind(){
    const opts={signal:this.abort.signal};
    this.root.addEventListener('pointermove',event=>this.trackGlassLight(event),opts);
    this.root.addEventListener('pointerleave',()=>{this.pendingPointer=null;cancelAnimationFrame(this.pointerFrame);this.pointerFrame=0;this.root.style.setProperty('--glass-x','50%');this.root.style.setProperty('--glass-y','8%');this.root.style.setProperty('--scene-x','0px');this.root.style.setProperty('--scene-y','0px')},opts);
    this.root.querySelector('[data-feature-all]')?.addEventListener('click',()=>this.showAllFeatureOverlays(),opts);
    this.root.querySelector('[data-catalog-search]')?.addEventListener('input',event=>{this.catalogQuery=event.target.value;this.filterCatalog()},opts);
    this.root.querySelectorAll('[data-catalog-division-select]').forEach(button=>button.addEventListener('click',()=>this.selectCatalogDivision(button.dataset.catalogDivisionSelect),opts));
    this.root.querySelector('[data-feature-catalog]')?.addEventListener('click',event=>{const clear=event.target.closest('[data-catalog-clear]');if(clear){this.catalogQuery='';const search=this.root.querySelector('[data-catalog-search]');if(search){search.value='';search.focus()}this.filterCatalog();return}const button=event.target.closest('[data-catalog-feature]');if(button)this.selectCatalogFeature(button.dataset.catalogFeature)},opts);
    this.root.querySelectorAll('[data-correlate]').forEach(button=>button.addEventListener('click',()=>{const code=button.dataset.catalogRelated;if(code)this.selectCatalogFeature(code);else this.setFeature(button.dataset.correlate)},opts));
    this.root.querySelectorAll('[data-theme]').forEach(button=>button.addEventListener('click',()=>this.setTheme(button.dataset.theme,button),opts));
    this.root.querySelector('[data-document-compare]')?.addEventListener('click',()=>this.toggleCompare(),opts);
    this.root.querySelectorAll('[data-baseline-prev]').forEach(button=>button.addEventListener('click',()=>this.changeBaseline(-1),opts));
    this.root.querySelectorAll('[data-baseline-next]').forEach(button=>button.addEventListener('click',()=>this.changeBaseline(1),opts));
    this.root.querySelector('[data-difference-prev]')?.addEventListener('click',()=>this.stepDifference(-1),opts);
    this.root.querySelector('[data-difference-next]')?.addEventListener('click',()=>this.stepDifference(1),opts);
    this.root.querySelector('[data-passage-prev]')?.addEventListener('click',()=>this.stepPassagePreview(-1),opts);
    this.root.querySelector('[data-passage-next]')?.addEventListener('click',()=>this.stepPassagePreview(1),opts);
    this.root.querySelectorAll('[data-pan-paper]').forEach(button=>button.addEventListener('click',()=>this.panToPaper(button.dataset.panPaper),opts));
    this.root.querySelectorAll('[data-editor-command]').forEach(button=>button.addEventListener('click',()=>this.runEditorCommand(button.dataset.editorCommand,button.dataset.editorValue),opts));
    const baselineBody=this.root.querySelector('[data-baseline-body]');
    baselineBody?.addEventListener('click',event=>{const mark=event.target.closest('[data-baseline-traits].baseline-feature-active');if(mark)this.inspectTraitOccurrence(mark,true)},opts);
    baselineBody?.addEventListener('keydown',event=>this.onEvidenceKeydown(event,true),opts);
    baselineBody?.addEventListener('pointerover',event=>this.onPassagePointerOver(event),opts);
    baselineBody?.addEventListener('pointerout',event=>this.onPassagePointerOut(event),opts);
    this.root.querySelectorAll('[data-paper-body] [data-traits]').forEach(mark=>{
      mark.classList.add('analysis-mark');
      mark.addEventListener('click',event=>{event.stopPropagation();if(mark.classList.contains('feature-active'))this.inspectTraitOccurrence(mark,false)},opts);
    });
    const body=this.root.querySelector('[data-paper-body]');
    body?.addEventListener('pointerover',event=>this.onPassagePointerOver(event),opts);
    body?.addEventListener('pointerout',event=>this.onPassagePointerOut(event),opts);
    body?.addEventListener('keydown',event=>this.onEvidenceKeydown(event,false),opts);
    body?.addEventListener('input',()=>this.documentChanged(),opts);
    body?.addEventListener('mouseup',()=>this.showSelectionTools(),opts);
    body?.addEventListener('keyup',()=>this.showSelectionTools(),opts);
    body?.addEventListener('keydown',event=>this.onEditorKeydown(event),opts);
    document.addEventListener('selectionchange',()=>this.updateEditorCommandState(),opts);
    document.addEventListener('keydown',event=>this.onWorkspaceKeydown(event),opts);
    this.root.querySelector('[data-comparison-viewport]')?.addEventListener('scroll',()=>this.updatePanState(),{signal:this.abort.signal,passive:true});
    this.root.querySelector('[data-add-note]')?.addEventListener('mousedown',event=>{event.preventDefault();this.selectionAction('Note previewed for this demo · not saved')},opts);
    this.root.querySelector('[data-explain-selection]')?.addEventListener('mousedown',event=>{event.preventDefault();this.selectionAction('Explanation previewed · not saved')},opts);
    this.root.querySelector('[data-open-comparison]')?.addEventListener('click',event=>{this.compareOpener=event.currentTarget;this.toggleCompare(true)},opts);
    this.updateEditorCommandState();
  }
  configureReviewMode(){
    this.root.dataset.reviewMode='readonly';
    const body=this.root.querySelector('[data-paper-body]');
    if(body){body.contentEditable='false';body.setAttribute('role','document');body.setAttribute('aria-readonly','true');body.setAttribute('aria-label','Read-only current submission in review mode');body.removeAttribute('aria-multiline')}
    const paper=this.root.querySelector('.current-paper-column .paper');if(paper)paper.setAttribute('aria-label','Read-only current submission');
    this.root.querySelectorAll('[data-editor-command]').forEach(button=>{button.disabled=true;button.setAttribute('aria-disabled','true');button.tabIndex=-1});
    const status=this.root.querySelector('[data-save-state]');if(status)status.textContent=DEMO_STATUS;
    const paperStatus=this.root.querySelector('.current-paper-column .paper-foot span:last-child');if(paperStatus)paperStatus.textContent='READ-ONLY DEMO';
    const note=this.root.querySelector('[data-add-note]');if(note){note.hidden=true;note.setAttribute('aria-hidden','true')}
    this.root.querySelectorAll('[data-paper-body] [data-traits]').forEach(mark=>{mark.tabIndex=-1;mark.removeAttribute('role');mark.removeAttribute('aria-label')});
  }
  filterCatalog(){
    const query=this.catalogQuery.trim().toLowerCase(),division=this.catalogDivision;let visible=0;
    this.root.querySelectorAll('[data-catalog-tier-section]').forEach(section=>{
      let tierVisible=0;section.querySelectorAll('[data-catalog-feature]').forEach(button=>{const matchesDivision=button.dataset.catalogDivision===division,matchesQuery=!query||button.textContent.toLowerCase().includes(query),show=matchesDivision&&matchesQuery,examples=[...this.root.querySelectorAll('[data-paper-body] [data-traits]')].filter(mark=>this.traitCodes(mark).includes(button.dataset.catalogFeature)).length,badge=button.querySelector(':scope > em');button.hidden=!show;button.classList.toggle('has-text-example',examples>0);button.dataset.exampleCount=String(examples);if(badge){if(!badge.dataset.availability)badge.dataset.availability=badge.textContent;if(examples){badge.textContent=String(examples);badge.setAttribute('aria-label',`${examples} text ${examples===1?'example':'examples'}`)}else{badge.textContent=badge.dataset.availability;badge.setAttribute('aria-label',badge.dataset.availability)}}if(show){visible+=1;tierVisible+=1}});section.hidden=!tierVisible;
    });
    const represented=this.representedCodes(division),representedVisible=[...this.root.querySelectorAll(`[data-catalog-feature][data-catalog-division="${division}"]:not([hidden])`)].filter(button=>represented.has(button.dataset.catalogFeature)).length,count=this.root.querySelector('[data-catalog-count]');if(count)count.textContent=`${visible} listed · ${representedVisible} with text examples`;
    const catalog=this.root.querySelector('[data-feature-catalog]');let empty=catalog?.querySelector('[data-catalog-empty]');if(!empty&&catalog){empty=document.createElement('div');empty.className='catalog-empty-state';empty.dataset.catalogEmpty='';const title=document.createElement('b'),copy=document.createElement('span'),clear=document.createElement('button');title.textContent='No matching writing traits';copy.textContent='Try another term or return to the complete division list.';clear.type='button';clear.dataset.catalogClear='';clear.textContent='Clear search';empty.append(title,copy,clear);catalog.append(empty)}if(empty){empty.hidden=visible>0;empty.querySelector('button').hidden=!query}
  }
  scrollCatalogItem(item,behavior='auto'){
    const catalog=this.root.querySelector('.feature-catalog');if(!catalog||!item)return;
    const viewport=catalog.getBoundingClientRect(),rect=item.getBoundingClientRect();
    if(rect.top>=viewport.top&&rect.bottom<=viewport.bottom)return;
    const centered=catalog.scrollTop+(rect.top-viewport.top)-((viewport.height-rect.height)/2);
    catalog.scrollTo({top:Math.max(0,centered),behavior});
  }
  selectCatalogDivision(division,{selectFirst=true}={}){
    if(!['surface','discourse','rhetoric'].includes(division))return;this.catalogDivision=division;this.catalogQuery='';const search=this.root.querySelector('[data-catalog-search]');if(search)search.value='';
    this.root.querySelectorAll('[data-catalog-division-select]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.catalogDivisionSelect===division)));this.filterCatalog();
    this.catalogFeature=null;this.activeDivision=division;this.lensMode='division';this.root.dataset.selectedCatalogFeature='';this.root.dataset.activeDivision=division;this.root.dataset.lensMode='division';this.root.querySelectorAll('[data-catalog-feature]').forEach(button=>{button.classList.remove('selected');button.setAttribute('aria-pressed','false')});
    this.previewPinned=null;this.previewMark=null;this.hidePassagePreview();this.setEvidenceScope('division');const lens=this.root.querySelector('[data-catalog-lens-label]');if(lens)lens.textContent=`All ${SYSTEM_BY_ID[division].name} examples`;const highlights=this.refreshTraitHighlights();this.updateDivisionInspector(division,highlights);this.updateDivisionRibbon(division,highlights);this.announce(`${SYSTEM_BY_ID[division].name} division selected. ${highlights.current.length} annotated examples are visible in the current paper.`);
    if(selectFirst){const catalog=this.root.querySelector('.feature-catalog');catalog?.scrollTo({top:0,behavior:'auto'})}
  }
  showAllFeatureOverlays(){
    this.previewPinned=null;this.previewMark=null;this.hidePassagePreview();this.catalogFeature=null;this.lensMode='all';this.root.dataset.lensMode='all';this.root.dataset.selectedCatalogFeature='all';this.root.querySelectorAll('[data-catalog-feature]').forEach(button=>{button.classList.remove('selected');button.setAttribute('aria-pressed','false')});
    const label=this.root.querySelector('[data-catalog-lens-label]');if(label)label.textContent='All annotated writing examples';this.setEvidenceScope('overview');const highlights=this.refreshTraitHighlights();this.updateInspector('punctuation',true);this.updateComparisonRibbon('punctuation',true);this.root.querySelector('[data-active-overlay]').textContent=`ALL DIVISIONS · ${this.contextualPassages('.analysis-mark.feature-active').length} PASSAGES · ${highlights.current.length} EXAMPLES`;this.announce(`All divisions selected. ${highlights.current.length} annotated examples are visible.`);
  }
  selectCatalogFeature(code,{applyLens=true}={}){
    const feature=FEATURE_BY_CODE[code];if(!feature)return;const lens=guideLensFor(feature);this.catalogFeature=code;this.root.dataset.selectedCatalogFeature=code;
    this.previewPinned=null;this.previewMark=null;this.hidePassagePreview();this.setEvidenceScope('exact');this.lensMode='exact';this.activeDivision=feature.system;this.catalogDivision=feature.system;this.active=lens;this.root.dataset.lensMode='exact';this.root.dataset.activeDivision=feature.system;this.root.dataset.activeFeature=lens;
    this.root.querySelectorAll('[data-catalog-division-select]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.catalogDivisionSelect===feature.system)));
    this.root.querySelectorAll('[data-catalog-feature]').forEach(button=>{const selected=button.dataset.catalogFeature===code;button.classList.toggle('selected',selected);button.setAttribute('aria-pressed',String(selected))});
    const highlights=applyLens?this.refreshTraitHighlights():{current:[...this.root.querySelectorAll('[data-paper-body] [data-traits].feature-active')],baseline:[...this.root.querySelectorAll('[data-baseline-traits].baseline-feature-active')]};const label=this.root.querySelector('[data-catalog-lens-label]');if(label)label.textContent=`Only ${feature.professorLabel||feature.shortLabel||feature.name}`;this.updateCatalogInspector(feature,lens,highlights);
    if(applyLens){const first=highlights.current[0];if(first){this.previewMark=first;this.showPassagePreview(first,code,{automatic:true})}else this.showNoLocalEvidence(feature);const location=localizationPresentationFor(feature);this.announce(`${feature.professorLabel} selected. ${location.label.toLowerCase()}. ${highlights.current.length} ${highlights.current.length===1?'example is':'examples are'} available in this excerpt.`)}
    const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches,behavior=!applyLens||reduced?'auto':'smooth',selected=this.root.querySelector(`[data-catalog-feature="${code}"]`),section=selected?.closest('[data-catalog-tier-section]');if(selected&&(selected.hidden||section?.hidden)){this.catalogQuery='';this.catalogDivision=selected.dataset.catalogDivision||DIVISION_BY_TIER[feature.tier]||'surface';const search=this.root.querySelector('[data-catalog-search]');if(search)search.value='';this.root.querySelectorAll('[data-catalog-division-select]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.catalogDivisionSelect===this.catalogDivision)));this.filterCatalog()}this.scrollCatalogItem(selected,behavior);this.root.querySelector('.feature-inspector')?.scrollTo({top:0,behavior});
  }
  setEvidenceScope(scope){
    this.evidenceScope=scope;this.root.dataset.evidenceScope=scope;
  }
  setInspectorMethod({scope,measure,baseline}){
    const set=(selector,value)=>{const element=this.root.querySelector(selector);if(element)element.textContent=value};
    set('[data-method-scope]',scope);set('[data-method-measure]',measure);set('[data-method-baseline]',baseline);
  }
  setComparisonAction({enabled=true,label='Open full comparison'}={}){
    const button=this.root.querySelector('[data-open-comparison]');if(!button)return;button.disabled=!enabled;button.setAttribute('aria-disabled',String(!enabled));const text=button.querySelector('b');if(text)text.textContent=enabled?label:'No passage comparison available';
  }
  clearCatalogSelection(familyId){
    this.catalogFeature=null;this.root.dataset.selectedCatalogFeature=familyId==='all'?'all':'';this.root.querySelectorAll('[data-catalog-feature]').forEach(button=>{button.classList.remove('selected');button.setAttribute('aria-pressed','false')});
    const label=this.root.querySelector('[data-catalog-lens-label]');if(label)label.textContent=familyId==='all'?'Overview · all passage families':`Passage family · ${FEATURES[familyId]?.title||'context'}`;
  }
  selectPassageFamily(id,mark){
    const code=this.activeTraitFor(mark,{baseline:mark?.matches?.('[data-baseline-traits]')});if(code){this.selectCatalogFeature(code);this.previewPinned=mark||null;clearTimeout(this.previewShowTimer);clearTimeout(this.previewHideTimer);this.previewMark=mark||null;if(mark)this.showPassagePreview(mark,code,{pinned:true})}
    const passage=this.root.querySelector('[data-passage-inspector]');if(passage&&mark?.matches?.(':focus-visible'))passage.scrollIntoView({block:'nearest',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
  }
  inspectTraitOccurrence(mark,fromBaseline=false){
    const codes=this.traitCodes(mark,{baseline:fromBaseline}),code=this.catalogFeature&&codes.includes(this.catalogFeature)?this.catalogFeature:codes.find(item=>FEATURE_BY_CODE[item]?.system===this.activeDivision)||codes[0];if(!code)return;
    this.selectCatalogFeature(code);this.previewPinned=mark;this.previewMark=mark;this.root.querySelectorAll('.evidence-selected').forEach(item=>item.classList.remove('evidence-selected'));mark.classList.add('evidence-selected');this.showPassagePreview(mark,code,{pinned:true});this.announce(`${fromBaseline?'Baseline':'Current paper'} ${FEATURE_BY_CODE[code]?.professorLabel||'writing'} example selected.`);
  }
  updateDivisionInspector(division,highlights){
    const presentation=DIVISION_PRESENTATION[division],system=SYSTEM_BY_ID[division],represented=this.representedCodes(division),set=(selector,value)=>{const el=this.root.querySelector(selector);if(el)el.textContent=value};
    const divisionFeatures=Object.values(FEATURE_BY_CODE).filter(feature=>feature.system===division),imported=divisionFeatures.filter(feature=>feature.availableInImportedDocument).length;
    this.root.style.setProperty('--feature-accent',system.color);this.root.querySelector('.feature-inspector')?.style.setProperty('--feature-accent',system.color);
    set('[data-inspector-index]','DIVISION OVERVIEW');set('[data-inspector-glyph]',presentation.glyph);set('[data-inspector-state]',`${divisionFeatures.length} FEATURES`);set('[data-inspector-title]',presentation.title);set('[data-inspector-copy]',presentation.copy);set('[data-evidence-heading]',`${system.name} evidence`);
    set('[data-current-label]','CURRENT PAPER');set('[data-current-value]',String(highlights.current.length));set('[data-current-unit]','VISIBLE EXAMPLES');set('[data-baseline-label]','SELECTED BASELINE PAPER');set('[data-baseline-value]',`${highlights.baseline.length} examples`);set('[data-delta-value]','12-paper profile · 3 viewable');set('[data-deviation-badge]','OVERVIEW');set('[data-position-caption]','Choose a feature or colored example to inspect a comparable passage.');
    set('[data-inspector-why]',presentation.why);set('[data-related-label]','RELATED MEASURES IN THIS DIVISION');set('[data-correlation-strength]','SAME DIVISION');set('[data-active-overlay]',`${system.name.toUpperCase()} DIVISION · ${highlights.current.length} COLORED EXAMPLES`);set('[data-baseline-lens]',`${system.name.toUpperCase()} DIVISION · ${highlights.baseline.length} BASELINE EXAMPLES`);
    this.setInspectorMethod({scope:'Division overview',measure:`${imported} imported-document features`,baseline:'12-paper profile · 3 viewable papers'});this.setComparisonAction({enabled:true});
    const comparison=this.root.querySelector('.comparison-orbit');if(comparison)comparison.dataset.positionState='overview';
    const codes=[...represented].slice(0,2),buttons=[...this.root.querySelectorAll('[data-correlate]')];buttons.forEach((button,index)=>{const feature=FEATURE_BY_CODE[codes[index]];if(!feature){button.hidden=true;return}button.hidden=false;button.dataset.catalogRelated=feature.code;button.querySelector('b').textContent=feature.professorLabel;button.querySelector('small').textContent=feature.plain;button.querySelector('em').textContent=`T${String(feature.tier).padStart(2,'0')}`});
    this.showDivisionCue(system.name,presentation.copy);
  }
  updateDivisionRibbon(division,highlights){
    const system=SYSTEM_BY_ID[division],set=(selector,value)=>{const el=this.root.querySelector(selector);if(el)el.textContent=value};set('[data-ribbon-glyph]',system.name[0]);set('[data-ribbon-title]',`${system.name} division`);set('[data-ribbon-current]',`${highlights.current.length} examples`);set('[data-ribbon-baseline]',`${highlights.baseline.length} examples`);set('[data-ribbon-delta]','Choose a feature to isolate exact evidence');
  }
  showDivisionCue(name,copy){
    const live=this.root.querySelector('[data-passage-live]'),empty=this.root.querySelector('[data-passage-empty]'),region=this.root.querySelector('[data-passage-inspector]');if(live)live.hidden=true;if(!empty)return;if(region)region.setAttribute('aria-label',`${name} division evidence`);empty.hidden=false;const label=empty.querySelector('.inspector-label span'),badge=empty.querySelector('.inspector-label b'),title=empty.querySelector('.passage-empty-cue b'),text=empty.querySelector('.passage-empty-cue span');if(label)label.textContent=`${name.toUpperCase()} DIVISION`;if(badge)badge.textContent='SELECT A FEATURE OR EXAMPLE';if(title)title.textContent=`All ${name} examples are visible`;if(text)text.textContent=copy;
  }
  showNoLocalEvidence(feature){
    const live=this.root.querySelector('[data-passage-live]'),empty=this.root.querySelector('[data-passage-empty]'),region=this.root.querySelector('[data-passage-inspector]');if(live)live.hidden=true;if(!empty)return;const location=localizationPresentationFor(feature);empty.hidden=false;if(region)region.setAttribute('aria-label',`${feature.professorLabel}: ${location.label.toLowerCase()}`);const label=empty.querySelector('.inspector-label span'),badge=empty.querySelector('.inspector-label b'),title=empty.querySelector('.passage-empty-cue b'),text=empty.querySelector('.passage-empty-cue span');if(label)label.textContent='EVIDENCE SCOPE';if(badge)badge.textContent=location.label;if(title)title.textContent=feature.professorLabel;if(text)text.textContent=feature.localizationGuidance||`${location.explanation} ${feature.plain}.`;
  }
  updateCatalogInspector(feature,lens,highlights={current:[],baseline:[]}){
    const tier=TIER_BY_ID[feature.tier],kind=localizationKindFor(feature),captured=kind!=='behavioral',location=localizationPresentationFor(feature),inline=canLocateInText(feature),direct=DIRECT_LOCALIZATION_KINDS.has(kind),set=(selector,value)=>{const el=this.root.querySelector(selector);if(el)el.textContent=value};
    const professorTitle=feature.professorLabel||feature.shortLabel||feature.name,technicalNote=professorTitle===feature.name?'':` Technical measure: ${feature.name}.`,teaching=TRAIT_EVIDENCE[feature.code];
    const statusOverrides={semicolon_colon_rate:'review',clause_depth_mean:'review',source_integration_style:'review',pause_density:'aligned',revision_depth:'aligned',char_trigram_profile_divergence:'aligned'},effectiveStatus=teaching?.statusLabel?.toLowerCase()||statusOverrides[feature.code]||feature.status,numeric=captured?(feature.current.match(/-?\d+(?:\.\d+)?/)?.[0]||'—'):'—',status=feature.tier===17?'CAPTURE READY':feature.tier===0?'COMPARISON ONLY':effectiveStatus.toUpperCase(),isReview=effectiveStatus==='review',isAligned=effectiveStatus==='aligned',position=feature.tier===17?{state:'overview',badge:'NOT CAPTURED',caption:'Available only from a captured drafting session.'}:isReview?{state:'outside',badge:'OUTSIDE RANGE',caption:'Outside the illustrative baseline range.'}:isAligned?{state:'aligned',badge:'ALIGNED',caption:'Within the illustrative baseline range.'}:{state:'watch',badge:'WATCH',caption:'Near the edge of the illustrative baseline range.'};
    const reading=kind==='behavioral'?`${professorTitle} uses events from a captured drafting session and is not available from uploaded prose.`:teaching?.explanation||`${professorTitle} measures ${feature.plain}.`;
    const range=feature.baseline.match(/-?\d+(?:\.\d+)?\s*[–—-]\s*-?\d+(?:\.\d+)?/)?.[0],percent=feature.baseline.match(/\d+(?:\.\d+)?%/)?.[0],compactBaseline=teaching?.baselineValue||(captured?(range||percent||'12-paper range'):'Not available'),displayCurrent=teaching?.currentValue||numeric,displayUnit=teaching?.currentUnit,displayStatus=teaching?.statusLabel||status,unitByCode={semicolon_colon_rate:'MARKS / 1K',clause_depth_mean:'CLAUSE DEPTH',source_integration_style:'SOURCE HANDOFFS'};
    const shown=highlights.current.length?`${highlights.current.length} ${highlights.current.length===1?'example':'examples'} shown.`:'No inline examples are appropriate for this measure.';
    set('[data-inspector-index]','SELECTED FEATURE');set('[data-inspector-glyph]',feature.tier===0?'CMP':String(feature.tier).padStart(2,'0'));set('[data-inspector-state]',location.label);set('[data-inspector-title]',professorTitle);set('[data-inspector-copy]',reading);set('[data-evidence-heading]',`${professorTitle} evidence`);
    set('[data-current-label]',captured?'CURRENT PAPER':'CURRENT SESSION');set('[data-current-value]',displayCurrent);set('[data-current-unit]',captured?displayUnit||unitByCode[feature.code]||'CURRENT SIGNAL':'LIVE SESSION');set('[data-baseline-label]',captured?'ILLUSTRATIVE BASELINE':'BASELINE STATUS');set('[data-baseline-value]',captured?`${compactBaseline}`:'Not captured');set('[data-delta-value]',captured?'12-paper profile · 3 viewable':'live session required');set('[data-deviation-badge]',displayStatus);set('[data-position-caption]',`${position.caption} ${shown}`);
    set('[data-inspector-why]',`${professorTitle} measures ${feature.plain}.${technicalNote} ${location.explanation} ${direct?'Colored glass marks the directly annotated text.':inline?'Colored glass marks representative context, not ownership of a single phrase.':'No inline highlight is shown because assigning this result to one phrase would be misleading.'}`);set('[data-related-label]','RELATED MEASURES IN THIS TIER');set('[data-correlation-strength]',`${tier.name.toUpperCase()} · TIER ${feature.tier}`);
    this.setInspectorMethod({scope:location.label,measure:feature.name,baseline:captured?'12-paper profile · 3 viewable papers':'Live drafting session required'});this.setComparisonAction({enabled:captured});
    const comparison=this.root.querySelector('.comparison-orbit');if(comparison)comparison.dataset.positionState=position.state;
    let siblings=tier.features.map(code=>FEATURE_BY_CODE[code]).filter(item=>item&&item.code!==feature.code);if(siblings.length<2)siblings=Object.values(FEATURE_BY_CODE).filter(item=>item.code!==feature.code&&item.system===feature.system);const nextIndex=siblings.findIndex(item=>item.index>feature.index),start=nextIndex<0?0:nextIndex,related=[siblings[start%siblings.length],siblings[(start+1)%siblings.length]].filter(Boolean),buttons=[...this.root.querySelectorAll('[data-correlate]')];buttons.forEach((button,index)=>{const item=related[index];if(!item){button.hidden=true;return}button.hidden=false;button.dataset.catalogRelated=item.code;button.dataset.correlate=guideLensFor(item);button.querySelector('b').textContent=item.professorLabel||item.shortLabel||item.name;button.querySelector('small').textContent=`${item.plain} · Technical: ${item.name}`;button.querySelector('em').textContent=`T${String(item.tier).padStart(2,'0')}`});
    const baselineCompact=feature.baseline.match(/\d+(?:\.\d+)?\s*[–—-]\s*\d+(?:\.\d+)?/)?.[0]||'12-paper profile';
    set('[data-ribbon-glyph]',feature.tier===0?'CMP':String(feature.tier).padStart(2,'0'));set('[data-ribbon-title]',professorTitle);set('[data-ribbon-current]',captured?displayCurrent:'Not captured');set('[data-ribbon-baseline]',teaching?.baselineValue||baselineCompact);set('[data-ribbon-delta]',displayStatus);
    const matches=this.contextualPassages('.analysis-mark.feature-active').length,baselineMatches=this.contextualPassages('.baseline-feature-active').length;set('[data-active-overlay]',inline?`${location.label} · ${professorTitle.toUpperCase()} · ${highlights.current.length} EXAMPLES IN ${matches} PASSAGES`:`${location.label} · NO INLINE HIGHLIGHT`);set('[data-baseline-lens]',inline?`${professorTitle.toUpperCase()} · ${highlights.baseline.length} EXAMPLES IN ${baselineMatches} BASELINE PASSAGES`:`${location.label} · BASELINE PROFILE`);
    this.root.style.setProperty('--feature-accent',feature.color);const inspector=this.root.querySelector('.feature-inspector');if(inspector)inspector.style.setProperty('--feature-accent',feature.color);
  }
  setupAnimationLifecycle(){
    if(!this.canvas)return;
    const sync=()=>this.syncAnimationState();
    document.addEventListener('visibilitychange',sync,{signal:this.abort.signal});
    this.motionPreference.addEventListener?.('change',sync);this.abort.signal.addEventListener('abort',()=>this.motionPreference.removeEventListener?.('change',sync),{once:true});
    if('IntersectionObserver' in window){this.canvasObserver=new IntersectionObserver(entries=>{this.canvasVisible=Boolean(entries[0]?.isIntersecting);this.syncAnimationState()},{threshold:.02});this.canvasObserver.observe(this.canvas)}
    this.drawCorrelation(performance.now());this.syncAnimationState();
  }
  shouldAnimate(){return Boolean(this.canvas&&!this.motionPreference.matches&&!document.hidden&&this.canvasVisible)}
  syncAnimationState(){
    cancelAnimationFrame(this.frame);this.frame=0;
    if(this.shouldAnimate())this.frame=requestAnimationFrame(time=>this.animate(time));else this.drawCorrelation(performance.now());
  }
  trackGlassLight(event){
    if(this.motionPreference.matches||this.transparencyPreference.matches)return;this.pendingPointer={x:event.clientX,y:event.clientY};if(this.pointerFrame)return;
    this.pointerFrame=requestAnimationFrame(()=>{this.pointerFrame=0;if(!this.pendingPointer||!this.root.isConnected)return;const point=this.pendingPointer;this.pendingPointer=null;const rect=this.root.getBoundingClientRect(),x=Math.max(0,Math.min(1,(point.x-rect.left)/rect.width)),y=Math.max(0,Math.min(1,(point.y-rect.top)/rect.height));this.root.style.setProperty('--glass-x',`${(x*100).toFixed(1)}%`);this.root.style.setProperty('--glass-y',`${(y*100).toFixed(1)}%`);this.root.style.setProperty('--scene-x',`${((.5-x)*8).toFixed(2)}px`);this.root.style.setProperty('--scene-y',`${((.5-y)*5).toFixed(2)}px`)});
  }
  contextualPassages(selector){
    return [...new Set([...this.root.querySelectorAll(selector)].map(mark=>mark.closest('p,blockquote')||mark))];
  }
  setFeature(id,{scope='family',preservePreview=false}={}){
    this.active=id;
    if(!preservePreview){this.previewPinned=null;this.previewMark=null;this.hidePassagePreview()}
    this.setEvidenceScope(id==='all'?'overview':scope);
    this.lensMode=id==='all'?'all':'family';this.root.dataset.lensMode=this.lensMode;
    if(scope!=='exact')this.clearCatalogSelection(id);
    EDITOR_STATE.active=id;
    this.root.dataset.activeFeature=id;
    this.root.querySelectorAll('[data-feature-select]').forEach(button=>{const on=id==='all'||button.dataset.featureSelect===id;button.classList.toggle('active',on);button.setAttribute('aria-pressed',String(on))});
    const marks=[...this.root.querySelectorAll('.analysis-mark')];
    marks.forEach(mark=>mark.classList.toggle('feature-active',this.traitMatches(mark)));
    if(this.previewMark&&!this.previewMark.classList.contains('feature-active')){clearTimeout(this.previewShowTimer);clearTimeout(this.previewHideTimer);this.previewMark=null;this.hidePassagePreview()}
    const field=this.root.querySelector('[data-correlation-field]'),canvas=this.root.querySelector('[data-correlation-canvas]'),focus=id==='all'?null:FEATURES[id],setField=(selector,value)=>{const el=field?.querySelector(selector);if(el)el.textContent=value};
    field?.classList.toggle('is-focused',!!focus);if(field)field.dataset.focusFeature=id;
    setField('[data-correlation-mode]',focus?'FOCUSED':'FULL FIELD');setField('[data-correlation-glyph]',focus?focus.glyph:'∞');setField('[data-correlation-focus-label]',focus?'FOCUS':'OVERVIEW');setField('[data-correlation-title]',focus?focus.title:'Authorship field');setField('[data-correlation-meta]',focus?`${focus.related.length} connected features`:'6 visible feature families');setField('[data-correlation-caption]',focus?'Select another authorship feature to travel through its local relationship field. Use ∞ for the full constellation.':'The full authorship field shows every visible feature family and its strongest relationships.');
    canvas?.setAttribute('aria-label',focus?`Focused ${focus.title.toLowerCase()} correlation constellation`:'Full authorship feature correlation constellation');
    const matched=marks.filter(mark=>mark.classList.contains('feature-active')),passages=this.contextualPassages('.analysis-mark.feature-active');
    this.syncBaselineHighlights();
    this.buildComparisonPairs();
    this.updateDifferenceRail(matched);
    if(id==='all'){
      this.root.querySelector('[data-active-overlay]').textContent=`OVERVIEW · ${passages.length} CONTEXT PASSAGES`;
      this.updateInspector('punctuation',true);
      this.updateComparisonRibbon('punctuation',true);
    }else{
      this.root.querySelector('[data-active-overlay]').textContent=`PASSAGE FAMILY · ${FEATURES[id].title.toUpperCase()} · ${passages.length} PASSAGES`;
      this.updateInspector(id,false);
      this.updateComparisonRibbon(id,false);
    }
  }
  revealCorrelationField(){
    const library=this.root.querySelector('.feature-library'),field=this.root.querySelector('[data-correlation-field]');if(!library||!field)return;
    const top=Math.max(0,field.offsetTop+field.offsetHeight-library.clientHeight+14),behavior=matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth';library.scrollTo({top,behavior});
    field.classList.remove('camera-arrival');void field.offsetWidth;field.classList.add('camera-arrival');clearTimeout(this.cameraTimer);this.cameraTimer=setTimeout(()=>field.classList.remove('camera-arrival'),760);
  }
  toggleCompare(force,restore=false){
    const next=typeof force==='boolean'?force:!this.compare;if(next===this.compare&&!restore)return;
    this.compare=next;EDITOR_STATE.compare=this.compare;
    this.root.classList.toggle('compare-mode',this.compare);
    const button=this.root.querySelector('[data-document-compare]'),column=this.root.querySelector('.baseline-paper-column'),viewport=this.root.querySelector('[data-comparison-viewport]'),ribbon=this.root.querySelector('[data-comparison-ribbon]');
    button?.setAttribute('aria-pressed',String(this.compare));
    button?.setAttribute('aria-label',this.compare?'Exit baseline comparison':'Compare baseline papers');
    const label=button?.querySelector('b');if(label)label.textContent=this.compare?'Exit comparison':'Compare baseline';
    column?.setAttribute('aria-hidden',String(!this.compare));
    ribbon?.setAttribute('aria-hidden',String(!this.compare));
    if(column){column.hidden=!this.compare;column.inert=!this.compare}if(ribbon){ribbon.hidden=!this.compare;ribbon.inert=!this.compare}
    viewport?.setAttribute('aria-label',this.compare?'Scrollable current and baseline paper comparison':'Scrollable current paper');
    const status=this.root.querySelector('[data-save-state]');if(status)status.textContent=DEMO_STATUS;
    this.announce(this.compare?`Baseline comparison opened with illustrative paper ${BASELINES[this.baselineIndex].paper}, ${BASELINES[this.baselineIndex].title}.`:'Baseline comparison closed. Current paper only.');
    requestAnimationFrame(()=>{
      if(viewport){const left=restore?EDITOR_STATE.scrollLeft:0,top=restore?EDITOR_STATE.scrollTop:viewport.scrollTop;viewport.scrollTo({left,top,behavior:'auto'})}
      this.updateDifferenceSelection(false);this.updateDifferenceRail([...this.root.querySelectorAll('.analysis-mark.feature-active')]);this.updatePanState();this.resize();
      if(this.compare){this.root.querySelector('[data-difference-next]')?.focus({preventScroll:true})}else if(this.compareOpener?.isConnected){this.compareOpener.focus({preventScroll:true})}
    });
  }
  changeBaseline(direction){
    this.baselineIndex=(this.baselineIndex+direction+BASELINES.length)%BASELINES.length;
    EDITOR_STATE.baselineIndex=this.baselineIndex;
    this.renderBaseline();
    const status=this.root.querySelector('[data-save-state]');if(status)status.textContent=DEMO_STATUS;this.announce(`Illustrative baseline paper ${BASELINES[this.baselineIndex].paper} selected: ${BASELINES[this.baselineIndex].title}.`);
  }
  renderSafeBaselineMarkup(container,markup){
    if(!container)return;const template=document.createElement('template');template.innerHTML=markup;
    const allowedTags=new Set(['P','SPAN','MARK','BLOCKQUOTE','CITE','SMALL']),walker=document.createTreeWalker(template.content,NodeFilter.SHOW_ELEMENT);const elements=[];while(walker.nextNode())elements.push(walker.currentNode);
    elements.reverse().forEach(element=>{
      if(!allowedTags.has(element.tagName)){element.replaceWith(document.createTextNode(element.textContent||''));return}
      [...element.attributes].forEach(attribute=>{const allowed=attribute.name==='data-baseline-feature'||(attribute.name==='class'&&element.tagName==='SPAN'&&attribute.value==='quote-mark');if(!allowed)element.removeAttribute(attribute.name)});
      if(element.hasAttribute('data-baseline-feature'))element.dataset.baselineFeature=element.dataset.baselineFeature.split(/\s+/).filter(value=>/^[a-z]+$/.test(value)).join(' ');
    });
    container.replaceChildren(template.content.cloneNode(true));
  }
  renderBaseline(){
    const paper=BASELINES[this.baselineIndex],set=(selector,value)=>{const el=this.root.querySelector(selector);if(el)el.textContent=value};
    const counter=`PAPER ${paper.paper} OF ${String(BASELINES.length).padStart(2,'0')}`,ribbon=this.root.querySelector('[data-comparison-ribbon]'),switchButtons=[...this.root.querySelectorAll('[data-baseline-prev],[data-baseline-next]')];
    ribbon?.setAttribute('aria-busy','true');switchButtons.forEach(button=>button.disabled=true);
    set('[data-baseline-code]',paper.code);set('[data-baseline-page]',paper.page);set('[data-baseline-course]',paper.course);set('[data-baseline-title]',paper.title);set('[data-baseline-meta]',paper.meta);set('[data-baseline-date]',paper.date);set('[data-baseline-counter]',counter);set('[data-baseline-counter-secondary]',counter);
    const body=this.root.querySelector('[data-baseline-body]');this.renderSafeBaselineMarkup(body,paper.body);this.annotateBaselineEvidence();
    const article=this.root.querySelector('.baseline-paper');if(article){article.classList.remove('baseline-paper-swap');void article.offsetWidth;article.classList.add('baseline-paper-swap')}
    this.syncBaselineHighlights();this.buildComparisonPairs();if(this.catalogFeature&&this.previewMark){if(!this.previewMark.isConnected){this.previewPinned=null;this.previewMark=this.root.querySelector('[data-paper-body] [data-traits].feature-active')||this.root.querySelector('[data-baseline-body] [data-baseline-traits].baseline-feature-active')}if(this.previewMark)this.showPassagePreview(this.previewMark,this.catalogFeature,{pinned:Boolean(this.previewPinned),automatic:!this.previewPinned})}
    clearTimeout(this.busyTimer);this.busyTimer=setTimeout(()=>{ribbon?.setAttribute('aria-busy','false');switchButtons.forEach(button=>button.disabled=false)},220);
  }
  syncBaselineHighlights(){
    const marks=[...this.root.querySelectorAll('[data-baseline-traits]')];
    marks.forEach(mark=>{const active=this.traitMatches(mark,{baseline:true});mark.classList.toggle('baseline-feature-active',active);if(active)this.applyTraitTone(mark,this.activeTraitFor(mark,{baseline:true}))});
    this.syncEvidenceRoving(marks,{baseline:true});
    const count=marks.filter(mark=>mark.classList.contains('baseline-feature-active')).length,label=this.root.querySelector('[data-baseline-lens]');
    if(label&&this.lensMode==='all')label.textContent=`ALL DIVISIONS · ${count} BASELINE EXAMPLES`;else if(label&&this.lensMode==='division')label.textContent=`${SYSTEM_BY_ID[this.activeDivision].name.toUpperCase()} DIVISION · ${count} BASELINE EXAMPLES`;else if(label&&this.lensMode==='exact')label.textContent=`${FEATURE_BY_CODE[this.catalogFeature]?.professorLabel.toUpperCase()||'FEATURE'} · ${count} BASELINE EXAMPLES`;else if(label)label.textContent=`${FEATURES[this.active]?.title.toUpperCase()||'FEATURE'} LENS · ${count} BASELINE MATCHES`;
  }
  updateComparisonRibbon(id,aggregate){
    const f=FEATURES[id],set=(selector,value)=>{const el=this.root.querySelector(selector);if(el)el.textContent=value};
    const family=!aggregate&&this.evidenceScope==='family';set('[data-ribbon-glyph]',aggregate?'∞':f.glyph);set('[data-ribbon-title]',aggregate?'All passage families':family?`${f.title} passages`:f.title);set('[data-ribbon-current]',aggregate?'6 families':family?'Context':f.current);set('[data-ribbon-baseline]',aggregate?'12-paper profile':family?'Prior passage':f.baseline);set('[data-ribbon-delta]',aggregate?'Context overview':family?'Choose an exact feature for a measured range':'Illustrative comparison only');
  }
  buildComparisonPairs(){
    this.root.querySelectorAll('.comparison-target').forEach(el=>{el.classList.remove('comparison-target','comparison-target-selected');el.removeAttribute('data-pair-label')});
    const collect=selector=>{
      const seen=new Set(),matches=[];
      this.root.querySelectorAll(selector).forEach(el=>{
        let target=el.closest('p,blockquote')||el;if(!target||seen.has(target))return;seen.add(target);matches.push(target);
      });
      return matches;
    };
    const current=collect('.analysis-mark.feature-active'),baseline=collect('[data-baseline-traits].baseline-feature-active'),length=Math.max(current.length,baseline.length);
    this.comparisonPairs=Array.from({length},(_,index)=>({current:current[index]||null,baseline:baseline[index]||null}));
    this.comparisonPairs.forEach((pair,index)=>Object.entries(pair).forEach(([side,el])=>{if(!el)return;el.classList.add('comparison-target',`${side}-comparison-target`);el.dataset.pairLabel=String(index+1).padStart(2,'0')}));
    this.differenceIndex=Math.min(this.differenceIndex,Math.max(0,length-1));EDITOR_STATE.differenceIndex=this.differenceIndex;
    const occurrence=this.root.querySelector('[data-ribbon-occurrences]');if(occurrence)occurrence.textContent=`${current.length} current · ${baseline.length} baseline passages`;
    this.updateDifferenceSelection(false);
  }
  updateDifferenceSelection(scroll){
    this.root.querySelectorAll('.comparison-target-selected').forEach(el=>el.classList.remove('comparison-target-selected'));
    const pair=this.comparisonPairs[this.differenceIndex],counter=this.root.querySelector('[data-difference-counter]'),buttons=this.root.querySelectorAll('[data-difference-prev],[data-difference-next]');
    if(counter)counter.textContent=this.comparisonPairs.length?`${this.differenceIndex+1} / ${this.comparisonPairs.length}`:'0 / 0';buttons.forEach(button=>button.disabled=!this.comparisonPairs.length);
    if(!pair)return;[pair.current,pair.baseline].filter(Boolean).forEach(el=>el.classList.add('comparison-target-selected'));
    if(scroll){
      const viewport=this.root.querySelector('[data-comparison-viewport]'),scrollable=viewport.scrollHeight>viewport.clientHeight+4&&getComputedStyle(viewport).overflowY!=='visible';if(!scrollable){(pair.current||pair.baseline)?.scrollIntoView({block:'center',behavior:this.motionPreference.matches?'auto':'smooth'});return}const v=viewport.getBoundingClientRect(),tops=[pair.current,pair.baseline].filter(Boolean).map(el=>el.getBoundingClientRect().top-v.top+viewport.scrollTop),target=tops.reduce((a,b)=>a+b,0)/tops.length;
      viewport.scrollTo({top:Math.max(0,target-150),left:viewport.scrollLeft,behavior:this.motionPreference.matches?'auto':'smooth'});
    }
  }
  stepDifference(direction){if(!this.comparisonPairs.length)return;this.differenceIndex=(this.differenceIndex+direction+this.comparisonPairs.length)%this.comparisonPairs.length;EDITOR_STATE.differenceIndex=this.differenceIndex;this.updateDifferenceSelection(true)}
  panToPaper(which){
    const viewport=this.root.querySelector('[data-comparison-viewport]'),column=this.root.querySelector(which==='baseline'?'.baseline-paper-column':'.current-paper-column');if(!viewport||!column)return;
    viewport.scrollTo({left:Math.max(0,column.offsetLeft-20),top:viewport.scrollTop,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
  }
  updatePanState(){
    const viewport=this.root.querySelector('[data-comparison-viewport]');if(!viewport)return;EDITOR_STATE.scrollTop=viewport.scrollTop;EDITOR_STATE.scrollLeft=viewport.scrollLeft;
    const maxScroll=Math.max(0,viewport.scrollWidth-viewport.clientWidth),focus=viewport.scrollLeft>maxScroll/2?'baseline':'current';this.root.querySelectorAll('[data-pan-paper]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.panPaper===focus)));
  }
  updateInspector(id,aggregate){
    const f=FEATURES[id];
    const set=(selector,value)=>{const el=this.root.querySelector(selector);if(el)el.textContent=value};
    const position={unit:aggregate?'PASSAGE FAMILIES':'CONTEXT ONLY',badge:aggregate?'OVERVIEW':'PASSAGE FAMILY',caption:'Select an exact feature in the left rail to see a measured value and established range.',state:'overview'};
    set('[data-inspector-index]',aggregate?'PASSAGE OVERVIEW':'PASSAGE FAMILY');set('[data-inspector-glyph]',aggregate?'∞':f.glyph);set('[data-inspector-state]',aggregate?'ALL VISIBLE EXAMPLES':'CONTEXT, NOT AN EXACT MEASURE');set('[data-inspector-title]',aggregate?'Writing-pattern context':`${f.title} passages`);set('[data-inspector-copy]',aggregate?'Every colored passage family is visible. Choose one exact feature when you need a measured baseline comparison.':`${f.copy} This view groups related passages before an exact feature is selected.`);set('[data-evidence-heading]',aggregate?'Writing evidence':`${f.title} evidence`);set('[data-current-label]','CURRENT VIEW');set('[data-current-value]',aggregate?'6':'—');set('[data-current-unit]',position.unit);set('[data-baseline-label]','BASELINE PROFILE');set('[data-baseline-value]',aggregate?'12-paper profile':'Choose a feature');set('[data-delta-value]','3 viewable papers');set('[data-deviation-badge]',position.badge);set('[data-position-caption]',position.caption);set('[data-inspector-why]',aggregate?'Related passage families organize a review; they do not create independent proof.':`${f.why} The colored passage is a broader context region, not an exact token-level attribution.`);set('[data-related-label]','RELATED CONTEXT LENSES');set('[data-correlation-strength]','OPEN A LENS');
    this.setInspectorMethod({scope:aggregate?'All visible passage families':'Passage-family context',measure:aggregate?'6 context families':`${f.title} context lens`,baseline:'12-paper profile · 3 viewable papers'});this.setComparisonAction({enabled:true});
    const comparison=this.root.querySelector('.comparison-orbit');
    if(comparison)comparison.dataset.positionState=position.state;
    const related=aggregate?FEATURES.punctuation.related:f.related;
    const buttons=[...this.root.querySelectorAll('[data-correlate]')];related.forEach((entry,index)=>{const button=buttons[index];if(!button)return;delete button.dataset.catalogRelated;button.dataset.correlate=entry[0];button.querySelector('b').textContent=entry[1];button.querySelector('small').textContent=entry[2];button.querySelector('em').textContent='OPEN'});
  }
  updateDifferenceRail(marks){
    const rail=this.root.querySelector('[data-difference-rail]');if(!rail)return;rail.innerHTML='';
    const paper=this.root.querySelector('.paper'),top=paper.getBoundingClientRect().top,height=Math.max(1,paper.getBoundingClientRect().height);
    [...new Set(marks.map(mark=>Math.max(1,Math.min(98,(mark.getBoundingClientRect().top-top)/height*100)).toFixed(1)))].forEach(position=>{const tick=document.createElement('i');tick.style.top=`${position}%`;rail.append(tick)});
  }
  onPassagePointerOver(event){
    const mark=event.target.closest?.('[data-paper-body] [data-traits].feature-active, [data-baseline-body] [data-baseline-traits].baseline-feature-active');if(!mark||!this.root.contains(mark))return;
    if(this.previewPinned)return;
    clearTimeout(this.previewHideTimer);if(mark===this.previewMark)return;
    clearTimeout(this.previewShowTimer);this.previewMark=mark;
    const baseline=mark.matches('[data-baseline-traits]'),code=this.activeTraitFor(mark,{baseline});
    this.previewShowTimer=setTimeout(()=>{if(this.previewMark===mark&&(mark.classList.contains('feature-active')||mark.classList.contains('baseline-feature-active')))this.showPassagePreview(mark,code)},85);
  }
  onPassagePointerOut(event){
    if(this.previewPinned)return;
    const mark=event.target.closest?.('[data-paper-body] [data-traits].feature-active, [data-baseline-body] [data-baseline-traits].baseline-feature-active');if(!mark)return;
    const next=event.relatedTarget?.closest?.('[data-paper-body] [data-traits].feature-active, [data-baseline-body] [data-baseline-traits].baseline-feature-active');if(next){clearTimeout(this.previewHideTimer);return}
    clearTimeout(this.previewShowTimer);this.previewMark=null;clearTimeout(this.previewHideTimer);this.previewHideTimer=setTimeout(()=>this.hidePassagePreview(),420);
  }
  passageSnippet(element,max=112){
    if(!element)return 'No directly comparable passage in this baseline paper.';
    const source=element.tagName==='MARK'?(element.closest('span[data-feature],span[data-baseline-feature]')||element.closest('p,blockquote')):element;
    const text=(source?.textContent||element.textContent||'').replace(/\s+/g,' ').trim();if(text.length<=max)return text;
    const exact=(element.textContent||'').replace(/\s+/g,' ').trim(),exactIndex=exact?text.toLowerCase().indexOf(exact.toLowerCase()):-1;
    if(exactIndex<0)return `${text.slice(0,max).replace(/\s+\S*$/,'')}…`;
    const context=Math.max(18,Math.floor((max-exact.length)/2)),rawStart=Math.max(0,exactIndex-context),rawEnd=Math.min(text.length,exactIndex+exact.length+context),start=rawStart?Math.max(rawStart,text.lastIndexOf(' ',rawStart)+1):0,nextSpace=text.indexOf(' ',rawEnd),end=rawEnd<text.length&&(nextSpace>rawEnd&&nextSpace<=rawEnd+18)?nextSpace:rawEnd,snippet=text.slice(start,end).trim();
    return `${start>0?'…':''}${snippet}${end<text.length?'…':''}`;
  }
  evidenceOccurrences(code,{baseline=false}={}){
    const selector=baseline?'[data-baseline-body] [data-baseline-traits]':'[data-paper-body] [data-traits]',activeClass=baseline?'baseline-feature-active':'feature-active',marks=[...this.root.querySelectorAll(selector)].filter(element=>element.classList.contains(activeClass)&&this.traitCodes(element,{baseline}).includes(code));return this.evidenceControlCandidates(marks,{baseline});
  }
  stepPassagePreview(direction){
    const code=this.catalogFeature||this.activeTraitFor(this.previewMark,{baseline:this.previewMark?.matches?.('[data-baseline-traits]')});if(!code)return;const current=this.evidenceOccurrences(code);if(!current.length)return;
    const shown=Math.max(0,Number(this.root.querySelector('[data-passage-position]')?.textContent||1)-1),index=current.includes(this.previewMark)?current.indexOf(this.previewMark):shown,next=Math.max(0,Math.min(current.length-1,index+direction)),target=current[next];
    this.previewPinned=target;this.previewMark=target;this.root.querySelectorAll('.evidence-selected').forEach(element=>element.classList.remove('evidence-selected'));target.classList.add('evidence-selected');this.showPassagePreview(target,code,{pinned:true});target.scrollIntoView({block:'center',inline:'nearest',behavior:this.motionPreference.matches?'auto':'smooth'});this.announce(`${FEATURE_BY_CODE[code]?.professorLabel||'Evidence'}, example ${next+1} of ${current.length}.`);
  }
  showPassagePreview(mark,code,{pinned=false,automatic=false}={}){
    const feature=FEATURE_BY_CODE[code],live=this.root.querySelector('[data-passage-live]'),empty=this.root.querySelector('[data-passage-empty]');if(!feature||!live)return;
    const location=localizationPresentationFor(feature);
    const current=this.evidenceOccurrences(code),baseline=this.evidenceOccurrences(code,{baseline:true}),fromBaseline=mark?.matches?.('[data-baseline-traits]'),index=Math.max(0,(fromBaseline?baseline:current).indexOf(mark)),currentMark=fromBaseline?(current[Math.min(index,Math.max(0,current.length-1))]||current[0]||null):mark,baselineMark=fromBaseline?mark:(baseline[Math.min(index,Math.max(0,baseline.length-1))]||baseline[0]||null),paper=BASELINES[this.baselineIndex],teaching=TRAIT_EVIDENCE[code],currentIndex=current.indexOf(currentMark),baselineIndex=baseline.indexOf(baselineMark);
    const set=(selector,value)=>{const el=live.querySelector(selector);if(el)el.textContent=value};
    const currentText=currentMark?this.passageSnippet(currentMark):'No current occurrence is available.',baselineText=baselineMark?this.passageSnippet(baselineMark):'No directly comparable occurrence appears in this baseline paper.',baselinePaper=baselineMark?`BASELINE PAPER ${paper.paper} · ILLUSTRATIVE`:`BASELINE PAPER ${paper.paper} · NO COMPARABLE OCCURRENCE`;
    const trimEvidence=value=>{const clean=(value||'').replace(/\s+/g,' ').trim();return clean.length>34?`${clean.slice(0,32).replace(/\s+\S*$/,'')}…`:clean},currentExact=trimEvidence(currentMark?.textContent),baselineExact=trimEvidence(baselineMark?.textContent),evidenceExplanation=DIRECT_LOCALIZATION_KINDS.has(localizationKindFor(feature))?baselineMark?`“${currentExact}” is the current example. Compare it with “${baselineExact}” in baseline paper ${paper.paper}.`:`“${currentExact}” is the current example. This baseline paper has no directly comparable occurrence.`:baselineMark?`This ${location.noun} is a concrete place to inspect ${feature.plain}. Compare it with the paired passage in baseline paper ${paper.paper}.`:`This ${location.noun} is a concrete place to inspect ${feature.plain}. This baseline paper has no comparable passage.`;
    set('[data-hover-glyph]',feature.tier===0?'C':String(feature.tier).padStart(2,'0'));set('[data-hover-feature]',feature.professorLabel);set('[data-hover-state]',pinned?`SELECTED · ${location.label}`:automatic?location.label:`PREVIEW · ${location.label}`);set('[data-hover-current]',currentText);set('[data-hover-baseline]',baselineText);set('[data-hover-current-value]',currentIndex>=0?`EXAMPLE ${currentIndex+1}`:'NO EXAMPLE');set('[data-hover-baseline-value]',baselineIndex>=0?`MATCH ${baselineIndex+1}`:'NO MATCH');set('[data-hover-baseline-paper]',baselinePaper);set('[data-hover-explanation]',evidenceExplanation);
    const navigation=live.querySelector('[data-passage-navigation]'),previous=live.querySelector('[data-passage-prev]'),next=live.querySelector('[data-passage-next]'),position=Math.max(0,currentIndex)+1,total=current.length;if(navigation){navigation.hidden=!total;navigation.setAttribute('aria-label',`Navigate ${feature.professorLabel} examples, ${total} total`)}if(previous){previous.disabled=!total||position<=1;previous.setAttribute('aria-label',position<=1?'Previous example, unavailable':`Previous example, ${position-1} of ${total}`)}if(next){next.disabled=!total||position>=total;next.setAttribute('aria-label',position>=total?'Next example, unavailable':`Next example, ${position+1} of ${total}`)}set('[data-passage-position]',total?String(position):'0');set('[data-passage-total]',String(total));
    this.root.querySelectorAll('[data-traits][aria-current],[data-baseline-traits][aria-current]').forEach(element=>element.removeAttribute('aria-current'));mark?.setAttribute('aria-current','true');this.root.querySelector('[data-passage-inspector]')?.setAttribute('aria-label',`${feature.professorLabel} current and baseline evidence`);
    empty.hidden=true;live.hidden=false;const inspector=this.root.querySelector('.feature-inspector');inspector?.classList.add('is-previewing');inspector?.classList.toggle('has-pinned-passage',pinned);
  }
  hidePassagePreview(){
    const live=this.root.querySelector('[data-passage-live]'),empty=this.root.querySelector('[data-passage-empty]');if(!live||!empty)return;
    live.hidden=true;empty.hidden=false;this.root.querySelectorAll('[data-traits][aria-current],[data-baseline-traits][aria-current]').forEach(element=>element.removeAttribute('aria-current'));const inspector=this.root.querySelector('.feature-inspector');inspector?.classList.remove('is-previewing','has-pinned-passage');
  }
  filterFeatures(query){const q=query.trim().toLowerCase();this.root.querySelectorAll('[data-feature-select]').forEach(button=>button.hidden=!!q&&!button.textContent.toLowerCase().includes(q))}
  setTheme(theme,button){this.root.dataset.editorTheme=theme;EDITOR_STATE.theme=theme;this.root.querySelectorAll('[data-theme]').forEach(item=>item.classList.toggle('active',item===button));this.drawCorrelation(performance.now())}
  runEditorCommand(command,value){
    if(this.reviewOnly)return;
    const body=this.root.querySelector('[data-paper-body]');if(!body)return;body.focus({preventScroll:true});
    document.execCommand(command,false,value||null);this.documentChanged();this.updateEditorCommandState();
  }
  onEditorKeydown(event){
    if(this.reviewOnly)return;
    const mod=event.metaKey||event.ctrlKey;if(!mod)return;const key=event.key.toLowerCase();
    if(key==='b'||key==='i'){event.preventDefault();this.runEditorCommand(key==='b'?'bold':'italic');return}
    if(key==='z'){event.preventDefault();this.runEditorCommand(event.shiftKey?'redo':'undo')}
  }
  onWorkspaceKeydown(event){
    if(event.key==='Escape'&&this.previewPinned){this.previewPinned=null;this.previewMark=null;this.hidePassagePreview();return}
    if(!this.compare||event.defaultPrevented||event.target.closest?.('[contenteditable],input,textarea,select'))return;
    const viewport=this.root.querySelector('[data-comparison-viewport]');if(!viewport)return;
    if(event.key==='PageDown'||event.key==='PageUp'){event.preventDefault();const direction=event.key==='PageDown'?1:-1;viewport.scrollBy({top:direction*viewport.clientHeight*.82,left:0,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'})}
  }
  updateEditorCommandState(){
    if(this.reviewOnly){this.root.querySelectorAll('[data-editor-command]').forEach(button=>{button.disabled=true;button.setAttribute('aria-disabled','true');button.setAttribute('aria-pressed','false')});return}
    const body=this.root.querySelector('[data-paper-body]'),selection=getSelection(),inside=body&&selection?.anchorNode&&body.contains(selection.anchorNode);
    this.root.querySelectorAll('[data-editor-command]').forEach(button=>{
      const command=button.dataset.editorCommand,value=button.dataset.editorValue;
      if(command==='undo'||command==='redo'){button.disabled=!document.queryCommandEnabled(command);return}
      let pressed=false;if(inside){pressed=command==='formatBlock'?String(document.queryCommandValue('formatBlock')).toLowerCase().replace(/[<>]/g,'')===(value||''):document.queryCommandState(command)}button.setAttribute('aria-pressed',String(pressed));
    });
  }
  documentChanged(){
    if(this.reviewOnly){const status=this.root.querySelector('[data-save-state]');if(status)status.textContent=DEMO_STATUS;return}
    const body=this.root.querySelector('[data-paper-body]'),status=this.root.querySelector('[data-save-state]'),count=this.root.querySelector('[data-word-count]');
    const words=(body.innerText.trim().match(/\S+/g)||[]).length;count.textContent=`${words} words`;status.textContent='Illustrative analysis updating locally…';this.buildComparisonPairs();this.updateEditorCommandState();clearTimeout(this.saveTimer);this.saveTimer=setTimeout(()=>status.textContent=DEMO_STATUS,700);
  }
  showSelectionTools(){
    const selection=getSelection(),tools=this.root.querySelector('[data-selection-tools]'),body=this.root.querySelector('[data-paper-body]');if(!selection||selection.isCollapsed||!body.contains(selection.anchorNode)){tools.hidden=true;return}
    const rect=selection.getRangeAt(0).getBoundingClientRect(),viewport=this.root.querySelector('.paper-viewport'),v=viewport.getBoundingClientRect();tools.hidden=false;tools.style.left=`${rect.left+rect.width/2-v.left+viewport.scrollLeft}px`;tools.style.top=`${rect.top-v.top+viewport.scrollTop-7}px`;
  }
  selectionAction(message){const status=this.root.querySelector('[data-save-state]');status.textContent=message;this.root.querySelector('[data-selection-tools]').hidden=true;setTimeout(()=>status.textContent=DEMO_STATUS,1100)}
  resize(){if(!this.canvas||!this.ctx)return;const rect=this.canvas.getBoundingClientRect(),dpr=Math.min(devicePixelRatio||1,2);this.canvas.width=Math.max(1,Math.round(rect.width*dpr));this.canvas.height=Math.max(1,Math.round(rect.height*dpr));this.ctx.setTransform(dpr,0,0,dpr,0,0);this.cw=rect.width;this.ch=rect.height;if(!this.shouldAnimate())this.drawCorrelation(performance.now())}
  animate(now=performance.now()){if(!this.shouldAnimate()){this.frame=0;this.drawCorrelation(now);return}this.drawCorrelation(now);this.frame=requestAnimationFrame(time=>this.animate(time))}
  drawCorrelation(now){
    if(!this.ctx||!this.cw)return;const ctx=this.ctx,w=this.cw,h=this.ch,t=this.motionPreference.matches?0:(now-this.start)/1000,styles=getComputedStyle(this.root),accent=styles.getPropertyValue('--accent').trim()||'#7de0cb',muted=styles.getPropertyValue('--ed-muted').trim()||'#789498';ctx.clearRect(0,0,w,h);
    const ids=Object.keys(FEATURES),colorFor=id=>getComputedStyle(this.root.querySelector(`[data-feature-select="${id}"]`)).getPropertyValue('--feature-color').trim()||accent,selected=this.active==='all'?null:this.active,focus=this.hover||selected,targetZoom=selected?1:0,reduced=this.motionPreference.matches;
    this.correlationZoom=reduced?targetZoom:this.correlationZoom+(targetZoom-this.correlationZoom)*.075;
    const zoom=this.correlationZoom,relatedIds=selected?FEATURES[selected].related.map(entry=>entry[0]):[],center={x:w*.5,y:h*.43},nodes=ids.map((id,i)=>{const angle=-Math.PI/2+i*Math.PI*2/ids.length+t*.025,radius=Math.min(w*.34,h*.34),baseX=w/2+Math.cos(angle)*radius,baseY=h/2+Math.sin(angle)*radius*.78,relationIndex=relatedIds.indexOf(id),relationAngle=relationIndex===0?Math.PI*.1:Math.PI*.9,targetX=id===selected?center.x:relationIndex>=0?center.x+Math.cos(relationAngle)*w*.31:baseX,targetY=id===selected?center.y:relationIndex>=0?center.y+Math.sin(relationAngle)*h*.34:baseY;return{id,x:baseX+(targetX-baseX)*zoom,y:baseY+(targetY-baseY)*zoom,color:colorFor(id),isRelated:relationIndex>=0}});
    nodes.forEach((a,i)=>nodes.slice(i+1).forEach(b=>{const related=FEATURES[a.id].related.some(r=>r[0]===b.id);if(!related)return;const connected=a.id===focus||b.id===focus,selectedEdge=selected&&(a.id===selected||b.id===selected);ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.strokeStyle=connected?(a.id===focus?a.color:b.color):selectedEdge?colorFor(selected):muted;ctx.globalAlpha=connected?.58:selectedEdge?.42:.1*(1-zoom*.72);ctx.lineWidth=connected?1.2:selectedEdge?1:.5;ctx.stroke()}));ctx.globalAlpha=1;
    nodes.forEach(node=>{const active=node.id===focus||node.id===selected,pulse=active?1.8+Math.sin(t*2.4)*1.05:0,peripheral=selected&&node.id!==selected&&!node.isRelated,size=node.id===selected?6+zoom*3:node.isRelated?4.2:3;ctx.beginPath();ctx.arc(node.x,node.y,size+pulse,0,Math.PI*2);ctx.fillStyle=node.color;ctx.globalAlpha=peripheral?.16:active?.96:node.isRelated?.76:.48;ctx.fill();ctx.font=`${node.id===selected?7:6}px DM Mono`;ctx.textAlign='center';ctx.fillStyle=active||node.isRelated?node.color:muted;ctx.globalAlpha=peripheral?.18:active?.96:.7;ctx.fillText(FEATURES[node.id].glyph,node.x,node.y+size+9)});ctx.globalAlpha=1;
  }
  destroy(){const viewport=this.root.querySelector('[data-comparison-viewport]');if(viewport){EDITOR_STATE.scrollTop=viewport.scrollTop;EDITOR_STATE.scrollLeft=viewport.scrollLeft}EDITOR_STATE.compare=this.compare;cancelAnimationFrame(this.frame);cancelAnimationFrame(this.pointerFrame);clearTimeout(this.saveTimer);clearTimeout(this.busyTimer);clearTimeout(this.previewShowTimer);clearTimeout(this.previewHideTimer);clearTimeout(this.cameraTimer);this.abort.abort();this.observer?.disconnect();this.canvasObserver?.disconnect()}
}

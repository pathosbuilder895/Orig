import { FEATURE_BY_CODE, TIER_BY_ID } from './feature-universe-data.js?v=professor-solar-final4';

const FEATURES = {
  punctuation:{index:'FEATURE 07 / 97',glyph:';',title:'Punctuation usage',state:'MEANINGFUL SHIFT',copy:'Semicolons and em dashes appear at nearly twice Morgan’s established rate, concentrating in the argument’s most abstract passages.',current:'18.4',baseline:'8.6—12.9',delta:'+2.1σ above baseline',behavior:'This boundary carries more rhetorical weight than Morgan’s usual punctuation. It slows the clause transition where the baseline typically resolves with a lighter stop.',why:'Punctuation is a low-level motor habit. A clustered change is useful context, but it is not independent evidence of authorship.',related:[['syntax','Sentence architecture','shared clause-boundary behavior','72%'],['cadence','Cadence & pacing','sentence-ending rhythm','58%']],strength:'r = 0.72',density:[10,12,9,13,11,12,10,14,11,12,13,18]},
  syntax:{index:'FEATURE 14 / 97',glyph:'¶',title:'Sentence architecture',state:'MODERATE SHIFT',copy:'Clause depth rises in six passages, with subordinate structures clustering around the central theological claim.',current:'2.38',baseline:'1.42—1.91',delta:'+1.7σ above baseline',behavior:'This passage nests more dependent clauses before resolving its main claim. The paired baseline passage reaches its conclusion through a shallower structure.',why:'Sentence construction reflects planning habits and working-memory rhythm. Interpret it alongside genre, revision history, and source use.',related:[['punctuation','Punctuation usage','shared clause boundaries','72%'],['cadence','Cadence & pacing','long-short sentence sequences','64%']],strength:'r = 0.72',density:[1.5,1.7,1.4,1.8,1.6,1.9,1.5,1.7,1.8,1.6,1.9,2.38]},
  cadence:{index:'FEATURE 22 / 97',glyph:'∿',title:'Cadence & pacing',state:'WATCH',copy:'Three short emphatic sentences interrupt otherwise extended prose, producing a rhythm uncommon in the baseline.',current:'0.71',baseline:'0.44—0.62',delta:'+1.2σ above baseline',behavior:'The highlighted sequence changes the document’s long–short rhythm. Its emphasis arrives more abruptly than in comparable baseline prose.',why:'Cadence captures the alternation of sentence lengths and stresses. It can change naturally with rhetorical purpose and should remain contextual.',related:[['syntax','Sentence architecture','sentence-length sequencing','64%'],['punctuation','Punctuation usage','terminal-mark rhythm','58%']],strength:'r = 0.64',density:[.45,.52,.48,.56,.49,.58,.53,.47,.61,.55,.57,.71]},
  lexical:{index:'FEATURE 31 / 97',glyph:'Aa',title:'Lexical texture',state:'ALIGNED',copy:'Topic vocabulary and preferred abstractions remain consistent with Morgan’s prior theology writing.',current:'0.86',baseline:'0.78—0.91',delta:'inside expected range',behavior:'The vocabulary and abstraction level remain close to Morgan’s established theological register. This is a continuity signal, not a deviation.',why:'Lexical texture measures patterns of word choice, not subject knowledge. Strong continuity can contextualize changes found elsewhere.',related:[['citation','Citation behavior','source-linked vocabulary','41%'],['transition','Discourse transitions','argument vocabulary','36%']],strength:'r = 0.41',density:[.81,.84,.79,.88,.85,.82,.87,.83,.89,.84,.86,.86]},
  citation:{index:'FEATURE 48 / 97',glyph:'“”',title:'Citation behavior',state:'MEANINGFUL SHIFT',copy:'Three sources enter through impersonal claims rather than Morgan’s usual author-led attribution pattern.',current:'3',baseline:'0—1',delta:'+1.9σ above baseline',behavior:'This source enters through an impersonal authority claim. Morgan’s baseline more often names the author before presenting the proposition.',why:'Citation transitions can reveal changes in research process or genre convention. Source verification remains a separate instructor judgment.',related:[['transition','Discourse transitions','source-entry phrasing','69%'],['lexical','Lexical texture','source-linked vocabulary','41%']],strength:'r = 0.69',density:[1,0,1,1,0,1,1,0,1,1,0,3]},
  transition:{index:'FEATURE 53 / 97',glyph:'↝',title:'Discourse transitions',state:'LOW VARIANCE',copy:'Connective phrases are slightly less varied than usual, though their placement remains consistent with the baseline.',current:'0.63',baseline:'0.66—0.82',delta:'−0.8σ below baseline',behavior:'This connective explicitly redirects the argument. The baseline uses a wider set of transition forms for the same structural move.',why:'Transitions expose how an argument is assembled. Lower variety alone is weak evidence and often reflects assignment structure.',related:[['citation','Citation behavior','source-entry phrasing','69%'],['syntax','Sentence architecture','argument segmentation','47%']],strength:'r = 0.69',density:[.72,.68,.77,.73,.69,.81,.74,.76,.7,.79,.71,.63]}
};

const GUIDE_LENS_BY_TIER = {
  0:'lexical',1:'lexical',2:'transition',3:'citation',4:'punctuation',5:'syntax',6:'lexical',7:'cadence',8:'cadence',9:'transition',10:'transition',11:'punctuation',12:'transition',13:'cadence',14:'punctuation',15:'lexical',16:'citation',17:'cadence'
};
const guideLensFor = feature => GUIDE_LENS_BY_TIER[feature?.tier] || 'lexical';
const DIVISION_BY_TIER = {0:'surface',1:'surface',2:'discourse',3:'rhetoric',4:'surface',5:'surface',6:'surface',7:'surface',8:'surface',9:'discourse',10:'discourse',11:'surface',12:'discourse',13:'surface',14:'surface',15:'surface',16:'rhetoric',17:'surface'};

const LABELS = Object.fromEntries(Object.entries(FEATURES).map(([id,f])=>[id,f.title]));
const DEMO_STATUS = 'Illustrative analysis · no records saved';
const FEATURE_POSITIONS = {
  punctuation:{band:[35,58],current:88,unit:'PER 1,000 WORDS',badge:'+2.1σ',caption:'Current usage sits above Morgan’s expected range.',state:'outside'},
  syntax:{band:[32,57],current:82,unit:'CLAUSE DEPTH RATIO',badge:'+1.7σ',caption:'Current clause depth sits above the established corridor.',state:'outside'},
  cadence:{band:[38,64],current:77,unit:'RHYTHM INDEX',badge:'+1.2σ',caption:'Pacing is elevated, but remains near the expected boundary.',state:'watch'},
  lexical:{band:[34,75],current:61,unit:'CONTINUITY INDEX',badge:'ALIGNED',caption:'Lexical texture remains inside Morgan’s expected range.',state:'aligned'},
  citation:{band:[12,37],current:83,unit:'TRANSITIONS',badge:'+1.9σ',caption:'Source-entry behavior sits beyond the established range.',state:'outside'},
  transition:{band:[43,77],current:35,unit:'VARIETY INDEX',badge:'−0.8σ',caption:'Transition variety is slightly below the expected range.',state:'watch'}
};

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
    this.root=root;this.active=EDITOR_STATE.active;this.hover=null;this.previewMark=null;this.previewPinned=null;this.evidenceScope='family';this.reviewOnly=true;this.correlationZoom=0;this.compare=false;this.baselineIndex=EDITOR_STATE.baselineIndex;this.differenceIndex=EDITOR_STATE.differenceIndex;this.comparisonPairs=[];this.catalogDivision='surface';this.catalogQuery='';this.catalogFeature='semicolon_colon_rate';this.abort=new AbortController();this.frame=0;this.start=performance.now();
    this.canvas=root.querySelector('[data-correlation-canvas]');this.ctx=this.canvas?.getContext('2d');
    this.root.dataset.editorTheme=EDITOR_STATE.theme;
    const initialCatalogFeature=this.catalogFeature;this.configureReviewMode();this.renderBaseline();this.bind();this.filterCatalog();this.setFeature(this.active);this.selectCatalogFeature(initialCatalogFeature,{applyLens:false});this.resize();if(this.canvas)this.animate();
    this.root.querySelectorAll('[data-theme]').forEach(button=>button.classList.toggle('active',button.dataset.theme===EDITOR_STATE.theme));
    if(EDITOR_STATE.compare)requestAnimationFrame(()=>this.toggleCompare(true,true));
    this.observer=new ResizeObserver(()=>this.resize());if(this.canvas)this.observer.observe(this.canvas);
  }
  bind(){
    const opts={signal:this.abort.signal};
    this.root.addEventListener('pointermove',event=>this.trackGlassLight(event),opts);
    this.root.addEventListener('pointerleave',()=>{this.root.style.setProperty('--glass-x','50%');this.root.style.setProperty('--glass-y','8%');this.root.style.setProperty('--scene-x','0px');this.root.style.setProperty('--scene-y','0px')},opts);
    this.root.querySelector('[data-feature-all]')?.addEventListener('click',()=>this.showAllFeatureOverlays(),opts);
    this.root.querySelector('[data-catalog-search]')?.addEventListener('input',event=>{this.catalogQuery=event.target.value;this.filterCatalog()},opts);
    this.root.querySelectorAll('[data-catalog-division-select]').forEach(button=>button.addEventListener('click',()=>this.selectCatalogDivision(button.dataset.catalogDivisionSelect),opts));
    this.root.querySelector('[data-feature-catalog]')?.addEventListener('click',event=>{const button=event.target.closest('[data-catalog-feature]');if(button)this.selectCatalogFeature(button.dataset.catalogFeature)},opts);
    this.root.querySelectorAll('[data-correlate]').forEach(button=>button.addEventListener('click',()=>{const code=button.dataset.catalogRelated;if(code)this.selectCatalogFeature(code);else this.setFeature(button.dataset.correlate)},opts));
    this.root.querySelectorAll('[data-theme]').forEach(button=>button.addEventListener('click',()=>this.setTheme(button.dataset.theme,button),opts));
    this.root.querySelector('[data-document-compare]')?.addEventListener('click',()=>this.toggleCompare(),opts);
    this.root.querySelectorAll('[data-baseline-prev]').forEach(button=>button.addEventListener('click',()=>this.changeBaseline(-1),opts));
    this.root.querySelectorAll('[data-baseline-next]').forEach(button=>button.addEventListener('click',()=>this.changeBaseline(1),opts));
    this.root.querySelector('[data-difference-prev]')?.addEventListener('click',()=>this.stepDifference(-1),opts);
    this.root.querySelector('[data-difference-next]')?.addEventListener('click',()=>this.stepDifference(1),opts);
    this.root.querySelectorAll('[data-pan-paper]').forEach(button=>button.addEventListener('click',()=>this.panToPaper(button.dataset.panPaper),opts));
    this.root.querySelectorAll('[data-editor-command]').forEach(button=>button.addEventListener('click',()=>this.runEditorCommand(button.dataset.editorCommand,button.dataset.editorValue),opts));
    this.root.querySelector('[data-baseline-body]')?.addEventListener('click',event=>{const mark=event.target.closest('[data-baseline-feature]');if(!mark)return;const ids=mark.dataset.baselineFeature.split(' ');this.selectPassageFamily(ids.includes(this.active)?this.active:ids[0],mark)},opts);
    this.root.querySelectorAll('.paper-body [data-feature]').forEach(mark=>{
      mark.classList.add('analysis-mark');
      mark.addEventListener('click',event=>{event.stopPropagation();const ids=mark.dataset.feature.split(' '),id=ids.includes(this.active)?this.active:ids[0];this.selectPassageFamily(id,mark)},opts);
    });
    const body=this.root.querySelector('[data-paper-body]');
    body?.addEventListener('pointerover',event=>this.onPassagePointerOver(event),opts);
    body?.addEventListener('pointerout',event=>this.onPassagePointerOut(event),opts);
    body?.addEventListener('input',()=>this.documentChanged(),opts);
    body?.addEventListener('mouseup',()=>this.showSelectionTools(),opts);
    body?.addEventListener('keyup',()=>this.showSelectionTools(),opts);
    body?.addEventListener('keydown',event=>this.onEditorKeydown(event),opts);
    document.addEventListener('selectionchange',()=>this.updateEditorCommandState(),opts);
    document.addEventListener('keydown',event=>this.onWorkspaceKeydown(event),opts);
    this.root.querySelector('[data-comparison-viewport]')?.addEventListener('scroll',()=>this.updatePanState(),{signal:this.abort.signal,passive:true});
    this.root.querySelector('[data-add-note]')?.addEventListener('mousedown',event=>{event.preventDefault();this.selectionAction('Note previewed for this demo · not saved')},opts);
    this.root.querySelector('[data-explain-selection]')?.addEventListener('mousedown',event=>{event.preventDefault();this.selectionAction('Explanation previewed · not saved')},opts);
    this.root.querySelector('[data-pin-evidence]')?.addEventListener('click',event=>{event.currentTarget.classList.toggle('pinned');event.currentTarget.textContent=event.currentTarget.classList.contains('pinned')?'◆ Added for this demo session':'◇ Add to demo review';const status=this.root.querySelector('[data-save-state]');if(status)status.textContent=DEMO_STATUS},opts);
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
    const pin=this.root.querySelector('[data-pin-evidence]');if(pin)pin.textContent='◇ Add to demo review';
    const note=this.root.querySelector('[data-add-note]');if(note){note.hidden=true;note.setAttribute('aria-hidden','true')}
    this.root.querySelectorAll('.paper-body [data-feature]:not(mark)').forEach(mark=>{const names=mark.dataset.feature.split(' ').map(id=>LABELS[id]).filter(Boolean).join(' and ');mark.tabIndex=0;mark.setAttribute('role','button');mark.setAttribute('aria-label',`Inspect ${names} passage-family context`);mark.addEventListener('keydown',event=>{if(event.key!=='Enter'&&event.key!==' ')return;event.preventDefault();mark.click()},{signal:this.abort.signal})});
  }
  filterCatalog(){
    const query=this.catalogQuery.trim().toLowerCase(),division=this.catalogDivision;let visible=0;
    this.root.querySelectorAll('[data-catalog-tier-section]').forEach(section=>{
      let tierVisible=0;section.querySelectorAll('[data-catalog-feature]').forEach(button=>{const matchesDivision=button.dataset.catalogDivision===division,matchesQuery=!query||button.textContent.toLowerCase().includes(query),show=matchesDivision&&matchesQuery;button.hidden=!show;if(show){visible+=1;tierVisible+=1}});section.hidden=!tierVisible;
    });
    const count=this.root.querySelector('[data-catalog-count]');if(count)count.textContent=`${visible} ${visible===1?'feature':'features'}`;
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
    if(!selectFirst)return;const selected=this.root.querySelector('.catalog-feature.selected');if(selected?.dataset.catalogDivision===division){this.scrollCatalogItem(selected,matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth');return}const first=this.root.querySelector(`.catalog-feature[data-catalog-division="${division}"]:not([hidden])`);if(first)this.selectCatalogFeature(first.dataset.catalogFeature);
  }
  showAllFeatureOverlays(){
    this.previewPinned=null;this.previewMark=null;this.hidePassagePreview();this.catalogFeature=null;this.root.dataset.selectedCatalogFeature='all';this.root.querySelectorAll('[data-catalog-feature]').forEach(button=>{button.classList.remove('selected');button.setAttribute('aria-pressed','false')});
    const label=this.root.querySelector('[data-catalog-lens-label]');if(label)label.textContent='Overview · all six passage families';this.setFeature('all',{scope:'overview'});
  }
  selectCatalogFeature(code,{applyLens=true}={}){
    const feature=FEATURE_BY_CODE[code];if(!feature)return;const lens=guideLensFor(feature);this.catalogFeature=code;this.root.dataset.selectedCatalogFeature=code;
    this.previewPinned=null;this.hidePassagePreview();this.setEvidenceScope('exact');
    this.root.querySelectorAll('[data-catalog-feature]').forEach(button=>{const selected=button.dataset.catalogFeature===code;button.classList.toggle('selected',selected);button.setAttribute('aria-pressed',String(selected))});
    if(applyLens)this.setFeature(lens,{scope:'exact'});const label=this.root.querySelector('[data-catalog-lens-label]');if(label)label.textContent=`Exact feature · ${feature.professorLabel||feature.shortLabel||feature.name}`;this.updateCatalogInspector(feature,lens);
    const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches,behavior=!applyLens||reduced?'auto':'smooth',selected=this.root.querySelector(`[data-catalog-feature="${code}"]`),section=selected?.closest('[data-catalog-tier-section]');if(selected&&(selected.hidden||section?.hidden)){this.catalogQuery='';this.catalogDivision=selected.dataset.catalogDivision||DIVISION_BY_TIER[feature.tier]||'surface';const search=this.root.querySelector('[data-catalog-search]');if(search)search.value='';this.root.querySelectorAll('[data-catalog-division-select]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.catalogDivisionSelect===this.catalogDivision)));this.filterCatalog()}this.scrollCatalogItem(selected,behavior);this.root.querySelector('.feature-inspector')?.scrollTo({top:0,behavior});
  }
  setEvidenceScope(scope){
    this.evidenceScope=scope;this.root.dataset.evidenceScope=scope;
  }
  clearCatalogSelection(familyId){
    this.catalogFeature=null;this.root.dataset.selectedCatalogFeature=familyId==='all'?'all':'';this.root.querySelectorAll('[data-catalog-feature]').forEach(button=>{button.classList.remove('selected');button.setAttribute('aria-pressed','false')});
    const label=this.root.querySelector('[data-catalog-lens-label]');if(label)label.textContent=familyId==='all'?'Overview · all passage families':`Passage family · ${FEATURES[familyId]?.title||'context'}`;
  }
  selectPassageFamily(id,mark){
    this.previewPinned=mark||null;this.clearCatalogSelection(id);this.setFeature(id,{scope:'family',preservePreview:true});clearTimeout(this.previewShowTimer);clearTimeout(this.previewHideTimer);this.previewMark=mark||null;if(mark)this.showPassagePreview(mark,id,{pinned:true});
    const passage=this.root.querySelector('[data-passage-inspector]');if(passage&&mark?.matches?.(':focus-visible'))passage.scrollIntoView({block:'nearest',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
  }
  updateCatalogInspector(feature,lens){
    const tier=TIER_BY_ID[feature.tier],captured=feature.tier!==17,set=(selector,value)=>{const el=this.root.querySelector(selector);if(el)el.textContent=value};
    const professorTitle=feature.professorLabel||feature.shortLabel||feature.name,technicalNote=professorTitle===feature.name?'':` Technical measure: ${feature.name}.`;
    const statusOverrides={semicolon_colon_rate:'review',clause_depth_mean:'review',source_integration_style:'review',pause_density:'aligned',revision_depth:'aligned',char_trigram_profile_divergence:'aligned'},effectiveStatus=statusOverrides[feature.code]||feature.status,numeric=captured?(feature.current.match(/-?\d+(?:\.\d+)?/)?.[0]||'—'):'—',status=feature.tier===17?'CAPTURE READY':feature.tier===0?'COMPARISON ONLY':effectiveStatus.toUpperCase(),isReview=effectiveStatus==='review',isAligned=effectiveStatus==='aligned',position=feature.tier===17?{band:[36,64],current:50,state:'overview',badge:'NOT CAPTURED',caption:'This signal becomes available during a live writing session.'}:isReview?{band:[28,61],current:87,state:'outside',badge:'OUTSIDE RANGE',caption:'The current signal sits beyond Morgan’s established range.'}:isAligned?{band:[27,74],current:54,state:'aligned',badge:'ALIGNED',caption:'The current signal sits inside Morgan’s established range.'}:{band:[33,69],current:73,state:'watch',badge:'WATCH',caption:'The current signal is near the edge of Morgan’s expected range.'};
    const reading=feature.tier===17?`${professorTitle} means ${feature.plain}. It becomes available when a live writing session supplies keystroke evidence.${technicalNote}`:`${professorTitle} means ${feature.plain}. ${feature.reading}${technicalNote}`;
    const range=feature.baseline.match(/-?\d+(?:\.\d+)?\s*[–—-]\s*-?\d+(?:\.\d+)?/)?.[0],percent=feature.baseline.match(/\d+(?:\.\d+)?%/)?.[0],compactBaseline=captured?(range||percent||'12-paper range'):'Not available',unitByCode={semicolon_colon_rate:'MARKS / 1K',clause_depth_mean:'CLAUSE DEPTH',source_integration_style:'SOURCE HANDOFFS'};
    set('[data-inspector-index]',`EXACT FEATURE · ${feature.tier===0?'COMPARISON':`TIER ${String(feature.tier).padStart(2,'0')}`} · ${String(feature.index+1).padStart(3,'0')} / 103`);set('[data-inspector-glyph]',feature.tier===0?'CMP':String(feature.tier).padStart(2,'0'));set('[data-inspector-state]',status);set('[data-inspector-title]',professorTitle);set('[data-inspector-copy]',reading);set('[data-current-value]',numeric);set('[data-current-unit]',captured?(unitByCode[feature.code]||'CURRENT SIGNAL'):'LIVE SESSION');set('[data-baseline-value]',compactBaseline);set('[data-delta-value]',captured?effectiveStatus:'requires captured keystrokes');set('[data-deviation-badge]',position.badge);set('[data-position-caption]',position.caption);set('[data-inspector-why]',`${professorTitle} means ${feature.plain}.${technicalNote} Colored text shows the broader ${FEATURES[lens].title.toLowerCase()} passage family for context, not an exact token-level attribution. This observation never acts as a standalone authorship verdict.`);set('[data-correlation-strength]',`${tier.name.toUpperCase()} · TIER ${feature.tier}`);
    const comparison=this.root.querySelector('.comparison-orbit'),scale=this.root.querySelector('[data-deviation-scale]');if(comparison)comparison.dataset.positionState=position.state;if(scale){scale.style.setProperty('--band-start',`${position.band[0]}%`);scale.style.setProperty('--band-end',`${position.band[1]}%`);scale.style.setProperty('--current-position',`${position.current}%`);scale.setAttribute('aria-label',position.caption)}
    let siblings=tier.features.map(code=>FEATURE_BY_CODE[code]).filter(item=>item&&item.code!==feature.code);if(siblings.length<2)siblings=Object.values(FEATURE_BY_CODE).filter(item=>item.code!==feature.code&&item.system===feature.system);const nextIndex=siblings.findIndex(item=>item.index>feature.index),start=nextIndex<0?0:nextIndex,related=[siblings[start%siblings.length],siblings[(start+1)%siblings.length]].filter(Boolean),buttons=[...this.root.querySelectorAll('[data-correlate]')];buttons.forEach((button,index)=>{const item=related[index];if(!item){button.hidden=true;return}button.hidden=false;button.dataset.catalogRelated=item.code;button.dataset.correlate=guideLensFor(item);button.querySelector('b').textContent=item.professorLabel||item.shortLabel||item.name;button.querySelector('small').textContent=`${item.plain} · Technical: ${item.name}`;button.querySelector('em').textContent=`T${String(item.tier).padStart(2,'0')}`});
    const seed=feature.index+feature.tier*7,values=Array.from({length:12},(_,index)=>.28+(((seed*17+index*29+index*index*3)%57)/100));this.updateDensity(values);
    const baselineCompact=feature.baseline.match(/\d+(?:\.\d+)?\s*[–—-]\s*\d+(?:\.\d+)?/)?.[0]||'12-paper profile';
    set('[data-ribbon-glyph]',feature.tier===0?'CMP':String(feature.tier).padStart(2,'0'));set('[data-ribbon-title]',professorTitle);set('[data-ribbon-current]',captured?numeric:'Not captured');set('[data-ribbon-baseline]',baselineCompact);set('[data-ribbon-delta]',status);
    const matches=this.contextualPassages('.analysis-mark.feature-active').length,baselineMatches=this.contextualPassages('.baseline-feature-active').length;set('[data-active-overlay]',`EXACT FEATURE · ${professorTitle.toUpperCase()} · ${matches} CONTEXT PASSAGES`);set('[data-baseline-lens]',`CONTEXT FAMILY · ${baselineMatches} BASELINE PASSAGES`);
    const inspector=this.root.querySelector('.feature-inspector');if(inspector)inspector.style.setProperty('--feature-accent',feature.color);
  }
  trackGlassLight(event){
    if(matchMedia('(prefers-reduced-motion: reduce)').matches)return;
    const rect=this.root.getBoundingClientRect();
    const x=Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),y=Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height));
    this.root.style.setProperty('--glass-x',`${(x*100).toFixed(1)}%`);
    this.root.style.setProperty('--glass-y',`${(y*100).toFixed(1)}%`);
    this.root.style.setProperty('--scene-x',`${((.5-x)*8).toFixed(2)}px`);
    this.root.style.setProperty('--scene-y',`${((.5-y)*5).toFixed(2)}px`);
  }
  contextualPassages(selector){
    return [...new Set([...this.root.querySelectorAll(selector)].map(mark=>mark.closest('p,blockquote')||mark))];
  }
  setFeature(id,{scope='family',preservePreview=false}={}){
    this.active=id;
    if(!preservePreview){this.previewPinned=null;this.previewMark=null;this.hidePassagePreview()}
    this.setEvidenceScope(id==='all'?'overview':scope);
    if(scope!=='exact')this.clearCatalogSelection(id);
    EDITOR_STATE.active=id;
    this.root.dataset.activeFeature=id;
    this.root.querySelectorAll('[data-feature-select]').forEach(button=>{const on=id==='all'||button.dataset.featureSelect===id;button.classList.toggle('active',on);button.setAttribute('aria-pressed',String(on))});
    const marks=[...this.root.querySelectorAll('.analysis-mark')];
    marks.forEach(mark=>mark.classList.toggle('feature-active',id==='all'||mark.dataset.feature.split(' ').includes(id)));
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
    viewport?.setAttribute('aria-label',this.compare?'Scrollable current and baseline paper comparison':'Scrollable current paper');
    const status=this.root.querySelector('[data-save-state]');if(status)status.textContent=DEMO_STATUS;
    requestAnimationFrame(()=>{
      if(viewport){const left=restore?EDITOR_STATE.scrollLeft:0,top=restore?EDITOR_STATE.scrollTop:viewport.scrollTop;viewport.scrollTo({left,top,behavior:'auto'})}
      this.updateDifferenceSelection(false);this.updateDifferenceRail([...this.root.querySelectorAll('.analysis-mark.feature-active')]);this.updatePanState();this.resize();
    });
  }
  changeBaseline(direction){
    this.baselineIndex=(this.baselineIndex+direction+BASELINES.length)%BASELINES.length;
    EDITOR_STATE.baselineIndex=this.baselineIndex;
    this.renderBaseline();
    const status=this.root.querySelector('[data-save-state]');if(status)status.textContent=DEMO_STATUS;
  }
  renderBaseline(){
    const paper=BASELINES[this.baselineIndex],set=(selector,value)=>{const el=this.root.querySelector(selector);if(el)el.textContent=value};
    const counter=`PAPER ${paper.paper} OF ${String(BASELINES.length).padStart(2,'0')}`,ribbon=this.root.querySelector('[data-comparison-ribbon]'),switchButtons=[...this.root.querySelectorAll('[data-baseline-prev],[data-baseline-next]')];
    ribbon?.setAttribute('aria-busy','true');switchButtons.forEach(button=>button.disabled=true);
    set('[data-baseline-code]',paper.code);set('[data-baseline-page]',paper.page);set('[data-baseline-course]',paper.course);set('[data-baseline-title]',paper.title);set('[data-baseline-meta]',paper.meta);set('[data-baseline-date]',paper.date);set('[data-baseline-counter]',counter);set('[data-baseline-counter-secondary]',counter);
    const body=this.root.querySelector('[data-baseline-body]');if(body)body.innerHTML=paper.body;
    const article=this.root.querySelector('.baseline-paper');if(article){article.classList.remove('baseline-paper-swap');void article.offsetWidth;article.classList.add('baseline-paper-swap')}
    this.syncBaselineHighlights();this.buildComparisonPairs();
    clearTimeout(this.busyTimer);this.busyTimer=setTimeout(()=>{ribbon?.setAttribute('aria-busy','false');switchButtons.forEach(button=>button.disabled=false)},220);
  }
  syncBaselineHighlights(){
    const marks=[...this.root.querySelectorAll('[data-baseline-feature]')];
    marks.forEach(mark=>mark.classList.toggle('baseline-feature-active',this.active==='all'||mark.dataset.baselineFeature.split(' ').includes(this.active)));
    const count=marks.filter(mark=>mark.classList.contains('baseline-feature-active')).length,label=this.root.querySelector('[data-baseline-lens]');
    if(label)label.textContent=this.active==='all'?`ALL LENSES · ${count} BASELINE PASSAGES`:`${FEATURES[this.active]?.title.toUpperCase()||'FEATURE'} LENS · ${count} BASELINE MATCHES`;
  }
  updateComparisonRibbon(id,aggregate){
    const f=FEATURES[id],set=(selector,value)=>{const el=this.root.querySelector(selector);if(el)el.textContent=value};
    const family=!aggregate&&this.evidenceScope==='family';set('[data-ribbon-glyph]',aggregate?'∞':f.glyph);set('[data-ribbon-title]',aggregate?'All passage families':family?`${f.title} passages`:f.title);set('[data-ribbon-current]',aggregate?'6 families':family?'Context':f.current);set('[data-ribbon-baseline]',aggregate?'12-paper profile':family?'Prior passage':f.baseline);set('[data-ribbon-delta]',aggregate?'Context overview':family?'Choose an exact feature for a measured range':f.delta);
  }
  buildComparisonPairs(){
    this.root.querySelectorAll('.comparison-target').forEach(el=>{el.classList.remove('comparison-target','comparison-target-selected');el.removeAttribute('data-pair-label')});
    const collect=(selector,key)=>{
      const seen=new Set(),matches=[];
      this.root.querySelectorAll(selector).forEach(el=>{
        const ids=el.dataset[key]?.split(' ')||[];if(this.active!=='all'&&!ids.includes(this.active))return;
        let target=(this.active==='all'||el.tagName==='MARK')?el.closest('p,blockquote'):el;if(!target||seen.has(target))return;seen.add(target);matches.push(target);
      });
      return matches;
    };
    const current=collect('.analysis-mark','feature'),baseline=collect('[data-baseline-feature]','baselineFeature'),length=Math.max(current.length,baseline.length);
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
      const viewport=this.root.querySelector('[data-comparison-viewport]'),v=viewport.getBoundingClientRect(),tops=[pair.current,pair.baseline].filter(Boolean).map(el=>el.getBoundingClientRect().top-v.top+viewport.scrollTop),target=tops.reduce((a,b)=>a+b,0)/tops.length;
      viewport.scrollTo({top:Math.max(0,target-150),left:viewport.scrollLeft,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
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
    const position={band:[28,72],current:50,unit:aggregate?'PASSAGE FAMILIES':'CONTEXT ONLY',badge:aggregate?'OVERVIEW':'PASSAGE FAMILY',caption:'Select an exact feature in the left rail to see a measured value and established range.',state:'overview'};
    set('[data-inspector-index]',aggregate?'PASSAGE OVERVIEW · 6 CONTEXT FAMILIES':`PASSAGE FAMILY · ${f.index}`);set('[data-inspector-glyph]',aggregate?'∞':f.glyph);set('[data-inspector-state]',aggregate?'CONTEXT VIEW':'CONTEXT · NOT AN EXACT MEASURE');set('[data-inspector-title]',aggregate?'Writing-pattern context':`${f.title} passages`);set('[data-inspector-copy]',aggregate?'Every colored passage family is visible at once. Choose an exact feature in the left rail when you need a specific measurement and baseline position.':`${f.copy} This family highlight provides passage-level context; it is not an exact 103-feature result.`);set('[data-current-value]',aggregate?'6':'—');set('[data-current-unit]',position.unit);set('[data-baseline-value]',aggregate?'12 papers':'Choose a feature');set('[data-delta-value]','Exact values appear after a feature is selected');set('[data-deviation-badge]',position.badge);set('[data-position-caption]',position.caption);set('[data-inspector-why]',aggregate?'Related passage families help organize a review; they do not turn several observations into independent proof.':`${f.why} The colored passage is a broader context region, not an exact token-level attribution.`);set('[data-correlation-strength]',aggregate?'RELATIONSHIP MAP':f.strength);
    const comparison=this.root.querySelector('.comparison-orbit'),scale=this.root.querySelector('[data-deviation-scale]');
    comparison.dataset.positionState=position.state;scale.style.setProperty('--band-start',`${position.band[0]}%`);scale.style.setProperty('--band-end',`${position.band[1]}%`);scale.style.setProperty('--current-position',`${position.current}%`);scale.setAttribute('aria-label',position.caption);
    const related=aggregate?FEATURES.punctuation.related:f.related;
    const buttons=[...this.root.querySelectorAll('[data-correlate]')];related.forEach((entry,index)=>{const button=buttons[index];if(!button)return;delete button.dataset.catalogRelated;button.dataset.correlate=entry[0];button.querySelector('b').textContent=entry[1];button.querySelector('small').textContent=entry[2];button.querySelector('em').textContent=entry[3]});
    this.updateDensity(aggregate?[.3,.46,.38,.61,.45,.66,.51,.72,.58,.74,.69,.86]:f.density);
  }
  updateDensity(values){
    const svg=this.root.querySelector('[data-density-svg]');if(!svg)return;
    const min=Math.min(...values),max=Math.max(...values),span=max-min||1;
    const points=values.map((v,i)=>[i*280/(values.length-1),72-(v-min)/span*61]);
    const line=points.map(([x,y],i)=>`${i?'L':'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
    svg.querySelector('.density-line').setAttribute('d',line);svg.querySelector('.density-area').setAttribute('d',`${line} L280 82 L0 82Z`);
    const [x,y]=points.at(-1);const guide=svg.querySelector('line'),dot=svg.querySelector('circle');guide.setAttribute('x1',x);guide.setAttribute('x2',x);dot.setAttribute('cx',x);dot.setAttribute('cy',y);
  }
  updateDifferenceRail(marks){
    const rail=this.root.querySelector('[data-difference-rail]');if(!rail)return;rail.innerHTML='';
    const paper=this.root.querySelector('.paper'),top=paper.getBoundingClientRect().top,height=Math.max(1,paper.getBoundingClientRect().height);
    [...new Set(marks.map(mark=>Math.max(1,Math.min(98,(mark.getBoundingClientRect().top-top)/height*100)).toFixed(1)))].forEach(position=>{const tick=document.createElement('i');tick.style.top=`${position}%`;rail.append(tick)});
  }
  onPassagePointerOver(event){
    const mark=event.target.closest?.('.analysis-mark.feature-active');if(!mark||!this.root.querySelector('[data-paper-body]')?.contains(mark))return;
    if(this.previewPinned)return;
    clearTimeout(this.previewHideTimer);if(mark===this.previewMark)return;
    clearTimeout(this.previewShowTimer);this.previewMark=mark;
    const ids=mark.dataset.feature.split(' '),id=ids.includes(this.active)?this.active:ids[0];
    this.previewShowTimer=setTimeout(()=>{if(this.previewMark===mark&&mark.classList.contains('feature-active'))this.showPassagePreview(mark,id)},85);
  }
  onPassagePointerOut(event){
    if(this.previewPinned)return;
    const mark=event.target.closest?.('.analysis-mark.feature-active');if(!mark)return;
    const next=event.relatedTarget?.closest?.('.analysis-mark.feature-active');if(next){clearTimeout(this.previewHideTimer);return}
    clearTimeout(this.previewShowTimer);this.previewMark=null;clearTimeout(this.previewHideTimer);this.previewHideTimer=setTimeout(()=>this.hidePassagePreview(),420);
  }
  passageSnippet(element,max=112){
    if(!element)return 'No directly comparable passage in this baseline paper.';
    const source=element.tagName==='MARK'?(element.closest('span[data-feature],span[data-baseline-feature]')||element.closest('p,blockquote')):element;
    const text=(source?.textContent||element.textContent||'').replace(/\s+/g,' ').trim();if(text.length<=max)return text;
    return `${text.slice(0,max).replace(/\s+\S*$/,'')}…`;
  }
  showPassagePreview(mark,id,{pinned=false}={}){
    const f=FEATURES[id],live=this.root.querySelector('[data-passage-live]'),empty=this.root.querySelector('[data-passage-empty]');if(!f||!live)return;
    const current=[...this.root.querySelectorAll('.analysis-mark')].filter(el=>el.dataset.feature.split(' ').includes(id)),baseline=[...this.root.querySelectorAll('[data-baseline-feature]')].filter(el=>el.dataset.baselineFeature.split(' ').includes(id)),fromBaseline=mark.matches('[data-baseline-feature]'),index=Math.max(0,(fromBaseline?baseline:current).indexOf(mark)),currentMark=fromBaseline?(current[Math.min(index,Math.max(0,current.length-1))]||null):mark,baselineMark=fromBaseline?mark:(baseline[Math.min(index,Math.max(0,baseline.length-1))]||null),paper=BASELINES[this.baselineIndex];
    const set=(selector,value)=>{const el=live.querySelector(selector);if(el)el.textContent=value};
    const exact=this.evidenceScope==='exact'&&this.catalogFeature&&guideLensFor(FEATURE_BY_CODE[this.catalogFeature])===id,exactFeature=exact?FEATURE_BY_CODE[this.catalogFeature]:null,exactLabel=exactFeature?(exactFeature.professorLabel||exactFeature.shortLabel||exactFeature.name):'';
    set('[data-hover-glyph]',f.glyph);set('[data-hover-feature]',`${f.title} passage family`);set('[data-hover-state]',pinned?'SELECTED CONTEXT':'PASSAGE CONTEXT');set('[data-hover-current]',this.passageSnippet(currentMark));set('[data-hover-baseline]',this.passageSnippet(baselineMark));set('[data-hover-current-value]','THIS PAPER');set('[data-hover-baseline-value]','PRIOR PAPER');set('[data-hover-baseline-paper]',`BASELINE PAPER ${paper.paper} · ILLUSTRATIVE`);set('[data-hover-explanation]',exact?`This passage supplies broader ${f.title.toLowerCase()} context for ${exactLabel} (technical measure: ${exactFeature.name}); the colored region is not an exact token-level attribution. ${f.behavior}`:`This is a passage-family comparison, not an exact feature measurement. ${f.behavior}`);
    empty.hidden=true;live.hidden=false;const inspector=this.root.querySelector('.feature-inspector');inspector?.classList.add('is-previewing');inspector?.classList.toggle('has-pinned-passage',pinned);
  }
  hidePassagePreview(){
    const live=this.root.querySelector('[data-passage-live]'),empty=this.root.querySelector('[data-passage-empty]');if(!live||!empty)return;
    live.hidden=true;empty.hidden=false;const inspector=this.root.querySelector('.feature-inspector');inspector?.classList.remove('is-previewing','has-pinned-passage');
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
  resize(){if(!this.canvas||!this.ctx)return;const rect=this.canvas.getBoundingClientRect(),dpr=Math.min(devicePixelRatio||1,2);this.canvas.width=Math.max(1,Math.round(rect.width*dpr));this.canvas.height=Math.max(1,Math.round(rect.height*dpr));this.ctx.setTransform(dpr,0,0,dpr,0,0);this.cw=rect.width;this.ch=rect.height}
  animate(now=performance.now()){this.drawCorrelation(now);this.frame=requestAnimationFrame(time=>this.animate(time))}
  drawCorrelation(now){
    if(!this.ctx||!this.cw)return;const ctx=this.ctx,w=this.cw,h=this.ch,t=(now-this.start)/1000,styles=getComputedStyle(this.root),accent=styles.getPropertyValue('--accent').trim()||'#7de0cb',muted=styles.getPropertyValue('--ed-muted').trim()||'#789498';ctx.clearRect(0,0,w,h);
    const ids=Object.keys(FEATURES),colorFor=id=>getComputedStyle(this.root.querySelector(`[data-feature-select="${id}"]`)).getPropertyValue('--feature-color').trim()||accent,selected=this.active==='all'?null:this.active,focus=this.hover||selected,targetZoom=selected?1:0,reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
    this.correlationZoom=reduced?targetZoom:this.correlationZoom+(targetZoom-this.correlationZoom)*.075;
    const zoom=this.correlationZoom,relatedIds=selected?FEATURES[selected].related.map(entry=>entry[0]):[],center={x:w*.5,y:h*.43},nodes=ids.map((id,i)=>{const angle=-Math.PI/2+i*Math.PI*2/ids.length+t*.025,radius=Math.min(w*.34,h*.34),baseX=w/2+Math.cos(angle)*radius,baseY=h/2+Math.sin(angle)*radius*.78,relationIndex=relatedIds.indexOf(id),relationAngle=relationIndex===0?Math.PI*.1:Math.PI*.9,targetX=id===selected?center.x:relationIndex>=0?center.x+Math.cos(relationAngle)*w*.31:baseX,targetY=id===selected?center.y:relationIndex>=0?center.y+Math.sin(relationAngle)*h*.34:baseY;return{id,x:baseX+(targetX-baseX)*zoom,y:baseY+(targetY-baseY)*zoom,color:colorFor(id),isRelated:relationIndex>=0}});
    nodes.forEach((a,i)=>nodes.slice(i+1).forEach(b=>{const related=FEATURES[a.id].related.some(r=>r[0]===b.id);if(!related)return;const connected=a.id===focus||b.id===focus,selectedEdge=selected&&(a.id===selected||b.id===selected);ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.strokeStyle=connected?(a.id===focus?a.color:b.color):selectedEdge?colorFor(selected):muted;ctx.globalAlpha=connected?.58:selectedEdge?.42:.1*(1-zoom*.72);ctx.lineWidth=connected?1.2:selectedEdge?1:.5;ctx.stroke()}));ctx.globalAlpha=1;
    nodes.forEach(node=>{const active=node.id===focus||node.id===selected,pulse=active?1.8+Math.sin(t*2.4)*1.05:0,peripheral=selected&&node.id!==selected&&!node.isRelated,size=node.id===selected?6+zoom*3:node.isRelated?4.2:3;ctx.beginPath();ctx.arc(node.x,node.y,size+pulse,0,Math.PI*2);ctx.fillStyle=node.color;ctx.globalAlpha=peripheral?.16:active?.96:node.isRelated?.76:.48;ctx.fill();ctx.font=`${node.id===selected?7:6}px DM Mono`;ctx.textAlign='center';ctx.fillStyle=active||node.isRelated?node.color:muted;ctx.globalAlpha=peripheral?.18:active?.96:.7;ctx.fillText(FEATURES[node.id].glyph,node.x,node.y+size+9)});ctx.globalAlpha=1;
  }
  destroy(){const viewport=this.root.querySelector('[data-comparison-viewport]');if(viewport){EDITOR_STATE.scrollTop=viewport.scrollTop;EDITOR_STATE.scrollLeft=viewport.scrollLeft}EDITOR_STATE.compare=this.compare;cancelAnimationFrame(this.frame);clearTimeout(this.saveTimer);clearTimeout(this.busyTimer);clearTimeout(this.previewShowTimer);clearTimeout(this.previewHideTimer);clearTimeout(this.cameraTimer);this.abort.abort();this.observer?.disconnect()}
}

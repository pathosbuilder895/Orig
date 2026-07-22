import { ConstellationEngine } from './constellation-engine.js?v=professor-solar-final4';
import { NetworkPulseEngine } from './network-pulse-engine.js?v=professor-solar-final4';
import { TemporalIntelligence } from './temporal-chart.js?v=professor-solar-final4';
import { DocumentIntelligence } from './document-intelligence.js?v=professor-solar-final4';
import { FEATURE_PLANETS, TIERS } from './feature-universe-data.js?v=professor-solar-final4';

let activeEngine = null;
let pulseEntryCluster = null;
let professorCatalogMode = 'essentials';
let editorEntryFeature = null;

const SIGNAL_SYSTEMS = {
  s:'surface', b:'surface', s1:'surface', v:'rhetoric', r:'discourse', c:'discourse', p:'rhetoric'
};

const icon = (name) => {
  const paths = {
    home:'<path d="M3 11.5 12 4l9 7.5v8a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
    nodes:'<circle cx="6" cy="7" r="2.5"/><circle cx="18" cy="5" r="2.5"/><circle cx="17" cy="18" r="2.5"/><path d="m8.4 6.6 7.1-1.2M7.5 9l8 7"/>',
    file:'<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v5h4M9 13h6M9 17h6"/>',
    chat:'<path d="M4 5h16v12H8l-4 4z"/><path d="M8 9h8M8 13h5"/>',
    search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
    spark:'<path d="m12 3 1.5 5.5L19 10l-5.5 1.5L12 17l-1.5-5.5L5 10l5.5-1.5z"/>',
    arrow:'<path d="M5 12h14M14 7l5 5-5 5"/>',
    filter:'<path d="M4 6h16M7 12h10M10 18h4"/>',
    bar:'<path d="M5 20V11h3v9zM11 20V5h3v15zM17 20v-7h3v7z"/>',
    editor:'<path d="M5 3h10l4 4v14H5zM15 3v5h4M8 12h8M8 16h5"/><path d="m16.5 15.5 3 3M18 14l2 2-5 5-2.5.5.5-2.5z"/>',
  };
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${paths[name]||''}</svg>`;
};

const DATA = {
  nodes:[
    {id:'s',x:50,y:50,r:35,label:'SUBMISSION',sub:'Morgan Lee · Essay 4',kind:'core'},
    {id:'b',x:22,y:24,r:20,label:'BASELINE',sub:'12 samples',kind:'gold'},
    {id:'s1',x:75,y:22,r:15,label:'SURFACE',sub:'structure · review',kind:'risk'},
    {id:'v',x:82,y:59,r:17,label:'RHETORIC',sub:'vocabulary · aligned',kind:'safe'},
    {id:'c',x:63,y:83,r:14,label:'DISCOURSE',sub:'sources · review',kind:'risk'},
    {id:'r',x:20,y:74,r:17,label:'REVISION',sub:'pacing · watch',kind:'gold'},
    {id:'p',x:9,y:49,r:11,label:'CONTEXT',sub:'course · assignment',kind:'muted'}
  ],
  edges:[['s','b'],['s','s1'],['s','v'],['s','c'],['s','r'],['b','r'],['b','p'],['s1','v'],['c','v']]
};

const SIGNAL_DETAILS = {
  s:{glyph:'Σ',title:'Current submission',badge:'Review signal',tone:'review',copy:'This fictional paper sits at the center. Connections show which observations deserve review and which provide counterevidence.',bars:[36,42,39,48,54,50,61,58,65,67,72,82],related:[['Sentence structure','Six passages outside the usual range','review'],['Vocabulary continuity','Inside the established range','aligned'],['Revision context','A possible alternate explanation','watch']]},
  b:{glyph:'B',title:'Verified baseline',badge:'12 papers',tone:'watch',copy:'Twelve illustrative prior papers define the student’s expected range. Three are available for side-by-side review.',bars:[44,49,45,52,47,55,51,58,53,57,55,56],related:[['Viewable baseline papers','Three examples available','aligned'],['Assignment context','Same course and genre','watch'],['Writing timeline','Evidence gathered over time','aligned']]},
  s1:{glyph:'01',title:'Surface · sentence structure',badge:'Outside usual range',tone:'review',copy:'Clause layering appears more often than in the illustrative baseline. This is a review signal, not a conclusion about authorship.',bars:[28,34,31,39,42,45,48,51,54,58,63,88],related:[['Clause layering','Six passages to compare','review'],['Punctuation use','Moves with sentence structure','watch'],['Open in Text Studio','Review the exact passages','aligned']]},
  v:{glyph:'03',title:'Rhetoric · vocabulary continuity',badge:'Aligned',tone:'aligned',copy:'Topic vocabulary and preferred abstractions remain consistent with prior work, providing important counterevidence.',bars:[55,52,57,54,59,56,60,58,61,59,60,61],related:[['Topic vocabulary','Four recurring terms','aligned'],['Claim framing','Inside expected range','aligned'],['Open in Text Studio','Review the aligned examples','aligned']]},
  c:{glyph:'02',title:'Discourse · source transitions',badge:'Review 3 passages',tone:'review',copy:'Three sources are introduced without the interpretive bridge found in the illustrative baseline.',bars:[31,35,33,38,36,41,39,43,40,45,48,76],related:[['Source handoffs','Three passages to compare','review'],['Citation placement','One connected observation','watch'],['Open in Text Studio','Review the exact passages','aligned']]},
  r:{glyph:'↻',title:'Revision · paragraph pacing',badge:'Watch',tone:'watch',copy:'Paragraph pacing moved moderately but remains near the expected boundary. Draft history may explain the change.',bars:[42,46,44,50,47,53,49,55,52,57,59,64],related:[['Draft history','Four recorded revisions','aligned'],['Paragraph rhythm','Near the expected boundary','watch'],['Assignment structure','Check the prompt requirements','watch']]},
  p:{glyph:'C',title:'Course and assignment context',badge:'Context only',tone:'neutral',copy:'Genre, prompt, sources, tutoring, accommodations, and revision process should be checked before any instructor action.',bars:[50,50,50,50,50,50,50,50,50,50,50,50],related:[['Assignment genre','Research essay','neutral'],['Source requirement','Four assigned authors','neutral'],['Instructor decision','Context remains essential','aligned']]}
};

function updateSignalPanel(event) {
  const detail = SIGNAL_DETAILS[event.detail.id];
  if (!detail) return;
  const root = document.querySelector('.detail-card');
  if (!root) return;
  const set = (selector, value) => { const el=root.querySelector(selector); if(el) el.textContent=value; };
  set('[data-detail-glyph]',detail.glyph); set('[data-detail-title]',detail.title);
  set('[data-detail-badge]',detail.badge); set('[data-detail-copy]',detail.copy);
  root.dataset.tone = detail.tone;
  const badge = root.querySelector('[data-detail-badge]');
  if (badge) badge.className = `status-pill ${detail.tone}`;
  const chart = root.querySelector('[data-detail-chart]');
  if (chart) chart.innerHTML = detail.bars.map((height,index)=>`<i style="height:${height}%" class="${index===detail.bars.length-1?detail.tone:''}"></i>`).join('');
  const related = document.querySelector('[data-related-list]');
  if (related) related.innerHTML = detail.related.map(([title,copy,tone])=>`<button type="button" data-view="editor"><i class="${tone}"></i><span>${title}<small>${copy}</small></span><b>↗</b></button>`).join('');
  const relatedCount = document.querySelector('[data-related-count]');
  if (relatedCount) relatedCount.textContent = String(detail.related.length);
  bindViewLinks();
}

function graph() {
  return `<div class="graph graph-3d" aria-label="Interactive four-dimensional writing-pattern relationship graph">
    <canvas class="constellation-canvas"></canvas>
    <div class="graph-vignette"></div>
    <div class="dimension-readout"><span class="dim-live"></span><b>REVISION EVOLUTION · 4D MODEL</b><small>timeline = <span data-time-readout>72</span>%</small></div>
    <div class="selected-readout"><small>SELECTED SIGNAL</small><b data-selected-title>Submission</b><span data-selected-meta>Morgan Lee · Essay 4</span></div>
    <button class="graph-system-entry" data-enter-system type="button"><small>SELECTED SYSTEM</small><b data-system-title>Surface · sentence structure</b><span>Enter evidence system&nbsp; →</span></button>
    <div class="graph-hud">
      <button data-camera="reset" title="Reset camera" aria-label="Reset constellation camera">◎</button>
      <button data-camera="in" title="Zoom in" aria-label="Zoom into constellation">＋</button>
      <button data-camera="out" title="Zoom out" aria-label="Zoom out of constellation">−</button>
      <button data-camera="motion" title="Play constellation motion" aria-label="Play constellation motion" aria-pressed="false">▶</button>
    </div>
    <div class="time-control"><div class="time-label"><span>BASELINE</span><b>REVISION TIMELINE</b><span>CURRENT PAPER</span></div><input data-time-axis type="range" min="0" max="100" value="72" aria-label="Move from baseline to the current revision"></div>
    <div class="graph-key"><span><i class="safe"></i>aligned</span><span><i class="gold"></i>watch</span><span><i class="risk"></i>deviation</span><span class="gesture">DRAG TO ORBIT · SCROLL TO ZOOM</span></div>
  </div>`;
}

function shell(content, active='overview') {
  return `<aside class="rail">
    <div class="brand"><div class="mark">O</div><span>ORIGINAL</span></div>
    <nav>
      <button class="${active==='overview'?'active':''}" data-view="overview">${icon('home')}<span>Command</span></button>
      <button class="${active==='constellation'?'active':''}" data-view="constellation">${icon('nodes')}<span>Constellation</span></button>
      <button class="${active==='pulse'?'active':''}" data-view="pulse">${icon('spark')}<span>Network pulse</span></button>
      <button class="${active==='temporal'?'active':''}" data-view="temporal">${icon('bar')}<span>Temporal</span></button>
      <button class="${active==='editor'?'active':''}" data-view="editor">${icon('editor')}<span>Text studio</span></button>
      <button class="${active==='case'?'active':''}" data-view="case">${icon('file')}<span>Case file</span></button>
    </nav>
    <div class="rail-foot"><span class="live-dot"></span> Synthetic demo<div class="avatar">AC</div></div>
  </aside>
  <main>${content}</main>`;
}

function header(kicker,title,meta='Fall 2026 · Synthetic institution') {
  return `<header><div><div class="eyebrow">${kicker}</div><h1>${title}</h1></div><div class="demo-trust" role="note"><span>INTERACTIVE CONCEPT</span><b>Fictional student · illustrative metrics · no records saved</b></div><div class="head-tools"><span class="date-chip">${meta}</span></div></header>`;
}

function overview() {
  return shell(`${header('Professor demonstration · Command','Authorship intelligence')}
    <section class="dashboard-grid">
      <div class="hero-panel panel"><div class="panel-label"><span>ILLUSTRATIVE INVESTIGATION MAP</span><button data-view="constellation">Open constellation ${icon('arrow')}</button></div>${graph()}</div>
      <aside class="signal-panel panel">
        <div class="panel-label"><span>PRIORITY REVIEW</span><span class="status-pill review">REVIEW SUGGESTED</span></div>
        <div class="score-ring"><div><strong>0.82</strong><span>deviation index</span><small>not a probability</small></div></div>
        <h2>Morgan Lee</h2><p>Essay 4 · Systematic Theology</p>
        <div class="signal-list"><div><span>Sentence structure</span><b>Outside usual range</b></div><div><span>Source transitions</span><b>Review 3 passages</b></div><div><span>Vocabulary continuity</span><b class="okay">Aligned</b></div></div>
        <button class="primary" data-view="case">Review evidence ${icon('arrow')}</button>
      </aside>
      <div class="metric panel"><span>STUDENTS WITH BASELINES</span><strong>148</strong><small>illustrative institution count</small></div>
      <div class="metric panel accent"><span>OPEN CONVERSATIONS</span><strong>07</strong><small>2 require attention</small></div>
      <div class="metric panel"><span>SUBMISSIONS / 7D</span><strong>326</strong><small>median review time 2.1 days</small></div>
      <div class="activity panel"><div class="panel-label"><span>RECENT REVIEW SIGNALS</span></div>
        ${[['Avery Chen','Voice stable; citation pattern shifted','0.67'],['Noah Williams','Syntactic density outside baseline','0.79'],['Morgan Lee','Multi-feature deviation cluster','0.82']].map((x,i)=>`<div class="activity-row"><span class="index">0${i+1}</span><div><b>${x[0]}</b><small>${x[1]}</small></div><strong>${x[2]}</strong></div>`).join('')}
      </div>
      <div class="analyst panel"><div class="panel-label"><span>ORIGINAL ANALYST</span>${icon('spark')}</div><p>“Suggested first evidence: compare Morgan’s sentence structure while keeping the aligned vocabulary signal in view. The instructor decides what follows.”</p><button data-view="case">Review suggested evidence ${icon('arrow')}</button></div>
    </section>`,'overview');
}

function constellation() {
  return shell(`${header('Professor demonstration · Evidence map','Writing-pattern constellation','Morgan Lee · 12 illustrative baseline papers')}
    <section class="constellation-layout">
      <div class="constellation-main panel">
        <div class="canvas-tools constellation-guide"><span><b>CENTER</b> current paper</span><span><b>ORBITS</b> Surface · Discourse · Rhetoric</span><span><b>SLIDER</b> revision evolution</span><button type="button" data-view="editor">Open passages →</button></div>
        ${graph()}
      </div>
      <aside class="detail-stack">
        <div class="panel detail-card" data-tone="review"><div class="panel-label"><span>SELECTED NODE</span><span class="status-pill review" data-detail-badge>Outside usual range</span></div><div class="big-icon" data-detail-glyph>01</div><h2 data-detail-title>Surface · sentence structure</h2><p data-detail-copy>Clause layering appears more often than in the illustrative baseline. This is a review signal, not a conclusion about authorship.</p><div class="mini-chart" data-detail-chart>${SIGNAL_DETAILS.s1.bars.map((h,i)=>`<i style="height:${h}%" class="${i===11?'review':''}"></i>`).join('')}</div><div class="chart-axis"><span>Illustrative baseline</span><span>Current</span></div><button class="detail-open" type="button" data-view="editor">Open highlighted passages →</button></div>
        <div class="panel related"><div class="panel-label"><span>CONNECTED EXAMPLES</span><b data-related-count>3</b></div><div data-related-list>${SIGNAL_DETAILS.s1.related.map(([title,copy,tone])=>`<button type="button" data-view="editor"><i class="${tone}"></i><span>${title}<small>${copy}</small></span><b>↗</b></button>`).join('')}</div></div>
      </aside>
    </section>`,'constellation');
}

function pulse() {
  return shell(`${header('Future concept · Relationship explorer','Writing-pattern galaxy','Illustrative map · 103 traits')}
    <section class="pulse-layout">
      <div class="pulse-stage panel">
        <div class="pulse-topbar">
          <div><span class="pulse-live"><i></i>ILLUSTRATIVE MODEL</span><b>Three writing-division solar systems · 103 feature planets</b></div>
          <div class="pulse-top-actions">
            <div class="pulse-view-tools" aria-label="Network camera controls"><button type="button" data-pulse-camera="out" aria-label="Zoom out">−</button><button type="button" data-pulse-camera="reset"><span data-pulse-zoom>100%</span> · Fit</button><button type="button" data-pulse-camera="in" aria-label="Zoom in">＋</button><button type="button" data-pulse-compare aria-pressed="false">◫ Baseline</button><button type="button" data-pulse-camera="mode" aria-pressed="true"><span data-pulse-mode>Orbit</span> drag</button></div>
          </div>
          <div class="pulse-fourth-axis">
            <div><span><i></i>FOURTH DIMENSION · REVISION EVOLUTION</span><em data-pulse-dimension-moment>DRAFT 03 · SOURCE INTEGRATION</em><b>t = <output data-pulse-dimension-value>72%</output></b><button type="button" data-pulse-dimension-motion aria-pressed="false">▶ Play</button></div>
            <input type="range" min="0" max="100" value="72" data-pulse-dimension aria-label="Fourth dimension: evidence evolution">
            <small><span>BASELINE FORMED</span><span>REVISION HISTORY</span><span>CURRENT PAPER</span></small>
          </div>
        </div>
        <div class="pulse-canvas-wrap">
          <canvas class="pulse-canvas" aria-label="Interactive writing-pattern relationship galaxy"></canvas>
          <div class="pulse-overlay">
            <div class="pulse-navigation">
              <button type="button" data-pulse-back hidden>← Back to galaxy</button>
              <div class="pulse-crumb"><span data-pulse-level>GALAXY</span><div class="pulse-path" data-pulse-path><button type="button" data-crumb="galaxy">All galaxies</button></div><small data-pulse-instruction>Select one of the three large evidence systems.</small></div>
            </div>
            <div class="pulse-camera-hint"><span data-pulse-gesture>DRAG TO ORBIT</span> · SCROLL TO ZOOM · SHIFT+DRAG TO PAN</div>
            <div class="pulse-legend"><span><i class="sun"></i>division sun</span><span><i class="tier"></i>tier orbit</span><span><i class="positive"></i>aligned</span><span><i class="neutral"></i>watch</span><span><i class="negative"></i>review</span></div>
            <article class="pulse-evidence-card" data-pulse-evidence hidden>
              <div class="pulse-evidence-head"><span data-evidence-kicker>EVIDENCE PLANET</span><button type="button" data-evidence-close aria-label="Close evidence">×</button></div>
              <h3 data-evidence-title>Voice continuity</h3>
              <p class="evidence-reading" data-evidence-reading></p>
              <div class="evidence-pair">
                <div><span>CURRENT SIGNAL</span><blockquote data-evidence-current></blockquote></div>
                <div><span>ILLUSTRATIVE BASELINE</span><blockquote data-evidence-baseline></blockquote></div>
              </div>
              <div class="evidence-meaning"><span>WHAT THE CONNECTION MEANS</span><p data-evidence-meaning></p></div>
              <div class="evidence-links"><span>CONNECTED EXAMPLES</span><div><button type="button" data-related-feature="1"><b></b><small></small></button><button type="button" data-related-feature="2"><b></b><small></small></button></div></div>
              <button class="evidence-open" type="button" data-view="editor">Open in Text studio →</button>
            </article>
            <div class="pulse-tooltip" data-pulse-tooltip hidden></div>
          </div>
        </div>
        <div class="pulse-ticker"><span>DEMO STATUS</span><div><i class="positive"></i>97 traits available for imported papers</div><div><i class="emergent"></i>Connections are illustrative</div><div><i class="negative"></i>6 drafting traits require live capture</div></div>
      </div>
      <aside class="pulse-controls">
        <div class="panel interest-panel"><div class="panel-label"><span data-index-title>THREE WRITING DIVISIONS</span><b data-index-count>103 FEATURE PLANETS</b></div><p data-index-copy>Choose the Surface, Discourse, or Rhetoric sun. Its tier planets appear next, followed by concrete current and baseline examples.</p>
          <div class="interest-list hierarchy-index" data-hierarchy-index aria-label="Galaxy hierarchy"></div>
          <button class="add-interest" data-pulse-all>← Return to full galaxy</button>
        </div>
        <div class="panel revelation-side-panel" data-revelation>
          <div class="panel-label"><span>EMERGENT CONNECTION</span><b>91 RELEVANCE</b></div>
          <h3>Semicolon and colon use moves with clause layering.</h3>
          <p>The same abstract passages contain both denser punctuation and deeper clauses. Review them together rather than treating them as two independent proofs.</p>
          <button type="button" data-focus-revelation>Inspect linked examples →</button>
        </div>
        <div class="panel sentiment-panel"><div class="panel-label"><span>SIGNAL STATUS</span><b data-sentiment-value>ALL</b></div><div class="sentiment-tabs"><button class="active" data-sentiment="all">All</button><button data-sentiment="positive">Aligned</button><button data-sentiment="neutral">Watch</button><button data-sentiment="negative">Review</button></div>
          <div class="sentiment-meter"><div><span style="width:46%"></span><span style="width:38%"></span><span style="width:16%"></span></div><small><b>46%</b> aligned</small><small><b>38%</b> watch</small><small><b>16%</b> review</small></div>
        </div>
        <div class="panel interpretation-panel"><div class="panel-label"><span>HOW TO READ THIS</span><b>CONTEXT, NOT PROOF</b></div><p>Select a planet to see the actual sentence, the baseline example, and a plain-language interpretation. Relationships suggest where to look; they never decide authorship.</p><button type="button" data-view="editor">Open professor review mode →</button></div>
      </aside>
    </section>`,'pulse');
}

function temporal() {
  return shell(`${header('Future concept · Institutional patterns','Writing-pattern activity','Spring 2026 · 18 illustrative weeks')}
    <section class="temporal-shell">
      <aside class="temporal-left panel">
        <div class="stability-card"><div class="panel-label"><span>WRITING-PATTERN CONSISTENCY</span><b>STABLE</b></div><div class="stability-score"><span>✓</span><strong>69<small>%</small></strong><div class="micro-histogram">${[2,3,4,6,8,11,15,10,7,5,4,3,4,6,7,4,3,2].map((h,i)=>`<i style="--h:${h};--d:${i}"></i>`).join('')}</div></div><p>Share of submissions inside the expected range</p><div class="stability-detail"><div><span>Interpretation</span><b>Not an authorship probability</b></div><div><span>Movement</span><b>−0.07σ</b></div><div><span>Profiles ready</span><b>110 / 155</b></div></div></div>
        <div class="sentiment-dial"><span>SUBMISSION OUTCOMES</span><div class="half-donut"><div><strong>1,570</strong><small>illustrative submissions</small></div></div><div class="dial-legend"><div><i class="positive"></i><span>Expected</span><b>69%</b></div><div><i class="neutral"></i><span>Developing</span><b>17%</b></div><div><i class="negative"></i><span>Review</span><b>14%</b></div></div></div>
        <div class="engagement-block"><span>REVIEW WORKFLOW</span><div class="engagement-grid"><div>${icon('search')}<small>Reviews opened</small><b>382</b><em>18 weeks</em></div><div>${icon('chat')}<small>Conversation suggested</small><b>65</b><em>instructor decides</em></div><div>${icon('nodes')}<small>Baselines ready</small><b>110</b><em>of 155 profiles</em></div><div>${icon('file')}<small>Cases resolved</small><b>276</b><em>illustrative workflow</em></div></div></div>
      </aside>
      <div class="temporal-main panel">
        <div class="temporal-kpis">
          <button class="active" data-temporal-mode="activity"><i style="--k:#59c5c7"></i><span>Submissions analyzed</span><strong>1,570</strong><small>derived from the chart</small></button>
          <button data-temporal-mode="readiness"><i style="--k:#d7a94c"></i><span>Baselines ready</span><strong>71%</strong><small>110 of 155 profiles</small></button>
          <button data-temporal-mode="workflow"><i style="--k:#8d9ba0"></i><span>Reviews opened</span><strong>382</strong><small>median 2.1 days</small></button>
          <button data-temporal-mode="evidence"><i style="--k:#b783ef"></i><span>Evidence signals</span><strong>765</strong><small>across 4 review states</small></button>
        </div>
        <div class="temporal-toolbar">
          <div class="temporal-title"><span data-chart-kicker>INSTITUTIONAL ACTIVITY</span><b data-chart-title>Submission outcomes over time</b></div>
          <div class="filter-chips"><span class="active">All courses · illustrative dataset</span><button class="cinematic-button" data-cinematic>◉ Guided explanation</button></div>
        </div>
        <div class="chart-stage">
          <div class="chart-aurora"></div>
          <svg class="temporal-svg" role="img" aria-label="Interactive stacked authorship activity chart"></svg>
          <svg class="chart-crystal" viewBox="0 0 420 190" preserveAspectRatio="none" aria-hidden="true">
            <defs>
              <linearGradient id="crystal-fill" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#d8e0dc" stop-opacity=".62"/><stop offset=".45" stop-color="#526865" stop-opacity=".42"/><stop offset="1" stop-color="#071211" stop-opacity=".9"/></linearGradient>
              <filter id="crystal-noise" x="-20%" y="-20%" width="140%" height="140%"><feTurbulence type="fractalNoise" baseFrequency=".035 .11" numOctaves="4" seed="17" result="noise"/><feDisplacementMap in="SourceGraphic" in2="noise" scale="18" xChannelSelector="R" yChannelSelector="B"/><feSpecularLighting in="noise" surfaceScale="3" specularConstant=".45" specularExponent="18" lighting-color="#dce8e3" result="spec"><feDistantLight azimuth="225" elevation="42"/></feSpecularLighting><feComposite in="spec" in2="SourceGraphic" operator="in" result="lit"/><feBlend in="SourceGraphic" in2="lit" mode="screen"/></filter>
            </defs>
            <path d="M-20 171L8 134L37 142L67 95L99 116L131 42L159 91L192 65L225 121L261 82L294 133L333 110L365 151L402 138L440 171V200H-20Z" fill="url(#crystal-fill)" filter="url(#crystal-noise)"/>
            <path d="M-20 171L8 134L37 142L67 95L99 116L131 42L159 91L192 65L225 121L261 82L294 133L333 110L365 151L402 138L440 171" fill="none" stroke="#d9e5df" stroke-opacity=".34"/>
          </svg>
          <div class="chart-tooltip" data-chart-tooltip hidden></div>
          <div class="chart-mode-note" data-mode-note>Each submission appears in exactly one outcome state.</div>
        </div>
        <div class="chart-footer">
          <div class="chart-legend" data-chart-legend></div>
          <div class="playback"><button data-playback aria-label="Play timeline">▶</button><span>JAN 12</span><input type="range" min="0" max="17" value="13" data-period-scrubber aria-label="Selected chart period"><span>MAY 18</span></div>
        </div>
      </div>
      <aside class="temporal-side">
        <div class="panel details-card"><div class="panel-label"><span>ILLUSTRATIVE DATASET</span><b>THEOLOGY</b></div><dl><div><dt>Academic period</dt><dd>Spring 2026</dd></div><div><dt>Student profiles</dt><dd>155</dd></div><div><dt>Active dimensions</dt><dd>97</dd></div><div><dt>Submissions analyzed</dt><dd>1,570</dd></div></dl></div>
        <div class="panel execution-card"><div class="panel-label"><span>BASELINE READINESS</span><b>110 / 155</b></div><div><strong>71%</strong><span>current period</span></div><div class="execution-track">${Array.from({length:28},(_,i)=>`<i class="${i<20?'on':''}"></i>`).join('')}</div></div>
        <div class="panel entity-card"><div class="panel-label"><span>COURSES INVOLVED</span><b>3</b></div><button><i>›</i><span>Systematic Theology</span><em>↗</em></button><button><i>›</i><span>Christian Ethics</span><em>↗</em></button><button><i>›</i><span>Church History</span><em>↗</em></button></div>
        <div class="panel related-card"><div class="panel-label"><span>RELATED EVIDENCE</span><b>3</b></div><button data-view="constellation"><span>Sentence-structure constellation</span><em>Explore ↗</em></button><button data-view="editor"><span>Source-transition passages</span><em>Review ↗</em></button><button data-view="case"><span>Instructor decision context</span><em>Open ↗</em></button></div>
        <div class="panel analyst-card"><div class="panel-label"><span>ORIGINAL ANALYST</span>${icon('spark')}</div><div class="analyst-signal"><i></i><span data-analyst-tag>STABLE RATE</span></div><h2 data-analyst-title>Volume changed without a proportional recommendation increase.</h2><p data-analyst-copy>Submission volume increased 14%, while the conversation-recommendation rate remained inside its eight-week range.</p><div class="analyst-facts"><div><span>Observed</span><b data-fact-one>+17 submissions</b></div><div><span>Normalized rate</span><b data-fact-two>4.1% · stable</b></div></div><button data-inspect>Inspect contributing periods →</button></div>
      </aside>
    </section>`,'temporal');
}

function caseView() {
  return shell(`${header('Professor demonstration · Decision support','Case review / Morgan Lee','Case ORG-1842 · Fictional draft')}
    <section class="case-layout">
      <div class="case-summary panel"><div class="case-top"><div><span class="status-pill review">REVIEW SUGGESTED</span><h2>Several writing patterns changed enough to review.</h2><p>This index is not a verdict or a probability of misconduct. Review the passages, consider alternate explanations, and let the instructor decide whether a supportive conversation is appropriate.</p></div><div class="confidence deviation-index"><strong>0.82</strong><span>index</span><small>deviation · not probability</small></div></div>
        <div class="evidence-grid"><article><span>01 · REVIEW</span><h3>Sentence structure</h3><p>Long, layered clauses appear more often than in the illustrative baseline.</p><div class="quote">“Consequently, one must recognize the ontological distinction…”</div><button type="button" data-editor-feature="clause_depth_mean">Compare 6 passages →</button></article><article><span>02 · REVIEW</span><h3>Source transitions</h3><p>Three sources are introduced using patterns not seen in the illustrative baseline.</p><div class="compare"><div><small>BASELINE</small><b>As Augustine writes…</b></div><div><small>CURRENT</small><b>Scholarship establishes…</b></div></div><button type="button" data-editor-feature="source_integration_style">Compare source passages →</button></article><article><span>03 · ALIGNED COUNTEREVIDENCE</span><h3>Vocabulary continuity</h3><p>Topic vocabulary remains strongly consistent with prior work.</p><div class="tags"><i>grace</i><i>nature</i><i>Augustine</i><i>will</i></div><button type="button" data-editor-feature="type_token_ratio">Review aligned examples →</button></article></div>
        <section class="context-check"><div><span>CONTEXT TO CHECK</span><b>Before any instructor action</b></div><ul><li>Assignment genre and prompt</li><li>Required sources or template</li><li>Tutoring or writing-center support</li><li>Accommodations and assistive tools</li><li>Draft and revision history</li></ul></section>
      </div>
      <aside class="decision panel"><div class="panel-label"><span>DECISION SUPPORT</span>${icon('spark')}</div><h2>Prepare the conversation</h2><p>Original keeps the instructor in control. Choose an action and generate a neutral, evidence-led brief.</p><label>Suggested next step</label><button class="choice selected" data-case-action="conversation"><i></i><span><b>Invite a conversation</b><small>Ask about process, sources, and revision</small></span></button><button class="choice" data-case-action="sample"><i></i><span><b>Request another sample</b><small>Gather more authorship evidence</small></span></button><button class="choice" data-case-action="clear"><i></i><span><b>Clear the case</b><small>Record reviewed, no further action</small></span></button><button class="primary" type="button" data-build-brief>Build conversation brief ${icon('arrow')}</button><button class="secondary" type="button" data-save-case>Save local demo state</button><div class="case-feedback" data-case-feedback role="status">No record has been saved.</div><section class="conversation-brief" data-conversation-brief hidden><div><span>CONVERSATION BRIEF</span><button type="button" data-close-brief aria-label="Close conversation brief">×</button></div><h3>Begin with the student’s process</h3><p>“I noticed that a few sentence and source-transition patterns differ from your earlier work, while your vocabulary remains consistent. Could you walk me through how you drafted and revised these passages?”</p><ul><li>Ask which sources shaped the revision.</li><li>Invite drafts, notes, or version history.</li><li>Record context before deciding any next step.</li></ul><small>Generated from illustrative data · instructor edits and decides</small></section><div class="audit-note">Production concept: decisions and evidence access would be recorded in an audit log.</div></aside>
    </section>`,'case');
}

const catalogLensForTier = {0:'lexical',1:'lexical',2:'transition',3:'citation',4:'punctuation',5:'syntax',6:'lexical',7:'cadence',8:'cadence',9:'transition',10:'transition',11:'punctuation',12:'transition',13:'cadence',14:'punctuation',15:'lexical',16:'citation',17:'cadence'};
const FEATURE_DIVISIONS = [
  {id:'surface',label:'Surface',short:'Language form',color:'#d5f36f',tiers:[1,4,5,6,7,8,11,13,14,15,17,0]},
  {id:'discourse',label:'Discourse',short:'Argument flow',color:'#67c995',tiers:[2,9,10,12]},
  {id:'rhetoric',label:'Rhetoric',short:'Claims + sources',color:'#a990ff',tiers:[3,16]}
];
const divisionForTier = tierId => FEATURE_DIVISIONS.find(division=>division.tiers.includes(tierId)) || FEATURE_DIVISIONS[0];
const PROFESSOR_ESSENTIAL_CODES = new Set([
  'type_token_ratio','mean_sentence_length','semicolon_colon_rate','clause_depth_mean','burstiness',
  'discourse_marker_density','transition_density','thematic_progression_score',
  'hedging_density','source_integration_style','appeal_to_authority_density','conclusion_strategy_score'
]);

function featureCatalog() {
  const initialCode = 'semicolon_colon_rate';
  const availability = feature => feature.tier === 17 ? 'Needs drafting data' : feature.tier === 0 ? 'Baseline only' : 'Available';
  return TIERS.map(tier => {
    const features = FEATURE_PLANETS.filter(feature => feature.tier === tier.id && (professorCatalogMode === 'all' || PROFESSOR_ESSENTIAL_CODES.has(feature.code)));
    if (!features.length) return '';
    const division = divisionForTier(tier.id);
    return `<section class="catalog-tier" data-catalog-tier-section="${tier.id}" data-catalog-division-section="${division.id}"${division.id === 'surface' ? '' : ' hidden'} style="--catalog-color:${tier.color}">
      <header><span>${tier.id === 0 ? 'CMP' : `TIER ${String(tier.id).padStart(2,'0')}`}</span><b>${tier.name}</b><em>${features.length}</em></header>
      ${features.map(feature => `<button type="button" class="catalog-feature${feature.code === initialCode ? ' selected' : ''}" data-catalog-feature="${feature.code}" data-catalog-tier-id="${feature.tier}" data-catalog-division="${division.id}" data-catalog-lens="${catalogLensForTier[feature.tier]}" aria-pressed="${feature.code === initialCode}" style="--catalog-color:${feature.color}">
        <i>${feature.tier === 0 ? 'C' : String(feature.tier).padStart(2,'0')}</i><span><b>${feature.professorLabel || feature.shortLabel}</b><small>Technical measure: ${feature.technicalLabel || feature.name}</small></span><em aria-label="${availability(feature)}">${availability(feature)}</em>
      </button>`).join('')}
    </section>`;
  }).join('');
}

function documentEditor() {
  const visibleFeatures = FEATURE_PLANETS.filter(feature => professorCatalogMode === 'all' || PROFESSOR_ESSENTIAL_CODES.has(feature.code));
  return shell(`${header('Professor demonstration · Passage review','Living document intelligence','Morgan Lee · Fictional Essay 4 · Draft 04')}
    <section class="editor-shell" data-editor-theme="navy">
      <div class="editor-atmosphere" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></div>
      <aside class="feature-library glass-panel">
        <div class="editor-panel-head"><div><span>AUTHORSHIP FEATURES</span><b>103 total · 97 available · 6 need live drafting</b></div><button data-feature-all aria-label="Show all feature overlays">∞</button></div>
        <div class="catalog-mode" role="group" aria-label="Feature catalog depth"><button type="button" data-catalog-mode="essentials" aria-pressed="${professorCatalogMode==='essentials'}">Professor essentials</button><button type="button" data-catalog-mode="all" aria-pressed="${professorCatalogMode==='all'}">All 103 traits</button></div>
        <nav class="catalog-divisions" aria-label="Feature divisions">${FEATURE_DIVISIONS.map((division,index)=>{const count=visibleFeatures.filter(feature=>division.tiers.includes(feature.tier)).length;return `<button type="button" data-catalog-division-select="${division.id}" aria-pressed="${index===0}" style="--division-color:${division.color}"><span>0${index+1}</span><b>${division.label}</b><small>${count}</small></button>`}).join('')}</nav>
        <div class="catalog-controls"><label class="feature-search"><span>${icon('search')}</span><input type="search" placeholder="Search selected division" aria-label="Search authorship features" data-catalog-search></label></div>
        <div class="catalog-summary"><span data-catalog-count>${visibleFeatures.filter(feature=>divisionForTier(feature.tier).id==='surface').length} ${professorCatalogMode==='essentials'?'essential':'Surface'} traits</span><b data-catalog-lens-label>Punctuation passage lens</b></div>
        <div class="feature-catalog" data-feature-catalog aria-label="All authorship features">${featureCatalog()}</div>
      </aside>

      <div class="document-stage">
        <div class="document-toolbar glass-panel">
          <div class="review-mode-badge"><i></i><span><b>PROFESSOR REVIEW MODE</b><small>Read-only demonstration</small></span></div>
          <button class="comparison-launch" data-document-compare aria-label="Compare baseline papers" aria-pressed="false"><span aria-hidden="true">▥</span><b>Compare baseline</b></button>
          <div class="document-status"><i></i><span data-save-state>Illustrative analysis · no records saved</span><b data-word-count>265 words</b></div>
          <div class="theme-switcher" role="group" aria-label="Document atmosphere">
            <button class="active" data-theme="navy" aria-label="Navy midnight" data-tooltip="Navy midnight"></button>
            <button data-theme="verdant" aria-label="Verdant glass" data-tooltip="Verdant glass"></button>
            <button data-theme="bodleian" aria-label="Bodleian library" data-tooltip="Bodleian library"></button>
            <button data-theme="forest" aria-label="Old forest" data-tooltip="Old forest"></button>
            <button data-theme="light" aria-label="Parchment daylight" data-tooltip="Parchment daylight"></button>
          </div>
        </div>
        <div class="comparison-ribbon glass-panel" data-comparison-ribbon aria-hidden="true">
          <div class="ribbon-lens"><span>ACTIVE LENS</span><div><i data-ribbon-glyph>;</i><b data-ribbon-title>Punctuation usage</b></div></div>
          <div class="ribbon-metric"><span>CURRENT</span><b data-ribbon-current>18.4</b></div>
          <div class="ribbon-metric"><span>BASELINE</span><b data-ribbon-baseline>8.6—12.9</b></div>
          <div class="ribbon-deviation"><span>POSITION</span><b data-ribbon-delta>+2.1σ above baseline</b><small data-ribbon-occurrences>5 current · 5 baseline passages</small></div>
          <div class="difference-stepper" role="group" aria-label="Navigate correlated differences">
            <button data-difference-prev aria-label="Previous correlated passage">‹</button>
            <b data-difference-counter>1 / 5</b>
            <button data-difference-next aria-label="Next correlated passage">›</button>
          </div>
          <div class="paper-pan-controls" role="group" aria-label="Move between full-size papers">
            <button data-pan-paper="current" aria-pressed="true">Current</button>
            <button data-pan-paper="baseline" aria-pressed="false">Baseline</button>
          </div>
          <div class="baseline-switcher ribbon-baseline-switcher" role="group" aria-label="Switch baseline paper">
            <button data-baseline-prev aria-label="Previous baseline paper">‹</button>
            <b data-baseline-counter>PAPER 03 OF 03</b>
            <button data-baseline-next aria-label="Next baseline paper">›</button>
          </div>
        </div>
        <div class="paper-viewport" data-comparison-viewport role="region" aria-label="Scrollable current paper">
          <div class="paper-comparison-track">
          <section class="paper-column current-paper-column" aria-label="Current submission">
            <div class="paper-context-bar">
              <span><i></i>CURRENT SUBMISSION</span><b>DRAFT 04</b>
            </div>
            <div class="paper-depth" aria-hidden="true"></div>
            <article class="paper" aria-label="Editable student submission">
            <div class="paper-running-head"><span>ML / ST-402 / 04</span><span>FICTIONAL REVIEW PAPER</span><span>6 OF 12</span></div>
            <div class="paper-title"><span>SYSTEMATIC THEOLOGY · ESSAY IV</span><h2>Memory, Grace, and the Shape of Moral Attention</h2><p>Morgan Lee · submitted 18 May 2026</p></div>
            <div class="paper-body" contenteditable="false" spellcheck="false" data-paper-body role="document" aria-label="Current fictional submission under review">
              <p><span data-feature="syntax cadence">Memory is not merely an archive of what the soul has witnessed<mark data-feature="punctuation">;</mark> it is the chamber in which attention learns what it is prepared to love.</span> <span data-feature="lexical">Augustine’s account of recollection</span> therefore resists a simple division between knowledge and desire<mark data-feature="punctuation">.</mark> <span data-feature="transition">Indeed<mark data-feature="punctuation">,</mark></span> the remembered good becomes morally active precisely when it bends perception toward another person<mark data-feature="punctuation">—</mark>not as an object of judgment<mark data-feature="punctuation">,</mark> but as a neighbor whose life places a claim upon our own<mark data-feature="punctuation">.</mark></p>
              <p><span data-feature="syntax">This matters because moral attention is never exercised in abstraction<mark data-feature="punctuation">:</mark> it is formed through repeated encounters<mark data-feature="punctuation">,</mark> habits of naming<mark data-feature="punctuation">,</mark> and the patient correction of first impressions.</span> <span data-feature="citation">As Rowan Williams writes<mark data-feature="punctuation">,</mark> “the self is discovered in answerability”</span><mark data-feature="punctuation">;</mark> yet the paper’s earlier sources describe that answerability as though it were instantaneous<mark data-feature="punctuation">.</mark> <span data-feature="cadence">It is not<mark data-feature="punctuation">.</mark> It accumulates<mark data-feature="punctuation">.</mark> It returns<mark data-feature="punctuation">.</mark></span></p>
              <blockquote data-feature="citation lexical"><span class="quote-mark" aria-hidden="true">“</span><p>We carry the minds of all whom we have encountered<mark data-feature="punctuation">,</mark> not as possessions<mark data-feature="punctuation">,</mark> but as unfinished obligations<mark data-feature="punctuation">.</mark></p><cite><span>Field notes on Augustine</span><small>Seminar week seven</small></cite></blockquote>
              <p><span data-feature="transition">Consequently<mark data-feature="punctuation">,</mark></span> <span data-feature="syntax cadence">one must recognize the ontological distinction between remembering an injury and allowing that injury to govern the grammar of every subsequent encounter<mark data-feature="punctuation">;</mark> the former may be truthful<mark data-feature="punctuation">,</mark> while the latter quietly converts memory into fate.</span> Grace interrupts this conversion<mark data-feature="punctuation">.</mark> <span data-feature="lexical">It does not erase the past<mark data-feature="punctuation">;</mark> it restores contingency to the future.</span></p>
              <p><span data-feature="transition">For this reason<mark data-feature="punctuation">,</mark></span> Christian formation should be understood as a discipline of reordered noticing<mark data-feature="punctuation">.</mark> <span data-feature="citation">Scholarship establishes that liturgical repetition can reorganize moral perception</span><mark data-feature="punctuation">,</mark> but such a claim remains incomplete without attending to the ordinary textures of apology<mark data-feature="punctuation">,</mark> repair<mark data-feature="punctuation">,</mark> and shared work<mark data-feature="punctuation">.</mark> <span data-feature="syntax">The question is not whether memory persists<mark data-feature="punctuation">;</mark> the question is what kind of world our remembering permits us to see.</span></p>
            </div>
            <div class="paper-foot"><span data-active-overlay>PUNCTUATION LENS · 18 OBSERVATIONS</span><span>LOCAL DEMO · NO RECORD SAVED</span></div>
            <div class="difference-rail" data-difference-rail aria-hidden="true"></div>
            </article>
          </section>
          <section class="paper-column baseline-paper-column" aria-label="Baseline reference paper" aria-hidden="true">
            <div class="paper-context-bar baseline-context-bar">
              <span><i></i>BASELINE REFERENCE</span><b data-baseline-counter-secondary>PAPER 03 OF 03</b>
            </div>
            <div class="paper-depth" aria-hidden="true"></div>
            <article class="paper baseline-paper" aria-label="Selected baseline paper" aria-live="polite">
              <div class="paper-running-head"><span data-baseline-code>ML / ST-402 / 03</span><span>ILLUSTRATIVE BASELINE</span><span data-baseline-page>5 OF 12</span></div>
              <div class="paper-title"><span data-baseline-course>SYSTEMATIC THEOLOGY · ESSAY III</span><h2 data-baseline-title>The Discipline of Attention</h2><p data-baseline-meta>Morgan Lee · submitted 02 April 2026</p></div>
              <div class="paper-body baseline-paper-body" data-baseline-body></div>
              <div class="paper-foot"><span data-baseline-lens>PUNCTUATION LENS · BASELINE CONTEXT</span><span data-baseline-date>ILLUSTRATIVE · 02 APR 2026</span></div>
            </article>
          </section>
          </div>
          <div class="selection-tools glass-panel" data-selection-tools hidden><button data-add-note>＋ Note</button><button data-explain-selection>✦ Explain</button></div>
        </div>
      </div>

      <aside class="feature-inspector glass-panel" aria-live="polite">
        <div class="inspector-hero"><span data-inspector-index>FEATURE 038 / 103</span><div class="inspector-glyph" data-inspector-glyph>;</div><small data-inspector-state>REVIEW SIGNAL</small><h2 data-inspector-title>Semicolon &amp; colon use</h2><p data-inspector-copy>These marks appear more often than in the illustrative baseline and cluster in the argument’s most abstract passages.</p><div class="interpretive-limit"><b>CONTEXT, NOT PROOF</b><span>Use this observation to guide review and conversation—never as an automatic verdict.</span></div></div>
        <div class="comparison-orbit" data-position-state="outside">
          <div class="comparison-head"><span>FEATURE POSITION</span><b data-deviation-badge>+2.1σ</b></div>
          <div class="comparison-values">
            <div class="current-readout"><span>CURRENT RATE</span><div><strong data-current-value>18.4</strong><small data-current-unit>PER 1,000 WORDS</small></div></div>
            <div class="baseline-readout"><span>ILLUSTRATIVE BASELINE RANGE</span><b data-baseline-value>8.6—12.9</b><small data-delta-value>outside usual range</small></div>
          </div>
          <div class="position-scale" data-deviation-scale role="img" aria-label="Current punctuation usage is above the established range">
            <div class="position-track"><span class="baseline-corridor"></span><i class="current-pin"></i></div>
            <div class="scale-labels"><span>LOWER</span><b>EXPECTED BAND</b><span>HIGHER</span></div>
          </div>
          <div class="comparison-caption"><i></i><span data-position-caption>Current usage sits beyond Morgan’s expected range.</span></div>
        </div>
        <div class="passage-inspector" data-passage-inspector role="region" aria-live="polite" aria-label="Highlighted passage comparison">
          <div class="passage-inspector-empty" data-passage-empty>
            <div class="inspector-label"><span>PASSAGE LENS</span><b>HOVER TO COMPARE</b></div>
            <div class="passage-empty-cue"><i>↔</i><div><b>Inspect the writing in context</b><span>Hover any colored passage to compare its behavior with the selected baseline.</span></div></div>
          </div>
          <div class="passage-inspector-live" data-passage-live hidden>
            <div class="passage-preview-head"><span><i data-hover-glyph>;</i><b data-hover-feature>Punctuation usage</b></span><em data-hover-state>MEANINGFUL SHIFT</em></div>
            <div class="passage-compare-grid">
              <article class="passage-sample current-sample"><header><span>CURRENT</span><b data-hover-current-value>18.4</b></header><q data-hover-current></q><small>Observed in this submission</small></article>
              <article class="passage-sample baseline-sample"><header><span>BASELINE</span><b data-hover-baseline-value>8.6—12.9</b></header><q data-hover-baseline></q><small data-hover-baseline-paper>PAPER 03 · ILLUSTRATIVE</small></article>
            </div>
            <div class="passage-explanation"><i></i><p data-hover-explanation></p></div>
          </div>
        </div>
        <div class="correlation-detail"><div class="inspector-label"><span>CORRELATES WITH</span><b data-correlation-strength>r = 0.72</b></div><button data-correlate="syntax"><i></i><span><b data-related-one>Sentence architecture</b><small>shared clause-boundary behavior</small></span><em>72%</em></button><button data-correlate="cadence"><i></i><span><b data-related-two>Cadence & pacing</b><small>sentence-ending rhythm</small></span><em>58%</em></button></div>
        <div class="evidence-note"><span>WHY IT MATTERS</span><p data-inspector-why>Punctuation is a low-level writing habit. A clustered change is useful context, but it is not independent proof of authorship.</p><button data-pin-evidence>◇ Pin illustrative observation</button></div>
      </aside>
      <div class="mark-tooltip glass-panel" data-mark-tooltip hidden></div>
    </section>`,'editor');
}

const views={overview,constellation,pulse,temporal,editor:documentEditor,case:caseView};
function render(view='overview') {
  if (activeEngine) { activeEngine.destroy(); activeEngine = null; }
  document.getElementById('app').innerHTML=views[view]();
  document.querySelector('main')?.scrollTo({ top:0, left:0, behavior:'auto' });
  bind();
  const canvas = document.querySelector('.constellation-canvas');
  if (canvas) {
    let selectedSignal = 's1';
    const systemButton = document.querySelector('[data-enter-system]');
    const syncSystemButton = (id) => {
      const detail = SIGNAL_DETAILS[id];
      if (systemButton && detail) systemButton.querySelector('[data-system-title]').textContent = detail.title;
      selectedSignal = id;
    };
    canvas.addEventListener('signalchange', event => { updateSignalPanel(event); syncSystemButton(event.detail.id); });
    systemButton?.addEventListener('click', () => { pulseEntryCluster = SIGNAL_SYSTEMS[selectedSignal] || 'authorship'; render('pulse'); });
    activeEngine = new ConstellationEngine(canvas, DATA);
  }
  const pulseCanvas = document.querySelector('.pulse-canvas');
  if (pulseCanvas) {
    activeEngine = new NetworkPulseEngine(pulseCanvas, { initialCluster:pulseEntryCluster });
    pulseEntryCluster = null;
  }
  const temporalSvg = document.querySelector('.temporal-svg');
  if (temporalSvg) activeEngine = new TemporalIntelligence(temporalSvg);
  const editorShell = document.querySelector('.editor-shell');
  if (editorShell) {
    activeEngine = new DocumentIntelligence(editorShell);
    if (editorEntryFeature && typeof activeEngine.selectCatalogFeature === 'function') {
      activeEngine.selectCatalogFeature(editorEntryFeature);
      editorEntryFeature = null;
    }
  }
}
function bindViewLinks(){
  document.querySelectorAll('[data-view]:not([data-view-bound])').forEach(el=>{
    el.dataset.viewBound='true';
    el.addEventListener('click',()=>render(el.dataset.view));
  });
}
function bind(){
  bindViewLinks();
  document.querySelectorAll('[data-editor-feature]').forEach(el=>el.addEventListener('click',()=>{
    editorEntryFeature=el.dataset.editorFeature;
    render('editor');
  }));
  document.querySelectorAll('[data-catalog-mode]').forEach(el=>el.addEventListener('click',()=>{
    const next=el.dataset.catalogMode;
    if(next===professorCatalogMode)return;
    professorCatalogMode=next;
    render('editor');
  }));
  document.querySelectorAll('.choice').forEach(el=>el.addEventListener('click',()=>{
    document.querySelectorAll('.choice').forEach(n=>{n.classList.remove('selected');n.setAttribute('aria-pressed','false')});
    el.classList.add('selected');el.setAttribute('aria-pressed','true');
  }));
  document.querySelector('[data-build-brief]')?.addEventListener('click',()=>{
    const brief=document.querySelector('[data-conversation-brief]');
    const selected=document.querySelector('.choice.selected')?.dataset.caseAction||'conversation';
    const titles={conversation:'Begin with the student’s process',sample:'Request a short, low-stakes writing sample',clear:'Document the review and close the case'};
    const title=brief?.querySelector('h3');if(title)title.textContent=titles[selected];
    if(brief){brief.hidden=false;brief.scrollIntoView({block:'nearest',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'})}
  });
  document.querySelector('[data-close-brief]')?.addEventListener('click',()=>{const brief=document.querySelector('[data-conversation-brief]');if(brief)brief.hidden=true});
  document.querySelector('[data-save-case]')?.addEventListener('click',()=>{
    const feedback=document.querySelector('[data-case-feedback]');
    if(feedback)feedback.textContent='Demo choice held in this tab only · no institutional record saved.';
  });
}
render();

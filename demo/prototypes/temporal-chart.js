const NS='http://www.w3.org/2000/svg';
const MODES={
  activity:{title:'Illustrative submission outcomes',kicker:'18-WEEK DEMONSTRATION',note:'Illustrative data: each submission appears in exactly one outcome state.',keys:[['aligned','Within expected range','#329b9c'],['developing','Developing baseline','#9255c4'],['review','Review suggested','#5f6d6f'],['conversation','Conversation suggested','#c9a568']]},
  readiness:{title:'Illustrative profile maturity',kicker:'BASELINE FORMATION · DEMO',note:'Illustrative readiness reflects sample count, diversity, and longitudinal stability.',keys:[['insufficient','Insufficient','#66757a'],['forming','Developing','#9b72d2'],['ready','Ready','#d7a94c'],['longitudinal','Longitudinal','#67c995']]},
  workflow:{title:'Illustrative faculty workflow',kicker:'FACULTY WORKFLOW · DEMO',note:'Illustrative workflow states describe instructor activity—not authorship conclusions.',keys:[['awaiting','Awaiting review','#d7a94c'],['reviewed','Reviewed','#59c5c7'],['sample','Sample requested','#9b72d2'],['resolved','Resolved','#67c995']]},
  evidence:{title:'Illustrative evidence-family activity',kicker:'EVIDENCE SIGNALS · DEMO',note:'Illustrative counts: one submission may contribute to multiple evidence families.',keys:[['syntax','Sentence architecture','#59c5c7'],['citation','Citation practice','#d7a94c'],['rhythm','Paragraph rhythm','#9b72d2'],['vocabulary','Vocabulary continuity','#67c995']]}
};
function seeded(seed=7319){return()=>((seed=(seed*16807)%2147483647)-1)/2147483646}
function makeData(){const rnd=seeded();const labels=['JAN 12','JAN 19','JAN 26','FEB 2','FEB 9','FEB 16','FEB 23','MAR 2','MAR 9','MAR 16','MAR 23','APR 6','APR 13','APR 20','APR 27','MAY 4','MAY 11','MAY 18'];return labels.map((label,i)=>{const wave=Math.sin((i-3)*.34)*13,base=64+i*2.2+wave+rnd()*10;return{label,full:`${label} – ${labels[Math.min(i+1,17)]}`,activity:{aligned:Math.round(base*.69),developing:Math.round(base*.17),review:Math.round(base*.1),conversation:Math.max(2,Math.round(base*.04))},readiness:{insufficient:Math.max(4,30-i),forming:30+Math.round(Math.sin(i*.4)*5),ready:38+i*3,longitudinal:8+Math.floor(i*.8)},workflow:{awaiting:7+Math.round(rnd()*9),reviewed:12+Math.round(i*.6+rnd()*8),sample:2+Math.round(rnd()*5),resolved:8+Math.round(i*.55+rnd()*6)},evidence:{syntax:8+Math.round(rnd()*13),citation:6+Math.round(rnd()*10)+(i===14?13:0),rhythm:5+Math.round(rnd()*9),vocabulary:4+Math.round(rnd()*8)},anomaly:[11,14,17].includes(i)}})}
function aggregateMode(data,mode){return Object.fromEntries(MODES[mode].keys.map(([key])=>[key,data.reduce((sum,row)=>sum+row[mode][key],0)]))}
function sumValues(record){return Object.values(record).reduce((sum,value)=>sum+value,0)}
export function summarizeTemporalData(data=makeData()){
  const activity=aggregateMode(data,'activity');
  const workflow=aggregateMode(data,'workflow');
  const evidence=aggregateMode(data,'evidence');
  const readiness={...data.at(-1).readiness};
  const readinessTotal=sumValues(readiness);
  return Object.freeze({
    dataMode:'illustrative-prototype',
    weeks:data.length,
    submissions:sumValues(activity),
    activity:Object.freeze(activity),
    readiness:Object.freeze({...readiness,total:readinessTotal,readyPercent:Math.round((readiness.ready+readiness.longitudinal)/readinessTotal*100)}),
    workflow:Object.freeze({...workflow,total:sumValues(workflow)}),
    evidence:Object.freeze({...evidence,total:sumValues(evidence)})
  });
}
function el(name,attrs={}){const node=document.createElementNS(NS,name);Object.entries(attrs).forEach(([k,v])=>node.setAttribute(k,String(v)));return node}
export class TemporalIntelligence{
  constructor(svg){
    this.svg=svg;this.host=svg.closest('.temporal-main');this.shell=svg.closest('.temporal-shell');this.data=makeData();this.summary=summarizeTemporalData(this.data);this.mode='activity';this.selected=13;this.compare=null;this.playing=false;this.resumeAfterVisibility=false;this.timer=null;this.tooltipTimer=null;this.hoveredColumn=null;this.cinemaTimers=[];this.abort=new AbortController();this.motionQuery=matchMedia('(prefers-reduced-motion: reduce)');this.reduceMotion=this.motionQuery.matches;
    this.motionChange=event=>{this.reduceMotion=event.matches;if(this.reduceMotion)this.setPlaying(false);this.syncMotionControls()};
    this.visibilityChange=()=>this.handleVisibility();
    this.bind();this.bindDepth();
    this.shell?.querySelector('[data-cinematic]')?.addEventListener('click',()=>this.cinematicTour(),{signal:this.abort.signal});
    this.resizeObserver=new ResizeObserver(()=>this.draw());this.resizeObserver.observe(svg.parentElement);
    this.syncSummary();this.syncCopy();this.draw();this.updateAnalyst();this.syncMotionControls();
    this.motionQuery.addEventListener?.('change',this.motionChange);
  }
  bind(){
    const opts={signal:this.abort.signal},root=this.shell||document;
    root.querySelectorAll('[data-temporal-mode]').forEach(button=>button.addEventListener('click',()=>{
      this.mode=button.dataset.temporalMode;this.compare=null;this.syncCopy();this.draw();this.updateAnalyst();
    },opts));
    root.querySelector('[data-playback]')?.addEventListener('click',()=>this.togglePlay(),opts);
    root.querySelector('[data-compare]')?.addEventListener('click',()=>{this.compare=this.compare==null?Math.max(0,this.selected-4):null;this.draw();this.updateAnalyst()},opts);
    root.querySelector('[data-period-scrubber]')?.addEventListener('input',event=>this.selectPeriod(Number(event.target.value)),opts);
    root.querySelectorAll('[data-marker]').forEach(button=>button.addEventListener('click',()=>this.selectPeriod(Number(button.dataset.marker)),opts));
    root.querySelector('[data-inspect]')?.addEventListener('click',()=>{this.compare=Math.max(0,this.selected-4);this.draw()},opts);
    document.addEventListener('visibilitychange',this.visibilityChange,opts);
  }
  syncSummary(){
    const root=this.shell||document;
    const summary=this.summary;
    const values={
      activity:[summary.submissions,`${summary.weeks}-week illustration`],
      readiness:[`${summary.readiness.readyPercent}%`,`${summary.readiness.ready+summary.readiness.longitudinal} of ${summary.readiness.total} profiles`],
      workflow:[summary.workflow.reviewed,`${summary.workflow.reviewed} reviewed · ${summary.workflow.resolved} resolved`],
      evidence:[summary.evidence.total,'across 4 evidence families']
    };
    if(root.dataset)root.dataset.temporalData='illustrative-prototype';
    root.querySelectorAll('[data-temporal-mode]').forEach(button=>{
      const [value,detail]=values[button.dataset.temporalMode]||[];
      if(value==null)return;
      const strong=button.querySelector('strong'),small=button.querySelector('small');
      if(strong)strong.textContent=Number.isFinite(value)?value.toLocaleString():value;
      if(small)small.textContent=detail;
    });
    root.querySelectorAll('.details-card dl div').forEach(row=>{
      if(row.querySelector('dt')?.textContent.trim()==='Submissions analyzed')row.querySelector('dd').textContent=summary.submissions.toLocaleString();
    });
    const expectedPercent=Math.round(summary.activity.aligned/summary.submissions*100);
    const developingPercent=Math.round(summary.activity.developing/summary.submissions*100);
    const reviewPercent=100-expectedPercent-developingPercent;
    const consistency=root.querySelector('.stability-score>strong');
    if(consistency?.firstChild)consistency.firstChild.nodeValue=String(expectedPercent);
    const stabilityDetails=root.querySelectorAll('.stability-detail>div');
    if(stabilityDetails[1])stabilityDetails[1].innerHTML=`<span>Review context</span><b>${(summary.activity.review+summary.activity.conversation).toLocaleString()} suggested</b>`;
    if(stabilityDetails[2])stabilityDetails[2].innerHTML=`<span>Profiles ready</span><b>${summary.readiness.ready+summary.readiness.longitudinal} / ${summary.readiness.total}</b>`;
    const distributionTotal=root.querySelector('.sentiment-dial .half-donut strong');
    const distributionCopy=root.querySelector('.sentiment-dial .half-donut small');
    if(distributionTotal)distributionTotal.textContent=summary.submissions.toLocaleString();
    if(distributionCopy)distributionCopy.textContent='illustrative submission outcomes';
    const distributionValues=root.querySelectorAll('.dial-legend b');
    [expectedPercent,developingPercent,reviewPercent].forEach((value,index)=>{if(distributionValues[index])distributionValues[index].textContent=`${value}%`});
    const workflowCards=root.querySelectorAll('.engagement-grid>div');
    const updateWorkflowCard=(card,label,value,detail)=>{if(!card)return;const small=card.querySelector('small'),strong=card.querySelector('b'),em=card.querySelector('em');if(small)small.textContent=label;if(strong)strong.textContent=value;if(em)em.textContent=detail};
    updateWorkflowCard(workflowCards[0],'Reviews opened',summary.workflow.reviewed.toLocaleString(),`${summary.weeks} weeks`);
    updateWorkflowCard(workflowCards[1],'Conversation suggested',summary.activity.conversation.toLocaleString(),'not a verdict');
    updateWorkflowCard(workflowCards[2],'Baselines ready',String(summary.readiness.ready+summary.readiness.longitudinal),`of ${summary.readiness.total} profiles`);
    updateWorkflowCard(workflowCards[3],'Cases resolved',summary.workflow.resolved.toLocaleString(),'illustrative workflow');
    const readiness=root.querySelector('.execution-card>div:nth-child(2) strong');
    if(readiness)readiness.textContent=`${summary.readiness.readyPercent}%`;
    const readinessPeriod=root.querySelector('.execution-card .panel-label b');
    if(readinessPeriod)readinessPeriod.textContent=`${summary.readiness.ready+summary.readiness.longitudinal} / ${summary.readiness.total}`;
    this.svg.dispatchEvent(new CustomEvent('temporal:summary',{bubbles:true,detail:summary}));
  }
  syncCopy(){
    const mode=MODES[this.mode],root=this.shell||document;
    root.querySelector('[data-chart-title]').textContent=mode.title;
    root.querySelector('[data-chart-kicker]').textContent=mode.kicker;
    root.querySelector('[data-mode-note]').textContent=mode.note;
    root.querySelectorAll('[data-temporal-mode]').forEach(button=>{
      const active=button.dataset.temporalMode===this.mode;
      button.classList.toggle('active',active);
      button.setAttribute('aria-pressed',String(active));
    });
  }
  totals(row){return MODES[this.mode].keys.reduce((sum,[key])=>sum+row[this.mode][key],0)}
  selectPeriod(index,{focus=false}={}){
    this.selected=Math.max(0,Math.min(this.data.length-1,index));
    const scrubber=this.shell?.querySelector('[data-period-scrubber]');
    if(scrubber)scrubber.value=String(this.selected);
    this.draw();this.updateAnalyst();
    if(focus)requestAnimationFrame(()=>this.svg.querySelector(`.chart-column[data-index="${this.selected}"]`)?.focus());
  }
  renderDataTable(){
    const table=this.shell?.querySelector('[data-temporal-table]');
    if(!table)return;
    const mode=MODES[this.mode];
    const caption=document.createElement('caption');caption.textContent=`${mode.title}. Illustrative ${this.summary.weeks}-week dataset.`;
    const head=document.createElement('thead');const headRow=document.createElement('tr');
    ['Period',...mode.keys.map(([,label])=>label),'Total'].forEach(label=>{const cell=document.createElement('th');cell.scope='col';cell.textContent=label;headRow.append(cell)});head.append(headRow);
    const body=document.createElement('tbody');
    this.data.forEach((row,index)=>{const tr=document.createElement('tr');if(index===this.selected)tr.dataset.selected='true';const period=document.createElement('th');period.scope='row';period.textContent=row.full;tr.append(period);mode.keys.forEach(([key])=>{const cell=document.createElement('td');cell.textContent=String(row[this.mode][key]);tr.append(cell)});const total=document.createElement('td');total.textContent=String(this.totals(row));tr.append(total);body.append(tr)});
    table.replaceChildren(caption,head,body);
  }
  draw(){
    const box=this.svg.parentElement.getBoundingClientRect(),w=Math.max(520,box.width),h=Math.max(400,box.height);this.w=w;this.h=h;
    this.svg.setAttribute('viewBox',`0 0 ${w} ${h}`);
    this.svg.setAttribute('aria-label',`${MODES[this.mode].title}; illustrative ${this.summary.weeks}-week data. Period ${this.selected+1} of ${this.data.length} is selected.`);
    this.svg.setAttribute('aria-activedescendant',`temporal-period-${this.selected}`);
    this.svg.innerHTML='';
    const defs=el('defs');
    MODES[this.mode].keys.forEach(([key,,color])=>{const gradient=el('linearGradient',{id:`bar-${key}`,x1:0,y1:0,x2:1,y2:0});gradient.append(el('stop',{offset:0,'stop-color':color,'stop-opacity':.72}),el('stop',{offset:.55,'stop-color':color,'stop-opacity':.98}),el('stop',{offset:1,'stop-color':color,'stop-opacity':.48}));defs.append(gradient)});
    this.svg.append(defs);
    const margin={l:62,r:22,t:32,b:58},chartWidth=w-margin.l-margin.r,chartHeight=h-margin.t-margin.b,max=Math.max(...this.data.map(row=>this.totals(row)))*1.14;
    for(let index=0;index<=5;index+=1){const y=margin.t+chartHeight-index*chartHeight/5;this.svg.append(el('line',{x1:margin.l,y1:y,x2:w-margin.r,y2:y,class:'chart-grid'}));const text=el('text',{x:margin.l-12,y:y+4,class:'axis-label','text-anchor':'end'});text.textContent=Math.round(max*index/5);this.svg.append(text)}
    const step=chartWidth/this.data.length,barWidth=Math.max(12,step*.58);
    this.data.forEach((row,index)=>{
      const x=margin.l+index*step+(step-barWidth)/2;
      const values=MODES[this.mode].keys.map(([key,label])=>`${label}: ${row[this.mode][key]}`).join(', ');
      const group=el('g',{id:`temporal-period-${index}`,class:`chart-column${index===this.selected?' selected':''}`,'data-index':index,tabindex:index===this.selected?0:-1,role:'button','aria-pressed':index===this.selected,'aria-label':`${row.full}, ${this.totals(row)} illustrative total. ${values}`});
      if(index===this.selected)group.append(el('rect',{x:x-7,y:margin.t,width:barWidth+14,height:chartHeight,class:'selection-slab'}));
      if(index===this.compare)group.append(el('rect',{x:x-4,y:margin.t+chartHeight-(this.totals(row)/max)*chartHeight,width:barWidth+8,height:(this.totals(row)/max)*chartHeight,class:'compare-outline'}));
      let bottom=margin.t+chartHeight;
      MODES[this.mode].keys.forEach(([key])=>{const value=row[this.mode][key],height=value/max*chartHeight;bottom-=height;group.append(el('rect',{x,y:bottom,width:barWidth,height:Math.max(1,height-.8),fill:`url(#bar-${key})`,class:'bar-segment'}));group.append(el('line',{x1:x+1,y1:bottom+.5,x2:x+barWidth-1,y2:bottom+.5,class:'bar-cap'}))});
      if(row.anomaly){const marker=el('g',{class:'anomaly-marker'});marker.append(el('circle',{cx:x+barWidth/2,cy:Math.max(12,bottom-11),r:4}));marker.append(el('line',{x1:x+barWidth/2,y1:Math.max(16,bottom-7),x2:x+barWidth/2,y2:bottom-2}));group.append(marker)}
      if(index%3===0||index===this.data.length-1){const label=el('text',{x:x+barWidth/2,y:h-25,class:'x-label','text-anchor':'middle'});label.textContent=row.label.split(' ')[0];group.append(label)}
      group.addEventListener('pointerenter',event=>this.showTooltip(index,event));
      group.addEventListener('pointerleave',()=>this.hideTooltip());
      group.addEventListener('click',()=>this.selectPeriod(index,{focus:true}));
      group.addEventListener('keydown',event=>{
        const target=event.key==='ArrowRight'?Math.min(this.data.length-1,index+1):event.key==='ArrowLeft'?Math.max(0,index-1):event.key==='Home'?0:event.key==='End'?this.data.length-1:null;
        if(target!==null){event.preventDefault();this.selectPeriod(target,{focus:true});return}
        if(event.key==='Enter'||event.key===' '){event.preventDefault();this.selectPeriod(index,{focus:true})}
      });
      this.svg.append(group);
    });
    this.drawLandscape(w,h,margin);this.renderLegend();this.renderDataTable();
  }
  drawLandscape(w,h,m){const path=el('path',{d:`M${m.l} ${h-7} L${m.l+70} ${h-18} L${m.l+120} ${h-10} L${m.l+180} ${h-27} L${m.l+250} ${h-13} L${m.l+320} ${h-21} L${m.l+390} ${h-8} L${w-m.r} ${h-16} L${w-m.r} ${h} L${m.l} ${h}Z`,class:'chart-landscape'});this.svg.append(path)}
  renderLegend(){const root=this.shell?.querySelector('[data-chart-legend]');if(root)root.innerHTML=MODES[this.mode].keys.map(([,label,color])=>`<span><i style="--legend:${color}"></i>${label}</span>`).join('');this.enhanceDepth();requestAnimationFrame(()=>this.pinTooltip())}
  enhanceDepth(){const colors=MODES[this.mode].keys.map(([, ,color])=>color);this.svg.querySelectorAll('.chart-column').forEach(group=>{const rects=[...group.querySelectorAll('.bar-segment')];rects.forEach((rect,index)=>{const x=Number(rect.getAttribute('x')),y=Number(rect.getAttribute('y')),w=Number(rect.getAttribute('width')),h=Number(rect.getAttribute('height')),d=Math.max(2.4,Math.min(4,w*.22)),color=colors[index%colors.length];const side=el('polygon',{points:`${x+w},${y} ${x+w+d},${y-d} ${x+w+d},${y+h-d} ${x+w},${y+h}`,fill:color,class:'bar-side-face'});const top=el('polygon',{points:`${x},${y} ${x+d},${y-d} ${x+w+d},${y-d} ${x+w},${y}`,fill:color,class:'bar-top-face'});rect.after(side);side.after(top)});if(rects.length){const first=rects[0],x=Number(first.getAttribute('x')),w=Number(first.getAttribute('width')),floor=Math.max(...rects.map(r=>Number(r.getAttribute('y'))+Number(r.getAttribute('height')))),d=Math.max(2.4,Math.min(4,w*.22));const base=el('polygon',{points:`${x-2},${floor} ${x+d},${floor-d} ${x+w+d+2},${floor-d} ${x+w+2},${floor}`,class:'column-foot'});group.insertBefore(base,group.firstChild)}})}
  bindDepth(){const stage=this.svg.parentElement;if(this.reduceMotion)return;const opts={signal:this.abort.signal};stage.addEventListener('pointermove',e=>{const r=stage.getBoundingClientRect(),nx=(e.clientX-r.left)/r.width-.5,ny=(e.clientY-r.top)/r.height-.5;stage.style.setProperty('--chart-ry',`${nx*2.2}deg`);stage.style.setProperty('--chart-rx',`${ny*-1.5}deg`);stage.style.setProperty('--light-x',`${50+nx*18}%`)},opts);stage.addEventListener('pointerleave',()=>{stage.style.setProperty('--chart-ry','0deg');stage.style.setProperty('--chart-rx','0deg');stage.style.setProperty('--light-x','64%')},opts)}
  pinTooltip(){if(this.hoveredColumn!==null)return;const column=this.svg.querySelector(`.chart-column[data-index="${this.selected}"]`);if(!column)return;const r=column.getBoundingClientRect();this.showTooltip(this.selected,{clientX:r.left+r.width/2,clientY:r.top+Math.min(75,r.height*.22)},true)}
  showTooltip(i,e,pinned=false){clearTimeout(this.tooltipTimer);if(!pinned)this.hoveredColumn=i;const row=this.data[i],tip=this.shell?.querySelector('[data-chart-tooltip]'),m=MODES[this.mode];if(!tip)return;tip.innerHTML=`<header><span>${row.full}</span><b>${this.totals(row)} total</b></header>${m.keys.map(([key,label,color])=>`<div><i style="--tip:${color}"></i><span>${label}</span><b>${row[this.mode][key]}</b><small>${Math.round(row[this.mode][key]/this.totals(row)*100)}%</small></div>`).join('')}<footer>${row.anomaly?'◆ Illustrative context marker':'Compared with the illustrative period'}</footer>`;tip.hidden=false;const stage=this.svg.parentElement.getBoundingClientRect();tip.style.left=`${Math.max(10,Math.min(stage.width-268,e.clientX-stage.left+12))}px`;tip.style.top=`${Math.max(10,Math.min(stage.height-220,e.clientY-stage.top-50))}px`}
  hideTooltip(){this.hoveredColumn=null;clearTimeout(this.tooltipTimer);this.tooltipTimer=setTimeout(()=>{if(this.hoveredColumn===null)this.pinTooltip()},90)}
  updateAnalyst(){const row=this.data[this.selected],total=this.totals(row),copy={activity:['ILLUSTRATIVE RATE','Review suggestions remain proportional to submission volume.',`In this illustration, ${row.full} contains ${total} submissions. The categories are workflow context, not authorship conclusions.`,`${row.activity.review} review suggested`,`${Math.round(row.activity.conversation/total*100)}% conversation suggested`],readiness:['ILLUSTRATIVE FORMATION','Baseline profiles continue to mature.','In this illustration, ready and longitudinal profiles make up the majority of the latest-week comparison set.',`${row.readiness.ready} ready profiles`,`${row.readiness.longitudinal} longitudinal`],workflow:['ILLUSTRATIVE WORKLOAD','Faculty resolution keeps pace with review work.','In this illustration, resolved and reviewed cases remain balanced against the incoming review queue.',`${row.workflow.reviewed} reviewed`,`${row.workflow.resolved} resolved`],evidence:['ILLUSTRATIVE CONTEXT','Signals concentrate in specific evidence families.','Illustrative signal counts identify features for inspection; they are not independent authorship conclusions.',`${row.evidence.syntax} sentence signals`,`${row.evidence.citation} citation signals`]}[this.mode],root=this.shell||document;const values={'[data-analyst-tag]':copy[0],'[data-analyst-title]':copy[1],'[data-analyst-copy]':copy[2],'[data-fact-one]':copy[3],'[data-fact-two]':copy[4]};Object.entries(values).forEach(([selector,value])=>{const element=root.querySelector(selector);if(element)element.textContent=value})}
  syncMotionControls(){
    const button=this.shell?.querySelector('[data-playback]');
    if(!button)return;
    button.disabled=this.reduceMotion;
    button.setAttribute('aria-disabled',String(this.reduceMotion));
    button.textContent=this.reduceMotion?'—':this.playing?'Ⅱ':'▶';
    button.setAttribute('aria-label',this.reduceMotion?'Timeline playback disabled by reduced-motion preference':this.playing?'Pause timeline':'Play timeline');
  }
  setPlaying(next){
    const allowed=Boolean(next)&&!this.reduceMotion&&!document.hidden;
    this.playing=allowed;clearInterval(this.timer);this.timer=null;this.syncMotionControls();
    if(this.playing)this.timer=setInterval(()=>this.selectPeriod((this.selected+1)%this.data.length),900);
  }
  togglePlay(){this.setPlaying(!this.playing)}
  stopCinematic(){
    this.cinemaTimers.forEach(clearTimeout);this.cinemaTimers=[];
    if(this.shell)this.shell.className='temporal-shell';
    const button=this.shell?.querySelector('[data-cinematic]');if(button)button.textContent='◉ Guided explanation';
  }
  handleVisibility(){
    if(document.hidden){this.resumeAfterVisibility=this.playing;this.setPlaying(false);this.stopCinematic();return}
    if(this.resumeAfterVisibility){this.resumeAfterVisibility=false;this.setPlaying(true)}
  }
  cinematicTour(){
    const shell=this.shell;if(!shell)return;const button=shell.querySelector('[data-cinematic]');this.stopCinematic();
    if(this.reduceMotion){this.selectPeriod(Math.min(this.data.length-1,this.selected+1));if(button)button.textContent='Guided view · updated';return}
    shell.className='temporal-shell cinema-active scene-left';if(button)button.textContent='● Playing';
    const scene=(name,delay)=>this.cinemaTimers.push(setTimeout(()=>{shell.className=`temporal-shell cinema-active ${name}`},delay));
    scene('scene-chart',1500);scene('scene-right',3300);scene('scene-chart',4850);
    this.cinemaTimers.push(setTimeout(()=>this.stopCinematic(),6500));
  }
  destroy(){clearInterval(this.timer);clearTimeout(this.tooltipTimer);this.cinemaTimers.forEach(clearTimeout);this.resizeObserver?.disconnect();this.motionQuery.removeEventListener?.('change',this.motionChange);this.abort.abort()}
}

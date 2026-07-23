const TAU = Math.PI * 2;

const PALETTE = {
  core: '#d5f36f', gold: '#d7a94c', risk: '#ec786b', safe: '#67c995', muted: '#7c8982'
};

function clamp(v, min, max) { return Math.max(min, Math.min(max, v)); }
function lerp(a, b, t) { return a + (b - a) * t; }
function ease(t) { return t * t * (3 - 2 * t); }
function hexRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export class ConstellationEngine {
  constructor(canvas, data) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d', { alpha: true });
    this.host = canvas.closest('.graph');
    this.nodes = this.makeNodes(data.nodes);
    this.edgeIds = data.edges;
    this.edges = data.edges.map(([a, b], index) => ({ a: this.nodes.find(n => n.id === a), b: this.nodes.find(n => n.id === b), phase: index * 1.71 }));
    this.particles = this.makeParticles(110);
    this.signalParticles = this.makeSignals(30);
    this.time = .72;
    this.targetTime = .72;
    this.yaw = -.28;
    this.pitch = -.12;
    this.targetYaw = this.yaw;
    this.targetPitch = this.pitch;
    this.zoom = 1;
    this.targetZoom = 1;
    // Professor demonstrations begin from a stable, explainable frame. Motion
    // remains available on demand and the 4D slider/orbit controls still work.
    this.motion = false;
    this.drag = null;
    this.hovered = null;
    this.selected = this.nodes.find(node => node.id === 's1') || this.nodes[0];
    this.pointer = { x: -1000, y: -1000 };
    this.motionQuery = matchMedia('(prefers-reduced-motion: reduce)');
    this.reduceMotion = this.motionQuery.matches;
    this.pageVisible = !document.hidden;
    this.inViewport = true;
    this.last = performance.now();
    this.lastRender = 0;
    this.frame = 0;
    this.bind();
    this.resize();
    this.updateReadout();
    this.loop = this.loop.bind(this);
    this.raf = null;
    this.syncLoop();
  }

  makeNodes(source) {
    const positions = {
      s:[0,0,0,0], b:[-1.75,-.7,-.8,-.6], s1:[1.45,-1.05,.35,.9], v:[1.85,.45,-.55,-.15],
      c:[.85,1.45,.62,.65], r:[-1.35,1.2,.32,-.35], p:[-2.25,.25,.8,-.75]
    };
    return source.map((n, i) => ({
      ...n, p: positions[n.id] || [Math.cos(i)*1.8, Math.sin(i)*1.8, 0, 0],
      pulse: i * .82, baseSize: n.kind === 'core' ? 26 : n.r * .68,
      trail: []
    }));
  }

  makeParticles(count) {
    let seed = 9173;
    const random = () => ((seed = (seed * 16807) % 2147483647) - 1) / 2147483646;
    return Array.from({ length: count }, () => ({
      x:(random()-.5)*7, y:(random()-.5)*5, z:(random()-.5)*5, w:(random()-.5)*2,
      size:.25+random()*1.15, alpha:.08+random()*.42, phase:random()*TAU
    }));
  }

  makeSignals(count) {
    return Array.from({ length: count }, (_, i) => ({
      edge: i % this.edgeIds.length, offset: (i * .173) % 1, speed: .035 + (i % 7) * .006
    }));
  }

  bind() {
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(this.host);
    this.onMove = e => this.pointerMove(e);
    this.onDown = e => { this.drag = { x:e.clientX, y:e.clientY, yaw:this.targetYaw, pitch:this.targetPitch }; this.canvas.setPointerCapture(e.pointerId); };
    this.onUp = e => { if (this.drag && Math.hypot(e.clientX-this.drag.x,e.clientY-this.drag.y)<5) this.pick(e); this.drag = null; };
    this.onWheel = e => { e.preventDefault(); this.targetZoom = clamp(this.targetZoom * (e.deltaY > 0 ? .9 : 1.1), .62, 1.85); };
    this.canvas.addEventListener('pointermove', this.onMove);
    this.canvas.addEventListener('pointerdown', this.onDown);
    this.canvas.addEventListener('pointerup', this.onUp);
    this.canvas.addEventListener('pointerleave', () => { this.hovered = null; });
    this.canvas.addEventListener('wheel', this.onWheel, { passive:false });
    this.range = this.host.querySelector('[data-time-axis]');
    this.timeReadout = this.host.querySelector('[data-time-readout]');
    this.range?.addEventListener('input', e => { this.targetTime = Number(e.target.value)/100; });
    this.host.querySelectorAll('[data-camera]').forEach(button => button.addEventListener('click', () => {
      const action = button.dataset.camera;
      if (action === 'reset') { this.targetYaw=-.28; this.targetPitch=-.12; this.targetZoom=1; }
      if (action === 'in') this.targetZoom=clamp(this.targetZoom*1.15,.62,1.85);
      if (action === 'out') this.targetZoom=clamp(this.targetZoom*.85,.62,1.85);
      if (action === 'motion') {
        if (this.reduceMotion) return;
        this.motion=!this.motion;
        button.classList.toggle('active',this.motion);
        button.setAttribute('aria-pressed',String(this.motion));
        button.setAttribute('aria-label',this.motion?'Pause constellation motion':'Play constellation motion');
        button.title=this.motion?'Pause constellation motion':'Play constellation motion';
        button.textContent=this.motion?'Ⅱ':'▶';
      }
    }));
    this.visibilityChange = () => { this.pageVisible = !document.hidden; this.syncLoop(); };
    document.addEventListener('visibilitychange', this.visibilityChange);
    this.motionChange = event => {
      this.reduceMotion = event.matches;
      if (this.reduceMotion) this.motion = false;
      const button = this.host.querySelector('[data-camera="motion"]');
      if (button) {
        button.setAttribute('aria-disabled', String(this.reduceMotion));
        button.setAttribute('aria-pressed', String(this.motion));
        button.setAttribute('aria-label', this.reduceMotion ? 'Constellation motion disabled by reduced-motion preference' : this.motion ? 'Pause constellation motion' : 'Play constellation motion');
        button.textContent = this.reduceMotion ? '—' : this.motion ? 'Ⅱ' : '▶';
      }
    };
    this.motionQuery.addEventListener?.('change', this.motionChange);
    this.motionChange(this.motionQuery);
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
      this.last = performance.now();
      this.raf = requestAnimationFrame(this.loop);
    }
  }

  resize() {
    const rect = this.host.getBoundingClientRect();
    this.dpr = Math.min(devicePixelRatio || 1, 2);
    this.width = Math.max(1, rect.width);
    this.height = Math.max(1, rect.height);
    this.canvas.width = Math.round(this.width*this.dpr);
    this.canvas.height = Math.round(this.height*this.dpr);
    this.canvas.style.width = `${this.width}px`;
    this.canvas.style.height = `${this.height}px`;
    this.ctx.setTransform(this.dpr,0,0,this.dpr,0,0);
  }

  pointerMove(e) {
    const r = this.canvas.getBoundingClientRect();
    this.pointer.x=e.clientX-r.left; this.pointer.y=e.clientY-r.top;
    if (this.drag) {
      this.targetYaw = this.drag.yaw + (e.clientX-this.drag.x)*.006;
      this.targetPitch = clamp(this.drag.pitch + (e.clientY-this.drag.y)*.005,-1.05,1.05);
      this.canvas.style.cursor='grabbing';
    } else {
      this.hovered = this.nearest(this.pointer.x,this.pointer.y,34);
      this.canvas.style.cursor=this.hovered?'pointer':'grab';
    }
  }

  nearest(x,y,max) {
    let best=null, distance=max;
    this.nodes.forEach(node => { if (!node.screen) return; const d=Math.hypot(x-node.screen.x,y-node.screen.y); if(d<distance){distance=d;best=node;} });
    return best;
  }

  pick(e) {
    const r=this.canvas.getBoundingClientRect(); const node=this.nearest(e.clientX-r.left,e.clientY-r.top,40);
    if(node){
      this.selected=node;this.updateReadout();
      this.canvas.dispatchEvent(new CustomEvent('signalchange',{detail:{id:node.id,label:node.label,sub:node.sub}}));
    }
  }

  selectById(id) {
    const node = this.nodes.find(candidate => candidate.id === id);
    if (!node) return;
    this.selected = node;
    this.updateReadout();
    this.canvas.dispatchEvent(new CustomEvent('signalchange',{detail:{id:node.id,label:node.label,sub:node.sub}}));
  }

  updateReadout() {
    const title=this.host.querySelector('[data-selected-title]');
    const meta=this.host.querySelector('[data-selected-meta]');
    if(title) title.textContent=this.selected.label.charAt(0)+this.selected.label.slice(1).toLowerCase();
    if(meta) meta.textContent=this.selected.sub;
  }

  rotate(p, now) {
    let [x,y,z,w]=p;
    const fourth=(this.time-.5)*1.35;
    const aw=fourth + (this.motion?Math.sin(now*.00018)*.15:0);
    let c=Math.cos(aw),s=Math.sin(aw); [x,w]=[x*c-w*s,x*s+w*c];
    c=Math.cos(this.yaw);s=Math.sin(this.yaw);[x,z]=[x*c-z*s,x*s+z*c];
    c=Math.cos(this.pitch);s=Math.sin(this.pitch);[y,z]=[y*c-z*s,y*s+z*c];
    return [x,y,z,w];
  }

  project(p, now) {
    const [x,y,z,w]=this.rotate(p,now);
    const fourD=1/(1.5-w*.14);
    const perspective=1/(3.9-z*.42);
    const scale=Math.min(this.width/7.4,this.height/5.6)*5.8*this.zoom*fourD*perspective;
    return {x:this.width*.5+x*scale,y:this.height*.47+y*scale,z,scale:clamp(scale/85,.55,1.55),alpha:clamp(.42+(z+2)*.17,.2,1)};
  }

  glow(x,y,r,color,alpha=.3) {
    const g=this.ctx.createRadialGradient(x,y,0,x,y,r);
    const [rr,gg,bb]=hexRgb(color);g.addColorStop(0,`rgba(${rr},${gg},${bb},${alpha})`);g.addColorStop(1,`rgba(${rr},${gg},${bb},0)`);
    this.ctx.fillStyle=g;this.ctx.beginPath();this.ctx.arc(x,y,r,0,TAU);this.ctx.fill();
  }

  drawBackground(now) {
    const ctx=this.ctx;
    const radial=ctx.createRadialGradient(this.width*.5,this.height*.42,0,this.width*.5,this.height*.42,Math.max(this.width,this.height)*.7);
    radial.addColorStop(0,'rgba(22,48,38,.72)');radial.addColorStop(.5,'rgba(9,23,18,.42)');radial.addColorStop(1,'rgba(4,10,8,.96)');ctx.fillStyle=radial;ctx.fillRect(0,0,this.width,this.height);
    this.particles.forEach(p=>{const pt=this.project([p.x,p.y,p.z,p.w],now);const twinkle=this.reduceMotion ? .72 : .55+Math.sin(now*.0015+p.phase)*.35;ctx.fillStyle=`rgba(182,210,194,${p.alpha*twinkle*pt.alpha})`;ctx.beginPath();ctx.arc(pt.x,pt.y,p.size*pt.scale,0,TAU);ctx.fill();});
    ctx.strokeStyle='rgba(126,159,143,.055)';ctx.lineWidth=1;
    for(let r=1;r<5;r++){ctx.beginPath();ctx.ellipse(this.width*.5,this.height*.47,r*this.width*.092,r*this.height*.105,Math.sin(this.yaw)*.25,0,TAU);ctx.stroke();}
  }

  drawEdges(now) {
    const ctx=this.ctx;
    this.edges.forEach((edge,i)=>{
      const a=edge.a.screen,b=edge.b.screen;if(!a||!b)return;
      const active=this.selected===edge.a||this.selected===edge.b;
      const grad=ctx.createLinearGradient(a.x,a.y,b.x,b.y);grad.addColorStop(0,active?'rgba(213,243,111,.5)':'rgba(97,122,110,.16)');grad.addColorStop(.5,active?'rgba(213,243,111,.22)':'rgba(97,122,110,.34)');grad.addColorStop(1,active?'rgba(213,243,111,.5)':'rgba(97,122,110,.16)');
      ctx.strokeStyle=grad;ctx.lineWidth=active?1.25:.7;ctx.beginPath();ctx.moveTo(a.x,a.y);const bow=Math.sin(edge.phase+(this.reduceMotion?0:now*.0002))*12;ctx.quadraticCurveTo((a.x+b.x)/2+bow,(a.y+b.y)/2-bow,b.x,b.y);ctx.stroke();
    });
    this.signalParticles.forEach((sig,i)=>{
      const edge=this.edges[sig.edge],a=edge.a.screen,b=edge.b.screen;if(!a||!b)return;
      sig.offset=(sig.offset+(this.motion?sig.speed*.008:0))%1;const t=ease(sig.offset);const x=lerp(a.x,b.x,t),y=lerp(a.y,b.y,t);const color=PALETTE[edge.b.kind]||PALETTE.muted;
      ctx.fillStyle=color;ctx.globalAlpha=.18;ctx.beginPath();ctx.arc(x,y,4.5,0,TAU);ctx.fill();
      ctx.globalAlpha=.9;ctx.beginPath();ctx.arc(x,y,1.05,0,TAU);ctx.fill();ctx.globalAlpha=1;
    });
  }

  drawNode(node,now) {
    const ctx=this.ctx,p=node.screen,color=PALETTE[node.kind]||PALETTE.muted;
    const selected=node===this.selected,hovered=node===this.hovered;
    const pulse=this.reduceMotion?1:1+Math.sin(now*.002+node.pulse)*.045;
    const radius=node.baseSize*p.scale*pulse*(selected?1.12:1);
    this.glow(p.x,p.y,radius*(selected?3.2:2.2),color,selected?.23:.12);
    ctx.save();ctx.translate(p.x,p.y);
    ctx.strokeStyle=color;ctx.globalAlpha=p.alpha;ctx.lineWidth=selected?1.8:1;
    ctx.beginPath();ctx.arc(0,0,radius,0,TAU);ctx.stroke();
    ctx.globalAlpha=.26;ctx.beginPath();ctx.arc(0,0,radius*.76,0,TAU);ctx.stroke();
    if(selected||hovered){const spin=this.reduceMotion?0:now*.0003;ctx.globalAlpha=.5;ctx.setLineDash([2,5]);ctx.beginPath();ctx.arc(0,0,radius+8+(this.reduceMotion?0:Math.sin(now*.002)*2),spin,spin+TAU);ctx.stroke();ctx.setLineDash([]);}
    ctx.globalAlpha=1;ctx.fillStyle='#eef2ed';ctx.font=`600 ${clamp(10*p.scale,9,13)}px "DM Mono"`;ctx.textAlign='center';ctx.fillText(node.label,0,-1);
    ctx.fillStyle=color;ctx.font=`500 ${clamp(8.5*p.scale,8,11)}px Manrope`;ctx.fillText(node.sub,0,13*p.scale);
    ctx.restore();
  }

  loop(now) {
    this.raf = null;
    if (!this.pageVisible || !this.inViewport) return;
    if (now-this.lastRender < 25) { this.raf=requestAnimationFrame(this.loop); return; }
    this.lastRender=now;
    const dt=clamp((now-this.last)/16.67,.2,3);this.last=now;
    this.time=lerp(this.time,this.targetTime,.075*dt);this.yaw=lerp(this.yaw,this.targetYaw,.075*dt);this.pitch=lerp(this.pitch,this.targetPitch,.075*dt);this.zoom=lerp(this.zoom,this.targetZoom,.09*dt);
    if(this.motion&&!this.drag)this.targetYaw+=.00032*dt;
    if(this.timeReadout)this.timeReadout.textContent=String(Math.round(this.time*100));
    this.nodes.forEach(n=>{n.screen=this.project(n.p,now);});
    this.ctx.clearRect(0,0,this.width,this.height);this.drawBackground(now);this.drawEdges(now);
    [...this.nodes].sort((a,b)=>a.screen.z-b.screen.z).forEach(n=>this.drawNode(n,now));
    this.raf=requestAnimationFrame(this.loop);
  }

  destroy() {
    if (this.raf !== null) cancelAnimationFrame(this.raf);this.resizeObserver?.disconnect();this.intersectionObserver?.disconnect();
    document.removeEventListener('visibilitychange',this.visibilityChange);this.motionQuery.removeEventListener?.('change',this.motionChange);
    this.canvas.removeEventListener('pointermove',this.onMove);this.canvas.removeEventListener('pointerdown',this.onDown);this.canvas.removeEventListener('pointerup',this.onUp);this.canvas.removeEventListener('wheel',this.onWheel);
  }
}

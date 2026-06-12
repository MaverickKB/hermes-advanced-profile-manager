/* System Explorer — interactive visual graph of every profile, its delegation
   links, channel routing, skill groups, MCP servers, providers, skills, and
   toolsets. Three views: Constellation (force), Mind map (radial), Flow
   (layered). Canvas-rendered, no external dependencies. */
(()=>{
const KIND_COLOR={profile:'#69d2ff',provider:'#b99cff',mcp:'#ffb86b',group:'#7dffa5',skill:'#5f7fa6',toolset:'#d8c75f'};
const HEALTH_COLOR={ok:'#37d27a',warn:'#ffd36a',error:'#ff7878'};
const EDGE_COLOR={delegates:'rgba(105,210,255,.55)',routes:'rgba(88,101,242,.8)',group:'rgba(125,255,165,.55)',mcp:'rgba(255,184,107,.45)','model-route':'rgba(185,156,255,.4)',skill:'rgba(95,127,166,.22)',toolset:'rgba(216,199,95,.25)'};
const EDGE_LABEL={delegates:'delegation','routes':'channel routing',group:'skill group',mcp:'MCP server','model-route':'provider route',skill:'skill',toolset:'toolset'};

let ex={
  raw:null,nodes:[],edges:[],byId:new Map(),adj:new Map(),
  mode:'constellation',focus:null,selected:null,hovered:null,
  cam:{x:0,y:0,k:1},alpha:0,running:false,
  dragNode:null,panStart:null,canvas:null,ctx:null,dpr:1,
  layers:{delegates:true,routes:true,group:true,mcp:true,'model-route':true,skill:false,toolset:false},
  issuesOnly:false,search:'',expanded:false,loaded:false,
  spread:1,labelMode:'auto',labelSize:12,
};
const KMIN=0.06,KMAX=5;

/* ------------------------------------------------------------------ data */
async function load(fresh){
  status('Building system graph…');
  const j=await api('/api/graph?skills=1&toolsets=1'+(fresh?'&fresh=1':''));
  ex.raw=j;
  ex.nodes=j.nodes.map(n=>({...n,x:(Math.random()-0.5)*1200,y:(Math.random()-0.5)*900,vx:0,vy:0,r:6}));
  ex.byId=new Map(ex.nodes.map(n=>[n.id,n]));
  ex.edges=j.edges.filter(e=>ex.byId.has(e.source)&&ex.byId.has(e.target));
  ex.adj=new Map();
  for(const e of ex.edges){
    if(!ex.adj.has(e.source))ex.adj.set(e.source,[]);
    if(!ex.adj.has(e.target))ex.adj.set(e.target,[]);
    ex.adj.get(e.source).push(e);ex.adj.get(e.target).push(e);
  }
  computeVisibility();
  status(`${j.counts.profiles} profiles · ${j.counts.nodes} nodes · ${j.counts.edges} edges · health: ${j.counts.health.ok} ok / ${j.counts.health.warn} warn / ${j.counts.health.error} error`);
  renderLegend();
  applyMode(true);
  // an open detail panel must reflect the fresh scan, not the one it was opened from
  if(ex.selected){
    if(ex.byId.has(ex.selected))selectNode(ex.selected);
    else{ex.selected=null;document.getElementById('ex-panel').classList.add('hidden')}
  }
}
function visibleEdge(e){
  if(!ex.layers[e.kind])return false;
  const s=ex.byId.get(e.source),t=ex.byId.get(e.target);
  return s._vis&&t._vis;
}
function computeVisibility(){
  for(const n of ex.nodes){
    if(n.kind==='profile')n._vis=!ex.issuesOnly||n.health!=='ok';
    else n._vis=false;
  }
  // resource nodes visible when their layer is on and any visible profile links to them
  for(const e of ex.edges){
    if(!ex.layers[e.kind])continue;
    const s=ex.byId.get(e.source),t=ex.byId.get(e.target);
    if(s.kind==='profile'&&s._vis&&t.kind!=='profile')t._vis=true;
  }
  if(ex.issuesOnly){
    // keep only the targets of BROKEN/stale links visible for context
    for(const e of ex.edges){
      if(!(e.broken||e.fuzzy))continue;
      const s=ex.byId.get(e.source),t=ex.byId.get(e.target);
      if(s._vis)t._ctx=true;
    }
    for(const n of ex.nodes){if(n._ctx&&!n._vis){n._vis=true;n._dim=true}n._ctx=false}
  }else{
    for(const n of ex.nodes)n._dim=false;
  }
  // degree-based radius over visible edges
  const deg=new Map();
  for(const e of ex.edges){
    if(!visibleEdge(e))continue;
    deg.set(e.source,(deg.get(e.source)||0)+1);
    deg.set(e.target,(deg.get(e.target)||0)+1);
  }
  for(const n of ex.nodes){
    const d=deg.get(n.id)||0;
    n._deg=d;
    n.r=n.kind==='profile'?Math.max(8,Math.min(26,7+Math.sqrt(d)*1.7)):Math.max(5,Math.min(18,4+Math.sqrt(d)*1.4));
  }
}

/* ------------------------------------------------------------- simulation */
function reheat(a=1){ex.alpha=a;if(!ex.running){ex.running=true;requestAnimationFrame(tick)}}
function visNodes(){return ex.nodes.filter(n=>n._vis)}
function tick(){
  if(ex.mode==='constellation')stepForce();
  else stepLerp();
  draw();
  if(ex.alpha>0.012||ex.dragNode){requestAnimationFrame(tick)}else{ex.running=false;draw()}
}
function stepForce(){
  const nodes=visNodes();
  const a=ex.alpha;
  const MAXV=28;
  // spatial grid repulsion
  const cell=150,grid=new Map();
  for(const n of nodes){
    const key=((n.x/cell)|0)+':'+((n.y/cell)|0);
    if(!grid.has(key))grid.set(key,[]);
    grid.get(key).push(n);
  }
  for(const n of nodes){
    let fx=0,fy=0;
    const gx=(n.x/cell)|0,gy=(n.y/cell)|0;
    for(let ix=gx-1;ix<=gx+1;ix++)for(let iy=gy-1;iy<=gy+1;iy++){
      const bucket=grid.get(ix+':'+iy);if(!bucket)continue;
      for(const m of bucket){
        if(m===n)continue;
        let dx=n.x-m.x,dy=n.y-m.y;let d2=dx*dx+dy*dy;
        if(d2<1){dx=Math.random()-0.5;dy=Math.random()-0.5;d2=1}
        d2=Math.max(d2,40);                         // soften overlapping pairs
        if(d2>cell*cell*4)continue;
        const f=(n.kind==='skill'||m.kind==='skill'?520:1500)*ex.spread*ex.spread/d2;
        fx+=dx*f;fy+=dy*f;
      }
    }
    // gravity to center
    const g=0.015/ex.spread;
    fx-=n.x*g;fy-=n.y*g;
    n.vx=(n.vx+fx*a)*0.5;n.vy=(n.vy+fy*a)*0.5;
  }
  for(const e of ex.edges){
    if(!visibleEdge(e))continue;
    const s=ex.byId.get(e.source),t=ex.byId.get(e.target);
    const len=(e.kind==='skill'?180:e.kind==='toolset'?160:e.kind==='delegates'?210:140)*ex.spread;
    // degree-normalized spring strength keeps hub nodes (48+ edges) stable
    const deg=Math.max(1,Math.min(s._deg||1,t._deg||1));
    const k=(e.kind==='skill'?0.012:0.06)/Math.sqrt(deg);
    let dx=t.x-s.x,dy=t.y-s.y;
    const d=Math.sqrt(dx*dx+dy*dy)||1;
    const f=Math.max(-2,Math.min(2,k*(d-len)/d))*a;
    s.vx+=dx*f;s.vy+=dy*f;t.vx-=dx*f;t.vy-=dy*f;
  }
  for(const n of nodes){
    if(n===ex.dragNode)continue;
    const sp=Math.hypot(n.vx,n.vy);
    if(sp>MAXV){n.vx*=MAXV/sp;n.vy*=MAXV/sp}
    n.x+=n.vx;n.y+=n.vy;
    if(!isFinite(n.x)||!isFinite(n.y)){n.x=(Math.random()-0.5)*900;n.y=(Math.random()-0.5)*700;n.vx=n.vy=0}
  }
  ex.alpha*=0.985;
}
function stepLerp(){
  let moving=false;
  for(const n of visNodes()){
    if(n._tx===undefined)continue;
    const dx=n._tx-n.x,dy=n._ty-n.y;
    if(Math.abs(dx)+Math.abs(dy)>0.6){n.x+=dx*0.16;n.y+=dy*0.16;moving=true}
    else{n.x=n._tx;n.y=n._ty}
  }
  ex.alpha=moving?Math.max(ex.alpha*0.99,0.02):0;
}

/* ----------------------------------------------------------------- layouts */
function applyMode(fitAfter){
  computeVisibility();
  if(ex.mode==='mindmap')layoutMindmap();
  else if(ex.mode==='flow')layoutFlow();
  else reheat(1);
  if(fitAfter)setTimeout(fit,ex.mode==='constellation'?900:300);
  if(ex.mode!=='constellation')reheat(0.5);
}
function layoutMindmap(){
  let activeProfile='default';
  try{activeProfile=state.active||'default'}catch(e){}
  const focusId=ex.focus||('profile:'+activeProfile);
  const focus=ex.byId.get(focusId)||visNodes().find(n=>n.kind==='profile');
  if(!focus)return;
  ex.focus=focus.id;
  // BFS depths over visible edges
  const depth=new Map([[focus.id,0]]);
  const parent=new Map();
  const queue=[focus.id];
  while(queue.length){
    const id=queue.shift();
    for(const e of ex.adj.get(id)||[]){
      if(!visibleEdge(e))continue;
      const next=e.source===id?e.target:e.source;
      if(!depth.has(next)){depth.set(next,depth.get(id)+1);parent.set(next,id);queue.push(next)}
    }
  }
  for(const n of ex.nodes)if(n._vis&&!depth.has(n.id))n._vis=false;
  focus._tx=0;focus._ty=0;
  const rings=new Map();
  for(const [id,d] of depth){if(d>0){if(!rings.has(d))rings.set(d,[]);rings.get(d).push(id)}}
  // angle inheritance: children cluster near their parent's angle
  const angle=new Map([[focus.id,0]]);
  const maxDepth=Math.max(0,...rings.keys());
  for(let d=1;d<=maxDepth;d++){
    const ids=rings.get(d)||[];
    ids.sort((a,b)=>(angle.get(parent.get(a))||0)-(angle.get(parent.get(b))||0));
    const R=d*230*ex.spread;
    ids.forEach((id,i)=>{
      const th=(i/ids.length)*Math.PI*2-Math.PI/2;
      angle.set(id,th);
      const n=ex.byId.get(id);
      n._tx=Math.cos(th)*R;n._ty=Math.sin(th)*R;
    });
  }
}
function layoutFlow(){
  const cols={orchestrator:0,profile:1,group:2.1,mcp:2.9,provider:3.7,toolset:4.5,skill:5.4};
  const colX=c=>(c*340-900)*ex.spread;
  const buckets=new Map();
  for(const n of visNodes()){
    let col;
    if(n.kind==='profile')col=(n.delegates_out||0)>0?'orchestrator':'profile';
    else col=n.kind;
    if(!buckets.has(col))buckets.set(col,[]);
    buckets.get(col).push(n);
    n._flowSide=col==='orchestrator'?'left':'right';
  }
  for(const [col,nodes] of buckets){
    nodes.sort((a,b)=>(b._deg-a._deg)||a.label.localeCompare(b.label));
    const gap=Math.max(34,Math.min(64,1400/nodes.length))*ex.spread;
    nodes.forEach((n,i)=>{
      n._tx=colX(cols[col]??1);
      n._ty=(i-(nodes.length-1)/2)*gap;
    });
  }
}

/* ------------------------------------------------------------------ render */
function draw(){
  const c=ex.canvas,ctx=ex.ctx;if(!c)return;
  ctx.setTransform(ex.dpr,0,0,ex.dpr,0,0);
  ctx.clearRect(0,0,c.width/ex.dpr,c.height/ex.dpr);
  const W=c.width/ex.dpr,H=c.height/ex.dpr;
  ctx.save();
  ctx.translate(W/2+ex.cam.x,H/2+ex.cam.y);
  ctx.scale(ex.cam.k,ex.cam.k);

  const focusSet=neighborSet(ex.hovered||ex.selected);
  // edges
  for(const e of ex.edges){
    if(!visibleEdge(e))continue;
    const s=ex.byId.get(e.source),t=ex.byId.get(e.target);
    const dimmed=focusSet&&!(focusSet.has(s.id)&&focusSet.has(t.id));
    ctx.globalAlpha=dimmed?0.06:1;
    ctx.strokeStyle=e.broken||e.fuzzy?'rgba(255,120,120,.8)':(EDGE_COLOR[e.kind]||'rgba(160,180,200,.3)');
    ctx.lineWidth=(e.kind==='delegates'?1.6:e.kind==='skill'?0.6:1)/ex.cam.k;
    if(e.fuzzy)ctx.setLineDash([6/ex.cam.k,5/ex.cam.k]);
    ctx.beginPath();
    if(e.kind==='delegates'||e.kind==='routes'){
      const mx=(s.x+t.x)/2-(t.y-s.y)*0.12,my=(s.y+t.y)/2+(t.x-s.x)*0.12;
      ctx.moveTo(s.x,s.y);ctx.quadraticCurveTo(mx,my,t.x,t.y);
    }else{
      ctx.moveTo(s.x,s.y);ctx.lineTo(t.x,t.y);
    }
    ctx.stroke();
    ctx.setLineDash([]);
    if((e.kind==='delegates'||e.kind==='routes')&&ex.cam.k>0.35){
      drawArrow(ctx,s,t,e);
    }
  }
  ctx.globalAlpha=1;
  // nodes
  for(const n of visNodes()){
    const dimmed=(focusSet&&!focusSet.has(n.id))||n._dim;
    ctx.globalAlpha=dimmed?0.12:1;
    ctx.beginPath();
    ctx.arc(n.x,n.y,n.r,0,Math.PI*2);
    ctx.fillStyle=KIND_COLOR[n.kind]||'#888';
    if(n.kind==='profile'){
      ctx.fillStyle='#0d1825';
      ctx.fill();
      ctx.lineWidth=2.6/Math.sqrt(ex.cam.k);
      ctx.strokeStyle=HEALTH_COLOR[n.health]||'#69d2ff';
      ctx.stroke();
      ctx.beginPath();ctx.arc(n.x,n.y,Math.max(2.5,n.r*0.45),0,Math.PI*2);
      ctx.fillStyle=KIND_COLOR.profile;ctx.fill();
    }else{
      ctx.fill();
    }
    if(n.id===ex.selected){
      ctx.beginPath();ctx.arc(n.x,n.y,n.r+5/ex.cam.k,0,Math.PI*2);
      ctx.strokeStyle='#fff';ctx.lineWidth=1.4/ex.cam.k;ctx.setLineDash([4/ex.cam.k,3/ex.cam.k]);ctx.stroke();ctx.setLineDash([]);
    }
  }
  drawLabels(ctx,focusSet);
  ctx.restore();
  ctx.globalAlpha=1;
}
function labelWanted(n,focusSet){
  if(n.id===ex.hovered||n.id===ex.selected)return 'pinned';
  if(focusSet&&focusSet.has(n.id))return 'pinned';
  if(n._dim)return null;
  if(focusSet&&!focusSet.has(n.id))return null;
  switch(ex.labelMode){
    case 'none':return null;
    case 'all':return 'cull';
    case 'profiles':return n.kind==='profile'?'cull':null;
    default:{ // auto: profiles early, resources when zoomed in; flow columns
      // tolerate much earlier labels because side placement + culling declutter
      const profileAt=ex.mode==='flow'?0.08:0.18;
      const resourceAt=ex.mode==='flow'?0.26:0.65;
      if(n.kind==='profile'&&ex.cam.k>profileAt)return 'cull';
      if(n.kind!=='profile'&&ex.cam.k>resourceAt)return 'cull';
      return null;
    }
  }
}
function drawLabels(ctx,focusSet){
  const fs=Math.max(ex.labelSize*0.85,ex.labelSize/ex.cam.k);
  ctx.font=`${fs}px ui-sans-serif,system-ui`;
  const candidates=[];
  for(const n of visNodes()){
    const mode=labelWanted(n,focusSet);
    if(!mode)continue;
    candidates.push({n,pinned:mode==='pinned',prio:(mode==='pinned'?1e6:0)+(n.kind==='profile'?1e3:0)+(n._deg||0)});
  }
  candidates.sort((a,b)=>b.prio-a.prio);
  const placed=[];
  const pad=4/ex.cam.k;
  for(const c of candidates){
    const n=c.n;
    const w=ctx.measureText(n.label).width,h=fs*1.25;
    let x,y,align;
    if(ex.mode==='flow'&&n._flowSide){
      align=n._flowSide==='left'?'right':'left';
      x=n._flowSide==='left'?n.x-n.r-6/ex.cam.k:n.x+n.r+6/ex.cam.k;
      y=n.y+fs*0.36;
    }else{
      align='center';
      x=n.x;
      y=n.y+n.r+fs+3/ex.cam.k;
    }
    const rx=align==='center'?x-w/2:align==='left'?x:x-w;
    const rect={x:rx-pad,y:y-fs,w:w+pad*2,h};
    if(!c.pinned&&placed.some(r=>rect.x<r.x+r.w&&rect.x+rect.w>r.x&&rect.y<r.y+r.h&&rect.y+rect.h>r.y))continue;
    placed.push(rect);
    ctx.globalAlpha=1;
    ctx.fillStyle='rgba(6,10,17,.78)';
    ctx.beginPath();
    if(ctx.roundRect)ctx.roundRect(rect.x,rect.y,rect.w,rect.h,3/ex.cam.k);
    else ctx.rect(rect.x,rect.y,rect.w,rect.h);
    ctx.fill();
    ctx.fillStyle=c.pinned?'#ffffff':n.kind==='profile'?'#e8f3ff':'#9fb3c8';
    ctx.textAlign=align;
    ctx.fillText(n.label,x,y);
  }
}
function drawArrow(ctx,s,t,e){
  const dx=t.x-s.x,dy=t.y-s.y,d=Math.sqrt(dx*dx+dy*dy)||1;
  const px=t.x-dx/d*(t.r+4),py=t.y-dy/d*(t.r+4);
  const a=Math.atan2(dy,dx),size=7/Math.sqrt(ex.cam.k);
  ctx.beginPath();
  ctx.moveTo(px,py);
  ctx.lineTo(px-size*Math.cos(a-0.42),py-size*Math.sin(a-0.42));
  ctx.lineTo(px-size*Math.cos(a+0.42),py-size*Math.sin(a+0.42));
  ctx.closePath();
  ctx.fillStyle=e.broken||e.fuzzy?'rgba(255,120,120,.85)':(EDGE_COLOR[e.kind]||'rgba(160,180,200,.5)');
  ctx.fill();
}
function neighborSet(id){
  if(!id)return null;
  const set=new Set([id]);
  for(const e of ex.adj.get(id)||[]){
    if(!visibleEdge(e))continue;
    set.add(e.source);set.add(e.target);
  }
  return set;
}

/* -------------------------------------------------------------- interaction */
function worldFromEvent(ev){
  const rect=ex.canvas.getBoundingClientRect();
  const W=rect.width,H=rect.height;
  const sx=ev.clientX-rect.left,sy=ev.clientY-rect.top;
  return {x:(sx-W/2-ex.cam.x)/ex.cam.k,y:(sy-H/2-ex.cam.y)/ex.cam.k};
}
function nodeAt(pos){
  let best=null,bestD=1e9;
  for(const n of visNodes()){
    const dx=n.x-pos.x,dy=n.y-pos.y;
    const d=Math.sqrt(dx*dx+dy*dy);
    if(d<n.r+6/ex.cam.k&&d<bestD){best=n;bestD=d}
  }
  return best;
}
function kToSlider(k){return Math.round(1000*Math.log(k/KMIN)/Math.log(KMAX/KMIN))}
function sliderToK(v){return KMIN*Math.pow(KMAX/KMIN,v/1000)}
function syncZoomSlider(){const s=document.getElementById('ex-zoom');if(s)s.value=kToSlider(ex.cam.k)}
function setZoom(k,anchorX=0,anchorY=0){
  const k0=ex.cam.k;
  ex.cam.k=Math.max(KMIN,Math.min(KMAX,k));
  const f=ex.cam.k/k0;
  ex.cam.x=anchorX-(anchorX-ex.cam.x)*f;
  ex.cam.y=anchorY-(anchorY-ex.cam.y)*f;
  syncZoomSlider();
  draw();
}
function wireCanvas(){
  const c=ex.canvas;
  c.addEventListener('wheel',ev=>{
    ev.preventDefault();
    const rect=c.getBoundingClientRect();
    const sx=ev.clientX-rect.left-rect.width/2,sy=ev.clientY-rect.top-rect.height/2;
    setZoom(ex.cam.k*Math.exp(-ev.deltaY*0.0014),sx,sy);
  },{passive:false});
  c.addEventListener('pointerdown',ev=>{
    try{c.setPointerCapture(ev.pointerId)}catch(e){}
    const pos=worldFromEvent(ev);
    const n=nodeAt(pos);
    if(n){ex.dragNode=n;n._wasDragged=false;reheat(Math.max(ex.alpha,0.25))}
    else ex.panStart={x:ev.clientX-ex.cam.x,y:ev.clientY-ex.cam.y};
  });
  c.addEventListener('pointermove',ev=>{
    if(ex.dragNode){
      const pos=worldFromEvent(ev);
      ex.dragNode.x=pos.x;ex.dragNode.y=pos.y;
      ex.dragNode._tx=pos.x;ex.dragNode._ty=pos.y;
      ex.dragNode._wasDragged=true;
      if(!ex.running)reheat(0.2);
    }else if(ex.panStart){
      ex.cam.x=ev.clientX-ex.panStart.x;ex.cam.y=ev.clientY-ex.panStart.y;
      draw();
    }else{
      const n=nodeAt(worldFromEvent(ev));
      const id=n?n.id:null;
      if(id!==ex.hovered){ex.hovered=id;c.style.cursor=id?'pointer':'grab';draw()}
    }
  });
  // every way a pointer interaction can end must release the drag — a missed
  // pointercancel (trackpad gesture, focus loss) otherwise leaves the pan stuck
  const endDrag=ev=>{
    if(ex.dragNode){
      if(ev&&ev.type==='pointerup'&&!ex.dragNode._wasDragged)selectNode(ex.dragNode.id);
      ex.dragNode=null;
    }
    ex.panStart=null;
  };
  c.addEventListener('pointerup',endDrag);
  c.addEventListener('pointercancel',endDrag);
  c.addEventListener('lostpointercapture',endDrag);
  window.addEventListener('blur',()=>endDrag());
  c.addEventListener('dblclick',ev=>{
    const n=nodeAt(worldFromEvent(ev));
    if(n){ex.focus=n.id;setMode('mindmap')}
  });
}
function fit(){
  const nodes=visNodes();if(!nodes.length)return;
  let minX=1e9,maxX=-1e9,minY=1e9,maxY=-1e9;
  for(const n of nodes){minX=Math.min(minX,n.x);maxX=Math.max(maxX,n.x);minY=Math.min(minY,n.y);maxY=Math.max(maxY,n.y)}
  const rect=ex.canvas.getBoundingClientRect();
  const w=maxX-minX+200,h=maxY-minY+200;
  ex.cam.k=Math.max(0.07,Math.min(1.6,Math.min(rect.width/w,rect.height/h)));
  ex.cam.x=-(minX+maxX)/2*ex.cam.k;
  ex.cam.y=-(minY+maxY)/2*ex.cam.k;
  syncZoomSlider();
  draw();
}

/* ------------------------------------------------------------- side panel */
function selectNode(id){
  ex.selected=id;
  const n=ex.byId.get(id);
  const panel=document.getElementById('ex-panel');
  if(!n){panel.classList.add('hidden');draw();return}
  const edges=(ex.adj.get(id)||[]).filter(visibleEdge);
  const out=edges.filter(e=>e.source===id),inn=edges.filter(e=>e.target===id);
  const li=(e,dir)=>{
    const other=ex.byId.get(dir==='out'?e.target:e.source);
    return `<div class="ex-edge-row"><span class="pill" style="border-color:${EDGE_COLOR[e.kind]||'#456'}">${esc(EDGE_LABEL[e.kind]||e.kind)}${e.route?' · '+esc(e.route):''}${e.channels?' · '+e.channels+' ch':''}${e.fuzzy?' · STALE NAME':''}</span> <a href="#" data-exgoto="${esc(other.id)}">${esc(other.label)}</a>${e.model?`<small>${esc(e.model)}</small>`:''}</div>`;
  };
  panel.classList.remove('hidden');
  panel.innerHTML=`
    <div class="ex-panel-head">
      <div><span class="pill" style="border-color:${KIND_COLOR[n.kind]}">${esc(n.kind)}</span>
      ${n.kind==='profile'?`<span class="pill ${n.health==='ok'?'good':n.health==='warn'?'warnpill':'bad'}">${esc(n.health)}</span>`:''}</div>
      <button id="ex-close" class="mini">×</button>
    </div>
    <h3>${esc(n.label)}</h3>
    ${n.kind==='profile'?`
      <div class="kv">
        ${kv([['Model',(n.provider?n.provider+' / ':'')+(n.model||'—')],['Skills',n.skills_enabled+' enabled / '+n.skills_installed+' installed'],['Delegates to',n.delegates_out+' profiles'],['Groups',(n.groups||[]).join(', ')||'none']])}
      </div>
      ${(n.health_reasons||[]).length?`<div class="issue ${n.health==='error'?'error':'warning'}"><strong>Health findings</strong><br>${n.health_reasons.map(esc).join('<br>')}</div>`:'<div class="issue"><strong>No health findings.</strong></div>'}
      <div class="actions">
        <button id="ex-open" class="primary">Open in manager</button>
        ${n.delegates_out?'<button id="ex-delegation">Delegation authority ('+n.delegates_out+')</button>':'<button id="ex-delegation">Delegation authority</button>'}
        <button id="ex-focus">Mind-map from here</button>
      </div>`:`
      <p class="muted">${n._deg} connections${n.missing?' · MANIFEST MISSING':''}</p>
      ${n.kind==='group'?'<div class="actions"><button id="ex-open-group">Open in Skill groups tab</button></div>':''}`}
    ${out.length?`<h4>Outgoing (${out.length})</h4><div class="ex-edges">${out.slice(0,80).map(e=>li(e,'out')).join('')}</div>`:''}
    ${inn.length?`<h4>Incoming (${inn.length})</h4><div class="ex-edges">${inn.slice(0,80).map(e=>li(e,'in')).join('')}</div>`:''}
  `;
  document.getElementById('ex-close').onclick=()=>{ex.selected=null;panel.classList.add('hidden');draw()};
  const openBtn=document.getElementById('ex-open');
  if(openBtn)openBtn.onclick=async()=>{await selectProfile(n.label);showTab('overview')};
  const delBtn=document.getElementById('ex-delegation');
  if(delBtn)delBtn.onclick=async()=>{await selectProfile(n.label);showTab('team')};
  const focusBtn=document.getElementById('ex-focus');
  if(focusBtn)focusBtn.onclick=()=>{ex.focus=n.id;setMode('mindmap')};
  const groupBtn=document.getElementById('ex-open-group');
  if(groupBtn)groupBtn.onclick=()=>{showTab('groups');setTimeout(()=>{if(window.openGroup)openGroup(n.label)},600)};
  panel.querySelectorAll('[data-exgoto]').forEach(a=>a.onclick=e=>{e.preventDefault();const target=ex.byId.get(a.dataset.exgoto);if(target){selectNode(target.id);centerOn(target)}});
  draw();
}
function centerOn(n){ex.cam.x=-n.x*ex.cam.k;ex.cam.y=-n.y*ex.cam.k;draw()}

/* ----------------------------------------------------------------- chrome */
function status(msg){document.getElementById('ex-status').textContent=msg}
const legendColor=c=>String(c).replace(/[\d.]+\)$/,'.9)');
function renderLegend(){
  document.getElementById('ex-legend').innerHTML=
    Object.entries({profile:'profile',group:'skill group',mcp:'MCP server',provider:'provider',skill:'skill',toolset:'toolset'})
      .map(([k,label])=>`<span><i style="background:${KIND_COLOR[k]}"></i>${label}</span>`).join('')
    +Object.keys(EDGE_COLOR).map(k=>`<span><i class="line" style="background:${legendColor(EDGE_COLOR[k])}"></i>${EDGE_LABEL[k]||k} thread</span>`).join('')
    +Object.entries(HEALTH_COLOR).map(([k,clr])=>`<span><i class="ring" style="border-color:${clr}"></i>${k}</span>`).join('')
    +`<span><i class="line" style="background:rgba(255,120,120,.8)"></i>broken/stale link</span>`;
}
function setMode(mode){
  ex.mode=mode;
  document.querySelectorAll('[data-exmode]').forEach(b=>b.classList.toggle('active',b.dataset.exmode===mode));
  applyMode(true);
}
function resize(){
  const c=ex.canvas;if(!c)return;
  const rect=c.parentElement.getBoundingClientRect();
  ex.dpr=window.devicePixelRatio||1;
  c.width=rect.width*ex.dpr;c.height=rect.height*ex.dpr;
  c.style.width=rect.width+'px';c.style.height=rect.height+'px';
  draw();
}
function wireControls(){
  document.querySelectorAll('[data-exmode]').forEach(b=>b.onclick=()=>setMode(b.dataset.exmode));
  document.querySelectorAll('[data-exlayer]').forEach(cb=>{
    // each layer toggle carries the swatch of the thread color it controls
    const sw=document.createElement('i');
    sw.className='ex-layer-swatch';
    sw.style.background=legendColor(EDGE_COLOR[cb.dataset.exlayer]||'rgba(160,180,200,.5)');
    cb.after(sw);
    cb.onchange=()=>{
      ex.layers[cb.dataset.exlayer]=cb.checked;
      applyMode(false);reheat(0.6);
    };
  });
  document.getElementById('ex-issues-only').onchange=e=>{ex.issuesOnly=e.target.checked;applyMode(true)};
  document.getElementById('ex-fit').onclick=fit;
  document.getElementById('ex-refresh').onclick=()=>load(true).catch(err=>status('Rescan failed: '+err.message));
  document.getElementById('ex-expand').onclick=()=>{
    ex.expanded=!ex.expanded;
    document.querySelector('.rail').style.display=ex.expanded?'none':'';
    document.querySelector('.app').style.gridTemplateColumns=ex.expanded?'1fr':'';
    document.querySelector('.hero').style.display=ex.expanded?'none':'';
    document.getElementById('tab-nav').style.display=ex.expanded?'none':'';
    setTimeout(resize,50);
    if(ex.expanded)status('Press ⛶ again (top right) to exit full view');
  };
  document.getElementById('ex-zoom').oninput=e=>setZoom(sliderToK(+e.target.value));
  document.getElementById('ex-spread').oninput=e=>{
    ex.spread=(+e.target.value)/100;
    if(ex.mode==='constellation')reheat(0.6);
    else{applyMode(false);reheat(0.5)}
  };
  document.getElementById('ex-labelsize').oninput=e=>{ex.labelSize=+e.target.value;draw()};
  document.getElementById('ex-labelmode').onchange=e=>{ex.labelMode=e.target.value;draw()};
  const bestMatch=()=>{
    if(!ex.search)return null;
    const q=ex.search;
    const score=n=>{
      const l=n.label.toLowerCase();
      if(!l.includes(q))return -1;
      let s=0;
      if(l===q)s+=100;else if(l.startsWith(q))s+=40;
      if(n.kind==='profile')s+=25;          // humans usually mean a profile
      return s;
    };
    return visNodes().map(n=>[score(n),n]).filter(([s])=>s>=0).sort((a,b)=>b[0]-a[0])[0]?.[1]||null;
  };
  const search=document.getElementById('ex-search');
  search.oninput=()=>{
    ex.search=search.value.toLowerCase();
    if(!ex.search){ex.hovered=null;draw();return}
    const hit=bestMatch();
    if(hit){ex.hovered=hit.id;draw()}
  };
  search.onkeydown=e=>{
    if(e.key==='Enter'){
      const hit=bestMatch();
      if(hit){selectNode(hit.id);centerOn(hit)}
    }
  };
  window.addEventListener('resize',resize);
}

/* ------------------------------------------------------------------ entry */
window.explorerLoad=async function(force){
  if(!ex.canvas){
    ex.canvas=document.getElementById('ex-canvas');
    ex.ctx=ex.canvas.getContext('2d');
    wireCanvas();wireControls();
  }
  resize();
  if(!ex.loaded||force===true){
    ex.loaded=true;
    await load(false);
  }else{
    draw();
  }
};
try{TAB_LOADERS.explorer=()=>window.explorerLoad()}catch(e){console.warn('explorer: tab loader registration failed',e)}
window.__ex=ex; // debug handle
window.__exDebug={stepForce,computeVisibility,visNodes,draw,fit}; // debug handle
})();

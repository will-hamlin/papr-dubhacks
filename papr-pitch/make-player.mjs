import fs from 'node:fs/promises';
import {slides} from './build-v2.mjs';
const root=new URL('./',import.meta.url);
const esc=s=>s.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
let sections='';
for(let i=0;i<slides.length;i++){
 const s=slides[i];let parts='';
 for(let j=0;j<s.items.length;j++){
  const a=s.items[j];
  if(a[0]==='image'){
   const src='data:image/svg+xml;base64,'+(await fs.readFile(new URL(a[1],root))).toString('base64');
   parts+=`<img class="piece logo" alt="Original papr logo" src="${src}" style="left:${a[2]}px;top:${a[3]}px;width:${a[4]}px;height:${a[5]}px;--delay:${Math.min(j*90,480)}ms">`;continue;
  }
  if(['rect','ellipse'].includes(a[0])){parts+=`<div class="graphic" style="position:absolute;left:${a[1]}px;top:${a[2]}px;width:${a[3]}px;height:${a[4]}px;background:${a[5]};${a[0]==='ellipse'?'border-radius:50%;':''}"></div>`;continue;}
  const [text,x,y,w,h,size,font='Times New Roman',color=s.bg==='#111F31'?'#FFFFFF':'#111F31']=a;
  const html=esc(text).replaceAll('\n','<br>').replace(/^ /,'&nbsp;');
  if(s.metricFrom?.[text]) {
   const [before,beforeSize]=s.metricFrom[text];
   const pad=8;
   const afterStyle=s.plainMetrics?.includes(text)?'background:transparent;color:'+color:'background:#BEDDFF;color:#111F31';
   const metricContent=s.citationNotes?.[text]?`<button class="provenance" data-note="${esc(s.citationNotes[text])}" title="View source and assumptions">${html}</button>`:html;
   parts+=`<div class="metric-window${text==='d'?' metric-letter':''}" style="left:${x-pad}px;top:${y}px;width:${w+pad*2}px;height:${h+14}px;font-family:'${font}';color:${color}"><span class="metric-before" aria-hidden="true" style="font-size:${beforeSize}px;left:${pad}px">${esc(before)}</span><span class="metric-after" style="font-size:${size}px;padding:0 ${pad}px;${afterStyle}">${metricContent}</span></div>`;
   continue;
  }
  const style=`left:${x}px;top:${y}px;width:${w}px;min-height:${h}px;font-size:${size}px;font-family:'${font}';color:${color};--delay:${Math.min(j*85,650)}ms`;
  parts+=`<div class="piece" style="${style}">${a[8]?`<a href="${esc(a[8])}" target="_blank" rel="noopener">${html}</a>`:html}</div>`;
 }
 sections+=`<section class="slide${i===0?' active':''}${s.reveal?' overtake':''}" aria-label="${i+1}. ${esc(s.title)}" aria-hidden="${i!==0}" style="background:${s.bg}">${parts}</section>`;
}
const html=`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>papr — pitch deck</title><style>
*{box-sizing:border-box}body{margin:0;background:#111f31;overflow:hidden;font-family:Bahnschrift,sans-serif}#viewport{position:absolute;inset:0;display:grid;place-items:center;perspective:1800px}#stage{width:1280px;height:720px;position:absolute;transform-origin:center;box-shadow:0 20px 90px #0005}.slide{position:absolute;inset:0;visibility:hidden;overflow:hidden;backface-visibility:hidden;transform-origin:8% 50%;isolation:isolate}.slide.active{visibility:visible;z-index:2;animation:paper-in 850ms cubic-bezier(.16,1,.3,1) both}.slide.depart{visibility:visible;z-index:1;animation:paper-out 700ms ease both}.piece{position:absolute;line-height:1.17;white-space:normal}.active .piece{animation:ink-in 850ms cubic-bezier(.16,1,.3,1) both;animation-delay:var(--delay)}.logo{object-fit:contain}.active .logo{animation-name:logo-in}a{color:inherit;text-decoration:none}a:hover{text-decoration:underline}
@keyframes paper-in{from{opacity:.1;clip-path:inset(0 0 0 100%);transform:perspective(1600px) translateX(48px) rotateY(-4deg)}to{opacity:1;clip-path:inset(0);transform:none}}@keyframes paper-out{to{opacity:0;transform:translateX(-45px) scale(.975)}}@keyframes ink-in{from{opacity:0;transform:translateY(18px);filter:blur(3px)}to{opacity:1;transform:none;filter:none}}@keyframes logo-in{from{opacity:0;clip-path:inset(0 100% 0 0);transform:translateY(12px)}to{opacity:1;clip-path:inset(0);transform:none}}
nav{position:fixed;z-index:9;bottom:12px;left:50%;transform:translateX(-50%);display:flex;align-items:center;gap:18px;background:#111f31ed;border:1px solid #beddff50;color:white;padding:8px 16px;border-radius:4px;opacity:0;transition:opacity .2s}body.controls nav,nav:hover,nav:focus-within{opacity:1}button{background:transparent;border:0;color:inherit;font:14px Bahnschrift;cursor:pointer;padding:6px}button:focus-visible{outline:2px solid #beddff}button:disabled{opacity:.3;cursor:default}#notes{position:fixed;z-index:10;right:24px;top:24px;max-width:430px;background:#fff;color:#111f31;padding:24px;line-height:1.5;box-shadow:0 8px 45px #0005}#notes[hidden]{display:none}#notes button{float:right;color:#111f31}#status{font-size:13px;min-width:40px;text-align:center}#hint{font-size:11px;color:#beddff}

.provenance{font:inherit;line-height:inherit;padding:0;margin:0;border:0;display:block;color:inherit;background:transparent}.provenance:hover{text-decoration:underline}.slide.overtake.active{animation:none}.slide.overtake.active .piece{animation:none}.metric-window{position:absolute;overflow:hidden;line-height:1.17}.metric-window span{position:absolute;left:0;top:0;white-space:nowrap}.metric-before{visibility:hidden}.active .metric-before{visibility:visible;animation:metric-out 1000ms cubic-bezier(.65,0,.2,1) both}.active .metric-after{animation:metric-in 1000ms cubic-bezier(.65,0,.2,1) both}@keyframes metric-in{from{transform:translateY(125%);opacity:0}to{transform:translateY(0);opacity:1}}@keyframes metric-out{from{transform:translateY(0);opacity:1}to{transform:translateY(-125%);opacity:0}}@keyframes target-copy{from{opacity:0}to{opacity:1}}

@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}.metric-before{display:none!important}}
@media print{body{overflow:visible;background:white}#viewport{position:static;display:block}#stage{position:static;transform:none!important;box-shadow:none;width:100%}.slide{position:relative;visibility:visible!important;width:1280px;height:720px;page-break-after:always;animation:none!important}.piece{animation:none!important}.metric-before{display:none!important}nav,#notes{display:none!important}@page{size:13.333in 7.5in;margin:0}}
</style></head><body class="controls"><main id="viewport"><div id="stage">${sections}</div></main><nav aria-label="Presentation controls"><button id="prev" aria-label="Previous slide">←</button><span id="status" aria-live="polite">1 / ${slides.length}</span><button id="next" aria-label="Next slide">→</button><button id="full">Fullscreen</button><button id="notesToggle">Notes</button><span id="hint">← → to navigate · F fullscreen · N notes</span></nav><aside id="notes" hidden><button id="closeNotes" aria-label="Close notes">×</button><h3>Presenter notes</h3><p id="noteText"></p></aside><script>
const notes=${JSON.stringify(slides.map(s=>s.notes)).replaceAll('<','\\u003c')};
const pages=[...document.querySelectorAll('.slide')],stage=document.getElementById('stage');let current=0,tid;
function resize(){stage.style.transform='scale('+Math.min(innerWidth/1280,innerHeight/720)+')'}
function show(n){n=Math.max(0,Math.min(pages.length-1,n));if(n===current)return;const old=pages[current];old.classList.remove('active');old.classList.add('depart');old.setAttribute('aria-hidden','true');setTimeout(()=>old.classList.remove('depart'),750);current=n;pages[n].classList.remove('depart');pages[n].classList.add('active');pages[n].setAttribute('aria-hidden','false');update();history.replaceState(null,'','#'+(current+1))}
function update(){document.getElementById('status').textContent=(current+1)+' / '+pages.length;document.getElementById('prev').disabled=current===0;document.getElementById('next').disabled=current===pages.length-1;document.getElementById('noteText').textContent=notes[current]}
document.querySelectorAll('.provenance').forEach(button=>button.addEventListener('click',()=>{document.getElementById('noteText').textContent=button.dataset.note;document.getElementById('notes').hidden=false}));
function toggleNotes(){document.getElementById('noteText').textContent=notes[current];document.getElementById('notes').hidden=!document.getElementById('notes').hidden}
async function fullscreen(){try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen()}catch{}}
document.getElementById('prev').onclick=()=>show(current-1);document.getElementById('next').onclick=()=>show(current+1);document.getElementById('full').onclick=fullscreen;document.getElementById('notesToggle').onclick=toggleNotes;document.getElementById('closeNotes').onclick=toggleNotes;
addEventListener('keydown',e=>{if(['ArrowRight','ArrowDown','PageDown',' '].includes(e.key)){e.preventDefault();show(current+1)}if(['ArrowLeft','ArrowUp','PageUp'].includes(e.key)){e.preventDefault();show(current-1)}if(e.key==='Home')show(0);if(e.key==='End')show(pages.length-1);if(e.key.toLowerCase()==='f')fullscreen();if(e.key.toLowerCase()==='n')toggleNotes();if(e.key==='Escape')document.getElementById('notes').hidden=true});
let touchX=0;addEventListener('touchstart',e=>touchX=e.changedTouches[0].clientX,{passive:true});addEventListener('touchend',e=>{let dx=e.changedTouches[0].clientX-touchX;if(Math.abs(dx)>60)show(current+(dx<0?1:-1))},{passive:true});
function controls(){document.body.classList.add('controls');clearTimeout(tid);tid=setTimeout(()=>document.body.classList.remove('controls'),2300)}addEventListener('pointermove',controls);addEventListener('resize',resize);resize();update();controls();if(location.hash)show(Number(location.hash.slice(1))-1);
</script></body></html>`;
await fs.writeFile(new URL('papr-animated.html',root),html);
console.log('Created self-contained animated deck with '+slides.length+' slides.');

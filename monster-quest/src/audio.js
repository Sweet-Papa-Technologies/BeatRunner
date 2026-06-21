// Music streaming + procedural WebAudio sound effects.
const tracks = {
  overworld: 'assets/audio/overworld.ogg',
  boss:      'assets/audio/boss.ogg',
  calm:      'assets/audio/calm.ogg',
};
const narration = {
  n1: 'assets/audio/narration1.mp3',
  n2: 'assets/audio/narration2.mp3',
};

let ctx = null;
let curMusic = null, curName = null;
let musicVol = 0.55, sfxVol = 0.5;
let _muted = false;

export function initAudio(){
  try{ ctx = new (window.AudioContext||window.webkitAudioContext)(); }catch(e){}
}
export function resumeAudio(){ if(ctx && ctx.state==='suspended') ctx.resume(); }

// ---------------- Music ----------------
export function playMusic(name, {loop=true, fade=1.2}={}){
  if (curName===name && curMusic && !curMusic.paused) return;
  const url = tracks[name]; if(!url) return;
  const next = new Audio(url);
  next.loop = loop; next.volume = 0;
  const p = next.play();
  if (p && p.catch) p.catch(()=>{}); // autoplay may be blocked until gesture
  const old = curMusic;
  curMusic = next; curName = name;
  const target = _muted?0:musicVol;
  const t0 = performance.now();
  const step = ()=>{
    const k = Math.min(1,(performance.now()-t0)/(fade*1000));
    next.volume = target*k;
    if (old) old.volume = Math.max(0,(old._base||musicVol)*(1-k));
    if (k<1) requestAnimationFrame(step);
    else if (old){ old.pause(); }
  };
  if(old) old._base = old.volume;
  step();
}
export function stopMusic(fade=0.8){
  const old = curMusic; if(!old) return; curMusic=null; curName=null;
  const t0=performance.now(); const b=old.volume;
  const step=()=>{ const k=Math.min(1,(performance.now()-t0)/(fade*1000));
    old.volume=b*(1-k); if(k<1) requestAnimationFrame(step); else old.pause(); };
  step();
}
export function playNarration(key){
  return new Promise(res=>{
    const url=narration[key]; if(!url){res();return;}
    const a=new Audio(url); a.volume=_muted?0:0.95;
    a.onended=res; a.onerror=res;
    const p=a.play(); if(p&&p.catch)p.catch(()=>res());
    window._curNarration=a;
  });
}
export function stopNarration(){ if(window._curNarration){ window._curNarration.pause(); window._curNarration=null; } }
export function toggleMute(){ _muted=!_muted; if(curMusic)curMusic.volume=_muted?0:musicVol; return _muted; }

// ---------------- SFX (synth) ----------------
function env(node, t, a, d, peak){
  const g=node; g.gain.cancelScheduledValues(t);
  g.gain.setValueAtTime(0,t); g.gain.linearRampToValueAtTime(peak,t+a);
  g.gain.exponentialRampToValueAtTime(0.0001,t+a+d);
}
function tone(freq, type, a, d, peak, slideTo){
  if(!ctx) return; const t=ctx.currentTime;
  const o=ctx.createOscillator(), g=ctx.createGain();
  o.type=type; o.frequency.setValueAtTime(freq,t);
  if(slideTo) o.frequency.exponentialRampToValueAtTime(slideTo,t+a+d);
  env(g,t,a,d,peak*sfxVol*(_muted?0:1));
  o.connect(g).connect(ctx.destination); o.start(t); o.stop(t+a+d+0.05);
}
function noise(d, peak, lp=1200){
  if(!ctx) return; const t=ctx.currentTime;
  const n=Math.floor(ctx.sampleRate*d); const buf=ctx.createBuffer(1,n,ctx.sampleRate);
  const data=buf.getChannelData(0); for(let i=0;i<n;i++)data[i]=Math.random()*2-1;
  const src=ctx.createBufferSource(); src.buffer=buf;
  const f=ctx.createBiquadFilter(); f.type='lowpass'; f.frequency.value=lp;
  const g=ctx.createGain(); env(g,t,0.005,d,peak*sfxVol*(_muted?0:1));
  src.connect(f).connect(g).connect(ctx.destination); src.start(t); src.stop(t+d+0.05);
}

export const sfx = {
  jump(){ tone(330,'square',0.01,0.18,0.25,640); },
  land(){ noise(0.08,0.22,800); },
  coin(){ tone(880,'square',0.01,0.08,0.22,0); setTimeout(()=>tone(1320,'square',0.01,0.12,0.22,0),60); },
  gem(){ tone(660,'triangle',0.01,0.1,0.25,0); setTimeout(()=>tone(990,'triangle',0.01,0.14,0.25,1480),70); },
  hit(){ noise(0.12,0.4,500); tone(160,'sawtooth',0.005,0.15,0.25,60); },
  hurt(){ tone(220,'sawtooth',0.005,0.3,0.3,90); noise(0.15,0.25,400); },
  attack(){ tone(520,'triangle',0.005,0.12,0.22,180); noise(0.06,0.15,2200); },
  cast(name){ const base={fire:440,water:520,vine:380}[name]||440;
    tone(base,'sine',0.02,0.25,0.25,base*2.2); tone(base*1.5,'triangle',0.05,0.3,0.15,0); },
  capture(){ [523,659,784,1047].forEach((f,i)=>setTimeout(()=>tone(f,'triangle',0.01,0.18,0.22,0),i*90)); },
  open(){ tone(196,'sine',0.02,0.5,0.3,392); noise(0.4,0.18,600); },
  bossRoar(){ tone(90,'sawtooth',0.05,0.8,0.4,55); noise(0.6,0.3,300); },
  victory(){ [523,659,784,1047,1319].forEach((f,i)=>setTimeout(()=>tone(f,'triangle',0.02,0.35,0.25,0),i*140)); },
  select(){ tone(740,'square',0.005,0.06,0.18,0); },
};

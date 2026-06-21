import * as THREE from 'three';

// Manifest: logical name -> file path. Missing/failed files fall back to a
// procedurally-drawn placeholder so the game always runs.
export const MANIFEST = {
  // sprites (transparent PNGs)
  hero:   'assets/sprites/hero.png',
  ember:  'assets/sprites/ember.png',
  aqua:   'assets/sprites/aqua.png',
  vine:   'assets/sprites/vine.png',
  boss:   'assets/sprites/boss.png',
  sage:   'assets/sprites/sage.png',
  gem:    'assets/sprites/gem.png',
  heart:  'assets/sprites/heart.png',
  key:    'assets/sprites/key.png',
  orb_fire:'assets/sprites/orb_fire.png',
  // textures
  grass:  'assets/textures/grass.png',
  stone:  'assets/textures/stone.png',
  crystal:'assets/textures/crystal.png',
  wood:   'assets/textures/wood.png',
  lava:   'assets/textures/lava.png',
  sky:    'assets/textures/sky.png',
  // cutscene / title (DOM backgrounds)
  scene1: 'assets/cutscene/scene1.png',
  scene2: 'assets/cutscene/scene2.png',
  scene3: 'assets/cutscene/scene3.png',
  title_bg:'assets/cutscene/title_bg.png',
};

const _tex = {};       // THREE.Texture cache
const _url = {};       // resolved usable URL (real or placeholder dataURL)
const _ok  = {};       // whether the real file loaded

// ---- procedural placeholders ----
const PLACE = {
  hero:['#6bd06b','◆',true], ember:['#ff7a3c','🔥',true], aqua:['#4fb8ff','💧',true],
  vine:['#7ad04f','🌿',true], boss:['#9a6bff','☠',true], sage:['#d9c27a','✦',true],
  gem:['#4fe3d0','💎',true], heart:['#ff4d6d','❤',true], key:['#ffd36b','🗝',true],
  orb_fire:['#ff9a3c','◉',true],
  grass:['#3f9d5a','grass',false], stone:['#6c6f86','stone',false],
  crystal:['#7a5cff','crystal',false], wood:['#9b6b3a','wood',false],
  lava:['#ff5a2c','lava',false], sky:['#4a6fbf','sky',false],
  scene1:['#2c4a6e','',false], scene2:['#3e6e4a','',false],
  scene3:['#3a2a55','',false], title_bg:['#26406e','',false],
};

function placeholder(name){
  const [color, glyph, isSprite] = PLACE[name] || ['#888','?',true];
  const s = 256;
  const c = document.createElement('canvas'); c.width = c.height = s;
  const g = c.getContext('2d');
  if (isSprite){
    // blobby creature/icon silhouette on transparent bg
    g.clearRect(0,0,s,s);
    const grd = g.createRadialGradient(s/2,s*0.42,10,s/2,s*0.5,s*0.42);
    grd.addColorStop(0,'#ffffff'); grd.addColorStop(.25,color); grd.addColorStop(1,shade(color,-40));
    g.fillStyle = grd;
    g.beginPath(); g.ellipse(s/2,s*0.52,s*0.34,s*0.40,0,0,Math.PI*2); g.fill();
    g.font = `${s*0.34}px serif`; g.textAlign='center'; g.textBaseline='middle';
    g.fillText(glyph, s/2, s*0.54);
  } else {
    // tileable texture: base + noise
    g.fillStyle = color; g.fillRect(0,0,s,s);
    for(let i=0;i<2600;i++){
      g.fillStyle = `rgba(${rnd()},${rnd()},${rnd()},0.06)`;
      const x=Math.random()*s,y=Math.random()*s,r=Math.random()*7+1;
      g.beginPath(); g.arc(x,y,r,0,Math.PI*2); g.fill();
    }
    g.strokeStyle='rgba(0,0,0,.18)'; g.lineWidth=2;
    g.strokeRect(2,2,s-4,s-4);
    g.fillStyle='rgba(255,255,255,.5)'; g.font='20px sans-serif'; g.textAlign='center';
    g.fillText(glyph, s/2, s/2);
  }
  return c.toDataURL('image/png');
}
function rnd(){return Math.floor(Math.random()*255);}
function shade(hex,amt){
  const n=parseInt(hex.slice(1),16);
  let r=(n>>16)+amt,gg=((n>>8)&255)+amt,b=(n&255)+amt;
  r=Math.max(0,Math.min(255,r));gg=Math.max(0,Math.min(255,gg));b=Math.max(0,Math.min(255,b));
  return `rgb(${r},${gg},${b})`;
}

function loadOne(name, path){
  return new Promise((resolve)=>{
    const img = new Image();
    let done=false;
    const finish=(ok,url)=>{ if(done)return; done=true; _ok[name]=ok; _url[name]=url; resolve(); };
    img.onload = ()=>{ if(img.naturalWidth>0) finish(true, path); else finish(false, placeholder(name)); };
    img.onerror= ()=> finish(false, placeholder(name));
    img.src = path + '?v=1';
    // safety timeout
    setTimeout(()=>finish(false, placeholder(name)), 8000);
  });
}

export async function loadAssets(onProgress){
  const names = Object.keys(MANIFEST);
  let n=0;
  for (const name of names){
    await loadOne(name, MANIFEST[name]);
    n++; onProgress && onProgress(n/names.length, name);
  }
}

// THREE texture (lazily built from resolved url)
export function tex(name, opts={}){
  if (_tex[name]) return _tex[name];
  const loader = new THREE.TextureLoader();
  const t = loader.load(_url[name] || placeholder(name));
  t.colorSpace = THREE.SRGBColorSpace;
  if (opts.repeat){ t.wrapS=t.wrapT=THREE.RepeatWrapping; t.repeat.set(opts.repeat[0],opts.repeat[1]); }
  t.anisotropy = 8;
  _tex[name]=t; return t;
}
export function url(name){ return _url[name] || placeholder(name); }
export function loaded(name){ return !!_ok[name]; }

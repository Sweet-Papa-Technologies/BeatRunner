import * as THREE from 'three';
import { tex } from './assets.js';

export const engine = {
  scene:null, camera:null, renderer:null, composer:null, clock:null,
  camTarget:new THREE.Vector3(), camOffset:new THREE.Vector3(0,16,15),
  bloom:null, _shake:0,
};

export async function initEngine(canvas){
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0a1024);
  scene.fog = new THREE.Fog(0x12203f, 40, 120);

  const camera = new THREE.PerspectiveCamera(52, innerWidth/innerHeight, 0.1, 600);
  camera.position.set(0,16,15);

  const renderer = new THREE.WebGLRenderer({canvas, antialias:true, powerPreference:'high-performance'});
  renderer.setSize(innerWidth, innerHeight);
  renderer.setPixelRatio(Math.min(devicePixelRatio,2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.08;
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  // ----- lights -----
  const hemi = new THREE.HemisphereLight(0xbfd4ff, 0x33402a, 0.85);
  scene.add(hemi);
  const sun = new THREE.DirectionalLight(0xfff0d0, 1.6);
  sun.position.set(28,40,18);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048,2048);
  sun.shadow.camera.near=1; sun.shadow.camera.far=160;
  const d=70; const sc=sun.shadow.camera;
  sc.left=-d; sc.right=d; sc.top=d; sc.bottom=-d; sc.updateProjectionMatrix();
  sun.shadow.bias=-0.0004;
  scene.add(sun);
  const rim = new THREE.DirectionalLight(0x6b8cff, 0.5);
  rim.position.set(-20,18,-22); scene.add(rim);
  engine.sun = sun;

  // ----- skydome -----
  const skyGeo = new THREE.SphereGeometry(300,32,16);
  const skyMat = new THREE.MeshBasicMaterial({ map: tex('sky'), side:THREE.BackSide, fog:false });
  const sky = new THREE.Mesh(skyGeo, skyMat); scene.add(sky); engine.sky=sky;

  engine.scene=scene; engine.camera=camera; engine.renderer=renderer; engine.clock=new THREE.Clock();

  // ----- post processing (graceful fallback if addons fail) -----
  try{
    const { EffectComposer } = await import('three/addons/postprocessing/EffectComposer.js');
    const { RenderPass } = await import('three/addons/postprocessing/RenderPass.js');
    const { UnrealBloomPass } = await import('three/addons/postprocessing/UnrealBloomPass.js');
    const { OutputPass } = await import('three/addons/postprocessing/OutputPass.js');
    const composer = new EffectComposer(renderer);
    composer.addPass(new RenderPass(scene,camera));
    const bloom = new UnrealBloomPass(new THREE.Vector2(innerWidth,innerHeight), 0.6, 0.6, 0.82);
    composer.addPass(bloom);
    composer.addPass(new OutputPass());
    engine.composer=composer; engine.bloom=bloom;
  }catch(e){ console.warn('Bloom unavailable, using direct render', e); }

  addEventListener('resize', ()=>{
    camera.aspect = innerWidth/innerHeight; camera.updateProjectionMatrix();
    renderer.setSize(innerWidth,innerHeight);
    engine.composer && engine.composer.setSize(innerWidth,innerHeight);
  });
  return engine;
}

export function render(){
  if (engine.composer) engine.composer.render();
  else engine.renderer.render(engine.scene, engine.camera);
}

// smooth follow camera, with shake
export function updateCamera(targetPos, dt){
  engine.camTarget.lerp(targetPos, 1-Math.pow(0.001,dt));
  const want = engine.camTarget.clone().add(engine.camOffset);
  engine.camera.position.lerp(want, 1-Math.pow(0.0001,dt));
  if (engine._shake>0){
    engine._shake = Math.max(0, engine._shake-dt*2.2);
    const s=engine._shake*engine._shake*1.4;
    engine.camera.position.x += (Math.random()-.5)*s;
    engine.camera.position.y += (Math.random()-.5)*s;
  }
  engine.camera.lookAt(engine.camTarget.x, engine.camTarget.y+1.5, engine.camTarget.z);
}
export function shake(amount=1){ engine._shake = Math.min(2, engine._shake+amount); }

// ---------------- Billboard sprite (upright, faces camera around Y) ----------------
export class Billboard extends THREE.Group{
  constructor(texName, w=2, h=2){
    super();
    const t = tex(texName);
    const mat = new THREE.MeshBasicMaterial({ map:t, transparent:true, alphaTest:0.35,
      side:THREE.DoubleSide, depthWrite:true });
    this.mesh = new THREE.Mesh(new THREE.PlaneGeometry(w,h), mat);
    this.mesh.position.y = h/2;
    this.mesh.castShadow = true;
    this.add(this.mesh);
    this.h=h; this.w=w;
    // soft ground shadow
    const shTex = makeBlobShadow();
    this.shadow = new THREE.Mesh(new THREE.PlaneGeometry(w*0.9,w*0.7),
      new THREE.MeshBasicMaterial({map:shTex,transparent:true,opacity:.5,depthWrite:false}));
    this.shadow.rotation.x = -Math.PI/2; this.shadow.position.y=0.02;
    this.add(this.shadow);
    this._baseScale=1;
  }
  faceCamera(cam){
    const a = Math.atan2(cam.position.x-this.position.x, cam.position.z-this.position.z);
    this.mesh.rotation.y = a;
  }
  setFlip(left){ this.mesh.scale.x = left? -1:1; }
  bob(t, amp=0.12, spd=4){ this.mesh.position.y = this.h/2 + Math.sin(t*spd)*amp; }
}

let _blob;
function makeBlobShadow(){
  if(_blob) return _blob;
  const c=document.createElement('canvas'); c.width=c.height=128; const g=c.getContext('2d');
  const grd=g.createRadialGradient(64,64,4,64,64,62);
  grd.addColorStop(0,'rgba(0,0,0,.65)'); grd.addColorStop(1,'rgba(0,0,0,0)');
  g.fillStyle=grd; g.fillRect(0,0,128,128);
  _blob=new THREE.CanvasTexture(c); return _blob;
}

// ---------------- Particle burst ----------------
const _bursts=[];
export function burst(scene, pos, color=0xffd36b, count=24, spread=0.35, life=0.7, size=0.35){
  const geo=new THREE.BufferGeometry();
  const pa=new Float32Array(count*3), va=[];
  for(let i=0;i<count;i++){
    pa[i*3]=pos.x; pa[i*3+1]=pos.y; pa[i*3+2]=pos.z;
    const dir=new THREE.Vector3((Math.random()-.5),(Math.random()*1.1),(Math.random()-.5)).normalize()
      .multiplyScalar(spread*(0.5+Math.random()));
    va.push(dir);
  }
  geo.setAttribute('position',new THREE.BufferAttribute(pa,3));
  const mat=new THREE.PointsMaterial({color,size,transparent:true,opacity:1,
    blending:THREE.AdditiveBlending,depthWrite:false});
  const pts=new THREE.Points(geo,mat); scene.add(pts);
  _bursts.push({pts,va,life,age:0,geo,mat});
}
export function updateParticles(dt){
  for(let i=_bursts.length-1;i>=0;i--){
    const b=_bursts[i]; b.age+=dt;
    const p=b.geo.attributes.position.array;
    for(let j=0;j<b.va.length;j++){
      b.va[j].y -= dt*2.2;
      p[j*3]+=b.va[j].x*dt*9; p[j*3+1]+=b.va[j].y*dt*9; p[j*3+2]+=b.va[j].z*dt*9;
    }
    b.geo.attributes.position.needsUpdate=true;
    b.mat.opacity=Math.max(0,1-b.age/b.life);
    if(b.age>=b.life){ engine.scene.remove(b.pts); b.geo.dispose(); b.mat.dispose(); _bursts.splice(i,1); }
  }
}

// ---------------- Input ----------------
export const input = { keys:{}, pressed:{}, _consumed:{} };
export function initInput(){
  addEventListener('keydown',e=>{
    const k=e.key.toLowerCase();
    if(!input.keys[k]) input.pressed[k]=true;
    input.keys[k]=true;
    if(['arrowup','arrowdown','arrowleft','arrowright',' '].includes(k)) e.preventDefault();
  });
  addEventListener('keyup',e=>{ input.keys[e.key.toLowerCase()]=false; });
  addEventListener('blur',()=>{ input.keys={}; });
}
// returns true once per physical press
export function justPressed(k){ if(input.pressed[k]){ input.pressed[k]=false; return true;} return false; }
export function clearPressed(){ input.pressed={}; }

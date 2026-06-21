import * as THREE from 'three';
import { tex, url } from './assets.js';
import { Billboard } from './engine.js';

// A solid floor box (stand on top) and/or wall (block sides).
function floorBox(minx,maxx,minz,maxz,top){ return {minx,maxx,minz,maxz,top}; }

export function buildWorld(scene){
  const W = {
    floors:[], walls:[], deadly:[], interact:[], decor:[], motes:[],
    spawn:new THREE.Vector3(0,0,18),
    flames:[], gate:null, bossSpawn:new THREE.Vector3(0,0,-66),
  };

  const matFor = (name, rx, rz)=> new THREE.MeshStandardMaterial({
    map: tex(name,{repeat:[rx,rz]}), roughness:0.95, metalness:0.02 });

  // ---------- ground regions ----------
  function ground(name, x0,x1,z0,z1, y, rough){
    const w=x1-x0, d=z1-z0;
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w,d,1,1),
      new THREE.MeshStandardMaterial({map:tex(name,{repeat:[w/6,d/6]}),roughness:rough??0.95,metalness:0.02}));
    m.rotation.x=-Math.PI/2; m.position.set((x0+x1)/2,y,(z0+z1)/2); m.receiveShadow=true;
    scene.add(m);
    W.floors.push(floorBox(x0,x1,z0,z1,y));
    return m;
  }
  ground('grass', -22,22, -12,24, 0);            // meadow
  ground('stone', -24,24, -52,-30, 0);           // courtyard
  const arena = ground('crystal', -26,26, -78,-52, 0, 0.6); // boss arena
  arena.material.emissive = new THREE.Color(0x241a4a);
  arena.material.emissiveIntensity = 0.5;

  // ---------- chasm + lava ----------
  const lava = new THREE.Mesh(new THREE.PlaneGeometry(60,30),
    new THREE.MeshStandardMaterial({map:tex('lava',{repeat:[6,3]}),emissive:0xff4a10,
      emissiveIntensity:0.9, roughness:0.5}));
  lava.rotation.x=-Math.PI/2; lava.position.set(0,-2.4,-21); scene.add(lava);
  W.deadly.push({minx:-22,maxx:22,minz:-30,maxz:-12});
  W.lava = lava;
  const lavaLight = new THREE.PointLight(0xff5a20, 2.2, 40); lavaLight.position.set(0,1,-21); scene.add(lavaLight);

  // ---------- floating platforms over chasm ----------
  const plats = [
    [0,-14,0.8,3.2], [-6.5,-18,1.7,3.0], [6.5,-21.5,1.2,3.0], [0,-26,0.7,4.0],
    [10,-17,2.6,2.6], // high optional (gem)
  ];
  for (const [x,z,top,s] of plats){
    const h = top+ (2.0); // box thickness so it reads as a chunk
    const m = new THREE.Mesh(new THREE.BoxGeometry(s,h,s),
      new THREE.MeshStandardMaterial({map:tex('wood'),roughness:0.8}));
    m.position.set(x, top-h/2, z); m.castShadow=true; m.receiveShadow=true; scene.add(m);
    W.floors.push(floorBox(x-s/2,x+s/2,z-s/2,z+s/2,top));
    // glowing crystal on each platform corner for flair
    addCrystal(scene,W,x, top, z-0.0, 0x6fe0ff, 0.5);
  }

  // ---------- boundary walls ----------
  const addWall=(x0,x1,z0,z1,h)=>{
    const w=x1-x0,d=z1-z0;
    const m=new THREE.Mesh(new THREE.BoxGeometry(w,h,d),
      new THREE.MeshStandardMaterial({map:tex('stone',{repeat:[w/4,d/4]}),roughness:0.9}));
    m.position.set((x0+x1)/2,h/2,(z0+z1)/2); m.castShadow=true; m.receiveShadow=true; scene.add(m);
    W.walls.push({minx:x0,maxx:x1,minz:z0,maxz:z1,top:h});
  };
  addWall(-24,-22,-52,24,4);  addWall(22,24,-52,24,4);     // meadow+courtyard sides
  addWall(-26,-24,-78,-52,5); addWall(24,26,-78,-52,5);    // arena sides
  addWall(-24,24,24,26,4);                                  // south back wall
  addWall(-26,26,-80,-78,6);                                // north back wall

  // ---------- decorative trees & rocks in meadow ----------
  for (const [x,z] of [[-16,16],[15,10],[-12,4],[18,-2],[-18,-6],[12,-8],[-8,20],[9,20]]){
    addTree(scene,x,z);
  }
  for (const [x,z] of [[-19,2],[19,14],[-6,-9],[7,6]]) addRock(scene,x,z);

  // ---------- ambient floating motes ----------
  W.motePoints = addMotes(scene);

  // ---------- NPC: Sage ----------
  const sage = new Billboard('sage', 2.4, 3.0); sage.position.set(-3,0,12);
  scene.add(sage);
  W.interact.push({type:'npc', id:'sage', bb:sage, pos:sage.position, radius:3.2, done:false, prompt:'Talk (auto)'});
  W.sage = sage;

  // ---------- capturable companions ----------
  function addWild(elem, sprite, x, z){
    const bb=new Billboard(sprite, 1.8, 1.8); bb.position.set(x,0,z); scene.add(bb);
    const ring = ringMarker(scene, x, z, COL[elem]);
    W.interact.push({type:'wild', elem, sprite, bb, ring, pos:bb.position, radius:2.4, done:false});
  }
  addWild('fire','ember', 9, 2);
  addWild('water','aqua', -17,-34);
  addWild('vine','vine', 17,-34);

  // ---------- gems ----------
  const gemSpots=[[-8,8],[6,16],[-14,18],[14,4],[ -10,-2],[0,-14,2.0],[10,-17,3.6],
                  [-16,-44],[16,-44],[0,-36]];
  for (const g of gemSpots){
    const [x,z,y=0]=g;
    const bb=new Billboard('gem',1.1,1.1); bb.position.set(x,y,z); scene.add(bb);
    const gl=new THREE.PointLight(0x4fe3d0,0.6,5); gl.position.set(x,y+1,z); scene.add(gl);
    W.interact.push({type:'gem', bb, light:gl, pos:bb.position, radius:1.6, done:false, baseY:y});
  }

  // ---------- braziers (puzzle) ----------
  function addBrazier(x,z){
    const g=new THREE.Group();
    const bowl=new THREE.Mesh(new THREE.CylinderGeometry(0.9,0.5,0.7,12),
      new THREE.MeshStandardMaterial({color:0x3a3346,metalness:0.6,roughness:0.4}));
    bowl.position.y=1.4; bowl.castShadow=true;
    const stem=new THREE.Mesh(new THREE.CylinderGeometry(0.25,0.35,1.4,8),
      new THREE.MeshStandardMaterial({color:0x2a2636,metalness:0.5,roughness:0.5}));
    stem.position.y=0.7;
    g.add(stem,bowl); g.position.set(x,0,z); scene.add(g);
    // flame (hidden until lit)
    const flame=new Billboard('orb_fire',1.6,1.8); flame.position.set(x,1.5,z); flame.visible=false; scene.add(flame);
    const light=new THREE.PointLight(0xff7a2a,0,12); light.position.set(x,2.6,z); scene.add(light);
    W.interact.push({type:'brazier', group:g, flame, light, pos:new THREE.Vector3(x,1.5,z),
      radius:2.6, lit:false, done:false});
  }
  addBrazier(-12,-40); addBrazier(0,-45); addBrazier(12,-40);

  // ---------- gate ----------
  const gate=new THREE.Group();
  const pillarMat=new THREE.MeshStandardMaterial({map:tex('stone'),roughness:0.85});
  const pL=new THREE.Mesh(new THREE.BoxGeometry(2,8,2),pillarMat); pL.position.set(-5,4,-52);
  const pR=pL.clone(); pR.position.x=5;
  const bar=new THREE.Mesh(new THREE.BoxGeometry(12,1.4,1.4),
    new THREE.MeshStandardMaterial({color:0x6a4a2a,roughness:0.7}));
  bar.position.set(0,7,-52);
  const seal=new THREE.Mesh(new THREE.PlaneGeometry(10,8),
    new THREE.MeshStandardMaterial({color:0x9a6bff,emissive:0x6a3bff,emissiveIntensity:1.4,
      transparent:true,opacity:0.55,side:THREE.DoubleSide}));
  seal.position.set(0,4,-52);
  [pL,pR,bar].forEach(m=>{m.castShadow=true;});
  gate.add(pL,pR,bar,seal); scene.add(gate);
  W.gate={group:gate, seal, bar, open:false,
    wall:{minx:-6,maxx:6,minz:-53,maxz:-51,top:8}};
  W.walls.push(W.gate.wall);

  // crystals lining the arena
  for(let i=0;i<10;i++){ const a=i/10*Math.PI*2; addCrystal(scene,W,Math.cos(a)*23,0,-65+Math.sin(a)*11,
    i%2?0x9a6bff:0x6fe0ff, 1.0+Math.random()); }

  return W;
}

// ----------------- helpers -----------------
const COL = {fire:0xff7a3c, water:0x4fb8ff, vine:0x7ad04f};

function addCrystal(scene,W,x,y,z,color,scale=1){
  const m=new THREE.Mesh(new THREE.OctahedronGeometry(0.6*scale,0),
    new THREE.MeshStandardMaterial({color,emissive:color,emissiveIntensity:1.3,
      roughness:0.2,metalness:0.1,transparent:true,opacity:0.92}));
  m.position.set(x,y+0.8*scale,z); m.castShadow=true; scene.add(m);
  const l=new THREE.PointLight(color,0.5,8); l.position.set(x,y+1,z); scene.add(l);
  W.decor.push({m,base:y+0.8*scale,spin:0.5+Math.random()});
}
function addTree(scene,x,z){
  const trunk=new THREE.Mesh(new THREE.CylinderGeometry(0.4,0.6,3,8),
    new THREE.MeshStandardMaterial({color:0x6b4a2a,roughness:0.9}));
  trunk.position.set(x,1.5,z); trunk.castShadow=true;
  const make=(r,y,c)=>{const m=new THREE.Mesh(new THREE.IcosahedronGeometry(r,0),
    new THREE.MeshStandardMaterial({color:c,roughness:0.8,flatShading:true}));
    m.position.set(x,y,z); m.castShadow=true; return m;};
  scene.add(trunk, make(2.0,4.2,0x3f9d4a), make(1.5,5.4,0x4fb35a), make(1.1,6.3,0x62c46e));
}
function addRock(scene,x,z){
  const m=new THREE.Mesh(new THREE.DodecahedronGeometry(0.9+Math.random()*0.6,0),
    new THREE.MeshStandardMaterial({color:0x6c6f86,roughness:0.95,flatShading:true}));
  m.position.set(x,0.5,z); m.rotation.set(Math.random(),Math.random(),Math.random());
  m.castShadow=true; m.receiveShadow=true; scene.add(m);
}
function ringMarker(scene,x,z,color){
  const m=new THREE.Mesh(new THREE.RingGeometry(1.3,1.7,28),
    new THREE.MeshBasicMaterial({color,transparent:true,opacity:0.7,side:THREE.DoubleSide}));
  m.rotation.x=-Math.PI/2; m.position.set(x,0.06,z); scene.add(m); return m;
}
function addMotes(scene){
  const N=180; const g=new THREE.BufferGeometry(); const p=new Float32Array(N*3);
  for(let i=0;i<N;i++){ p[i*3]=(Math.random()-.5)*90; p[i*3+1]=Math.random()*16+1; p[i*3+2]=(Math.random()*1)*-80+20; }
  g.setAttribute('position',new THREE.BufferAttribute(p,3));
  const m=new THREE.PointsMaterial({color:0xfff0c0,size:0.18,transparent:true,opacity:0.8,
    blending:THREE.AdditiveBlending,depthWrite:false});
  const pts=new THREE.Points(g,m); scene.add(pts); return pts;
}

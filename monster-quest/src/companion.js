import * as THREE from 'three';
import { Billboard, burst, justPressed } from './engine.js';
import { sfx } from './audio.js';

export const SPECIES = {
  fire:  {name:'Ember', sprite:'ember', color:0xff7a3c, dmg:2.0, cd:0.5},
  water: {name:'Aqua',  sprite:'aqua',  color:0x4fb8ff, dmg:1.5, cd:0.45},
  vine:  {name:'Sprout',sprite:'vine',  color:0x7ad04f, dmg:1.5, cd:0.5},
};

export class Companions{
  constructor(scene, game){
    this.scene=scene; this.game=game;
    this.roster=[];            // ['fire','water',...]
    this.active=-1;
    this.bb=null;              // floating sprite of active companion
    this.shots=[];
    this.cd=0;
    this.t=0;
  }
  has(elem){ return this.roster.includes(elem); }
  capture(elem){
    if(this.has(elem)) return false;
    this.roster.push(elem);
    if(this.active<0) this.setActive(0);
    this.game.ui.buildRoster(this.roster, this.active);
    sfx.capture();
    return true;
  }
  setActive(i){
    if(i<0||i>=this.roster.length) return;
    this.active=i;
    const sp=SPECIES[this.roster[i]];
    if(this.bb){ this.scene.remove(this.bb); }
    this.bb=new Billboard(sp.sprite, 1.5, 1.5);
    this.scene.add(this.bb);
    this.game.ui.buildRoster(this.roster, this.active);
    sfx.select();
    burst(this.scene,this.game.player.pos.clone().setY(1.5),sp.color,16,0.4,0.5);
  }
  activeElem(){ return this.active>=0 ? this.roster[this.active] : null; }

  cast(){
    const elem=this.activeElem(); if(!elem||this.cd>0) return null;
    const sp=SPECIES[elem]; this.cd=sp.cd;
    const p=this.game.player;
    const dir=new THREE.Vector3(p.facingLeft?-1:1,0,0);
    // aim slightly toward nearest target if any
    const tgt=this._nearestTarget(p.pos, 30);
    if(tgt){ dir.copy(tgt.pos.clone().sub(p.pos).setY(0).normalize()); }
    const origin=(this.bb?this.bb.position:p.pos).clone().setY(1.5);
    const geo=new THREE.SphereGeometry(0.35,12,12);
    const mat=new THREE.MeshBasicMaterial({color:sp.color});
    const m=new THREE.Mesh(geo,mat); m.position.copy(origin); this.scene.add(m);
    const light=new THREE.PointLight(sp.color,1.4,8); m.add(light);
    this.shots.push({m,light,dir,elem,dmg:sp.dmg,color:sp.color,life:1.6,dist:0});
    sfx.cast(elem);
    this.game.ui.flashSlot(this.active, sp.cd);
    return elem;
  }
  _nearestTarget(from,maxd){
    let best=null,bd=maxd;
    for(const t of this.game.combatTargets){ if(!t.alive) continue;
      const d=t.pos.distanceTo(from); if(d<bd){bd=d;best=t;} }
    return best;
  }

  update(dt){
    this.t+=dt; this.cd=Math.max(0,this.cd-dt);
    const p=this.game.player;
    // switch companions
    if(this.roster.length){
      if(justPressed('1')) this.setActive(0);
      if(justPressed('2')&&this.roster.length>1) this.setActive(1);
      if(justPressed('3')&&this.roster.length>2) this.setActive(2);
      if(p.control && justPressed('e')) this.cast();
    }
    // float beside player
    if(this.bb){
      const f=p.facingLeft?1:-1;
      const want=new THREE.Vector3(p.pos.x+f*1.6, p.pos.y+1.8+Math.sin(this.t*3)*0.2, p.pos.z+0.4);
      this.bb.position.lerp(want, 1-Math.pow(0.002,dt));
      this.bb.faceCamera(this.game.camera);
    }
    // projectiles
    for(let i=this.shots.length-1;i>=0;i--){
      const s=this.shots[i];
      const step=s.dir.clone().multiplyScalar(28*dt);
      s.m.position.add(step); s.dist+=step.length(); s.life-=dt;
      if(this.t*60%2<1) burst(this.scene,s.m.position.clone(),s.color,4,0.15,0.3,0.18);
      // hit targets
      let hit=false;
      for(const t of this.game.combatTargets){ if(!t.alive) continue;
        if(t.pos.distanceTo(s.m.position)< (t.radius||1.6)){ t.hit(s.dmg, s.m.position.clone()); hit=true; break; } }
      if(hit||s.life<=0||s.dist>34){
        burst(this.scene,s.m.position.clone(),s.color,18,0.4,0.5);
        this.scene.remove(s.m); s.m.geometry.dispose(); s.m.material.dispose();
        this.shots.splice(i,1);
      }
    }
  }
}

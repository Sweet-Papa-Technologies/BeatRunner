import * as THREE from 'three';
import { Billboard, burst, shake } from './engine.js';
import { sfx } from './audio.js';

class Minion{
  constructor(scene, game, pos){
    this.scene=scene; this.game=game; this.alive=true; this.radius=1.1; this.hp=2;
    const geo=new THREE.IcosahedronGeometry(0.7,0);
    this.m=new THREE.Mesh(geo,new THREE.MeshStandardMaterial({color:0x2a1a44,
      emissive:0x6a3bff,emissiveIntensity:0.8,roughness:0.4,flatShading:true}));
    this.m.position.copy(pos); this.m.position.y=1.2; this.m.castShadow=true; scene.add(this.m);
    this.light=new THREE.PointLight(0x9a6bff,0.8,6); this.m.add(this.light);
    this.pos=this.m.position; this.t=Math.random()*6; this.touchCD=0;
  }
  hit(d){ this.hp-=d; burst(this.scene,this.pos.clone(),0x9a6bff,14,0.4,0.5);
    if(this.hp<=0) this.die(); }
  die(){ this.alive=false; burst(this.scene,this.pos.clone(),0x9a6bff,26,0.6,0.7); sfx.hit();
    this.scene.remove(this.m); this.m.geometry.dispose(); }
  update(dt){
    if(!this.alive) return;
    this.t+=dt; this.touchCD=Math.max(0,this.touchCD-dt);
    const p=this.game.player.pos;
    const dir=p.clone().sub(this.pos).setY(0); const dist=dir.length(); dir.normalize();
    this.pos.addScaledVector(dir, 6*dt);
    this.pos.y=1.2+Math.sin(this.t*4)*0.25;
    this.m.rotation.y+=dt*3; this.m.rotation.x+=dt*2;
    if(dist<1.4 && this.touchCD<=0){ this.touchCD=1; this.game.player.takeDamage(1,this.pos); }
  }
}

export class Boss{
  constructor(scene, game){
    this.scene=scene; this.game=game;
    this.maxHp=42; this.hp=42; this.alive=true; this.radius=2.6;
    this.bb=new Billboard('boss', 6.5, 8.5);
    this.home=game.world.bossSpawn.clone();
    this.bb.position.copy(this.home); this.bb.position.y=0;
    scene.add(this.bb);
    this.pos=new THREE.Vector3().copy(this.home).setY(4.2);
    this.shots=[]; this.minions=[];
    this.t=0; this.actT=2.2; this.phase=1; this.state='idle'; this.stateT=0;
    this.intro=true; this.introT=2.6;
    this.touchCD=0;
    // aura light
    this.aura=new THREE.PointLight(0x9a6bff,2.5,30); this.aura.position.copy(this.pos); scene.add(this.aura);
    game.combatTargets.push(this);
  }
  hit(d, from){
    if(!this.alive||this.intro) return;
    this.hp=Math.max(0,this.hp-d);
    this.game.ui.setBoss(this.hp/this.maxHp);
    burst(this.scene,(from||this.pos).clone(),0xff7a7a,10,0.3,0.4);
    this.bb.mesh.material.color.setRGB(2,0.6,0.6);
    setTimeout(()=>this.bb&&this.bb.mesh.material.color.setRGB(1,1,1),80);
    const ph = this.hp/this.maxHp;
    if(this.phase===1 && ph<=0.66){ this.enterPhase(2); }
    else if(this.phase===2 && ph<=0.33){ this.enterPhase(3); }
    if(this.hp<=0) this.die();
  }
  enterPhase(p){ this.phase=p; sfx.bossRoar(); shake(1.2);
    this.game.ui.banner(p===3?'PHASE 3 — FINAL FURY':'PHASE '+p, 1.3);
    burst(this.scene,this.pos.clone(),0x9a6bff,40,0.8,0.9); }
  die(){
    this.alive=false; this.state='dying'; sfx.bossRoar();
    this.minions.forEach(m=>m.die());
    this.game.onBossDefeated();
  }

  _fireVolley(n){
    const p=this.game.player.pos.clone().setY(1.4);
    for(let i=0;i<n;i++){
      const spread=(i-(n-1)/2)*0.22;
      const base=p.clone().sub(this.pos).setY(0).normalize();
      const dir=base.applyAxisAngle(new THREE.Vector3(0,1,0),spread);
      const m=new THREE.Mesh(new THREE.SphereGeometry(0.45,10,10),
        new THREE.MeshBasicMaterial({color:0x9a6bff}));
      m.position.copy(this.pos); this.scene.add(m);
      const l=new THREE.PointLight(0x9a6bff,1.2,6); m.add(l);
      this.shots.push({m,dir,life:3.0});
    }
    sfx.cast('fire');
  }
  _shockwave(){
    // telegraph ring expanding from boss; damages if player near ground close
    this.state='slam'; this.stateT=0.9;
    const ring=new THREE.Mesh(new THREE.RingGeometry(0.5,1.0,40),
      new THREE.MeshBasicMaterial({color:0xff4d6d,transparent:true,opacity:0.8,side:THREE.DoubleSide}));
    ring.rotation.x=-Math.PI/2; ring.position.set(this.pos.x,0.1,this.pos.z); this.scene.add(ring);
    this.wave={ring,r:1,hit:false};
  }
  _summon(){
    if(this.minions.filter(m=>m.alive).length>=4) return;
    for(let i=0;i<2;i++){
      const a=Math.random()*Math.PI*2;
      const pos=this.pos.clone().add(new THREE.Vector3(Math.cos(a)*5,0,Math.sin(a)*5));
      const mn=new Minion(this.scene,this.game,pos); this.minions.push(mn);
      this.game.combatTargets.push(mn);
    }
    sfx.cast('vine');
  }

  update(dt){
    this.t+=dt;
    if(this.intro){ this.introT-=dt; this.bb.faceCamera(this.game.camera);
      this.bb.position.y=Math.sin(this.t*2)*0.3;
      this.pos.set(this.home.x,4.2+Math.sin(this.t*2)*0.3,this.home.z);
      this.aura.position.copy(this.pos);
      if(this.introT<=0) this.intro=false;
      return;
    }
    // minions & shots always update even while dying
    this.minions.forEach(m=>m.update(dt));
    this.minions=this.minions.filter(m=>m.alive||true);
    for(let i=this.shots.length-1;i>=0;i--){
      const s=this.shots[i]; s.m.position.addScaledVector(s.dir,16*dt); s.life-=dt;
      const pp=this.game.player.pos;
      if(s.m.position.distanceTo(new THREE.Vector3(pp.x,1.4,pp.z))<1.2){
        this.game.player.takeDamage(1,s.m.position); s.life=0;
      }
      if(s.life<=0){ burst(this.scene,s.m.position.clone(),0x9a6bff,10,0.3,0.4);
        this.scene.remove(s.m); s.m.geometry.dispose(); s.m.material.dispose(); this.shots.splice(i,1); }
    }
    if(!this.alive){
      // death throes
      this.bb.mesh.material.opacity=Math.max(0,1-this.t%1);
      this.bb.position.y+=dt*0.5; return;
    }

    // hover bob & drift around arena center, face player
    const ang=this.t*0.4;
    const cx=this.home.x+Math.cos(ang)*4, cz=this.home.z+Math.sin(ang*0.7)*3;
    this.pos.x+=(cx-this.pos.x)*Math.min(1,dt*1.5);
    this.pos.z+=(cz-this.pos.z)*Math.min(1,dt*1.5);
    this.pos.y=4.2+Math.sin(this.t*2)*0.4;
    this.bb.position.set(this.pos.x,0,this.pos.z);
    this.bb.bob(this.t,0.3,2);
    this.bb.faceCamera(this.game.camera);
    this.aura.position.copy(this.pos);

    // contact damage
    this.touchCD=Math.max(0,this.touchCD-dt);
    if(this.touchCD<=0){
      const d=Math.hypot(this.pos.x-this.game.player.pos.x,this.pos.z-this.game.player.pos.z);
      if(d<3 && this.game.player.pos.y<3){ this.game.player.takeDamage(1,this.pos); this.touchCD=1; }
    }

    // shockwave update
    if(this.wave){
      this.wave.r+=dt*16; const s=this.wave.r;
      this.wave.ring.scale.set(s,s,s); this.wave.ring.material.opacity=Math.max(0,0.8-s/14);
      const pd=Math.hypot(this.pos.x-this.game.player.pos.x,this.pos.z-this.game.player.pos.z);
      if(!this.wave.hit && Math.abs(pd-s)<1.6 && this.game.player.pos.y<2.2){
        this.wave.hit=true; this.game.player.takeDamage(1,this.pos); }
      if(s>14){ this.scene.remove(this.wave.ring); this.wave=null; }
    }

    // melee from player
    if(this.game.player.meleeHits(this.bb.position)) {
      if(!this._meleeCD||this._meleeCD<=0){ this.hit(1.2,this.bb.position.clone().setY(2)); this._meleeCD=0.4; }
    }
    if(this._meleeCD>0) this._meleeCD-=dt;
    this.minions.forEach(m=>{ if(m.alive && this.game.player.meleeHits(m.pos)){
      if(!m._mcd||m._mcd<=0){ m.hit(1.5); m._mcd=0.4; } } if(m._mcd>0)m._mcd-=dt; });

    // attack scheduler
    this.actT-=dt;
    if(this.actT<=0){
      const rate=[0,1,0.7,0.5][this.phase];
      const r=Math.random();
      if(r<0.45) this._fireVolley(this.phase+2);
      else if(r<0.75) this._shockwave();
      else this._summon();
      this.actT=(1.6+Math.random()*1.4)*rate;
    }
  }
}

import * as THREE from 'three';
import { Billboard, input, justPressed, burst, shake } from './engine.js';
import { sfx } from './audio.js';

const SPEED=11, JUMP=15, GRAV=42, RADIUS=0.7;

export class Player{
  constructor(scene, game){
    this.scene=scene; this.game=game;
    this.bb=new Billboard('hero', 2.2, 2.8);
    this.bb.position.copy(game.world.spawn);
    scene.add(this.bb);
    this.pos=this.bb.position;
    this.vel=new THREE.Vector3();
    this.onGround=false; this.facingLeft=false;
    this.maxHp=5; this.hp=5;
    this.invuln=0; this.attackT=0; this.attackCD=0;
    this.lastSafe=this.pos.clone();
    this.control=true; this.dead=false;
    this.squash=1;
  }

  takeDamage(n=1, fromPos=null){
    if(this.invuln>0||this.dead) return;
    this.hp=Math.max(0,this.hp-n); this.invuln=1.1; sfx.hurt(); shake(0.7);
    this.game.ui.setHearts(this.hp,this.maxHp,true);
    burst(this.scene,this.pos.clone().setY(1.4),0xff4d6d,18,0.4,0.6);
    if(fromPos){ const k=this.pos.clone().sub(fromPos).setY(0).normalize().multiplyScalar(7);
      this.vel.x=k.x; this.vel.z=k.z; this.vel.y=6; }
    if(this.hp<=0) this.die();
  }
  heal(n=1){ this.hp=Math.min(this.maxHp,this.hp+n); this.game.ui.setHearts(this.hp,this.maxHp,true);
    burst(this.scene,this.pos.clone().setY(1.6),0x6bff9a,16,0.35,0.6); }
  die(){ this.dead=true; this.game.onPlayerDeath(); }
  respawn(){ this.dead=false; this.hp=this.maxHp; this.invuln=1.5;
    this.pos.copy(this.lastSafe); this.vel.set(0,0,0); this.game.ui.setHearts(this.hp,this.maxHp); }

  update(dt, world){
    if(this.dead){ return; }
    this.invuln=Math.max(0,this.invuln-dt);
    this.attackCD=Math.max(0,this.attackCD-dt);
    if(this.attackT>0) this.attackT-=dt;

    // ---- input movement (screen-relative) ----
    let ix=0, iz=0;
    if(this.control){
      if(input.keys['a']||input.keys['arrowleft']) ix-=1;
      if(input.keys['d']||input.keys['arrowright']) ix+=1;
      if(input.keys['w']||input.keys['arrowup']) iz-=1;
      if(input.keys['s']||input.keys['arrowdown']) iz+=1;
    }
    const len=Math.hypot(ix,iz)||1; ix/=len; iz/=len;
    const moving=(ix||iz);
    this.vel.x=ix*SPEED; this.vel.z=iz*SPEED;
    if(ix<-0.1) this.facingLeft=true; else if(ix>0.1) this.facingLeft=false;

    // jump
    if(this.control && this.onGround && (justPressed(' ')||justPressed('w')&&false)){}
    if(this.control && this.onGround && justPressed(' ')){
      this.vel.y=JUMP; this.onGround=false; sfx.jump(); this.squash=0.7;
      burst(this.scene,this.pos.clone(),0xffffff,10,0.25,0.4,0.2);
    }
    // attack
    if(this.control && this.attackCD<=0 && justPressed('j')){
      this.attackT=0.22; this.attackCD=0.38; sfx.attack();
      const f=this.facingLeft?-1:1;
      burst(this.scene,this.pos.clone().add(new THREE.Vector3(f*1.2,1.2,0)),0xfff0a0,14,0.4,0.4,0.3);
    }

    // ---- physics integrate ----
    this.vel.y-=GRAV*dt;
    // move X with wall resolve
    this.pos.x+=this.vel.x*dt; this._resolveWalls(world,'x');
    this.pos.z+=this.vel.z*dt; this._resolveWalls(world,'z');
    // boundary clamp (safety net)
    this.pos.x=Math.max(-25.3,Math.min(25.3,this.pos.x));
    // vertical
    this.pos.y+=this.vel.y*dt;
    this._resolveFloor(world);

    // ---- deadly / fall ----
    const overLava=this._inDeadly(world);
    if(this.pos.y< -4 || (overLava && this.pos.y<=0.3)){
      this.takeDamage(1,null); this.pos.copy(this.lastSafe); this.vel.set(0,0,0);
    }

    // ---- visuals ----
    this.squash+= (1-this.squash)*Math.min(1,dt*10);
    this.bb.setFlip(this.facingLeft);
    this.bb.mesh.scale.y=this.squash; this.bb.mesh.scale.x=(this.facingLeft?-1:1)*(2-this.squash);
    if(this.onGround && moving) this.bb.bob(performance.now()/1000,0.1,11);
    else this.bb.mesh.position.y=this.bb.h/2;
    // attack lunge
    if(this.attackT>0){ const f=this.facingLeft?-1:1; this.bb.mesh.position.x=f*0.4*Math.sin(this.attackT/0.22*Math.PI); }
    else this.bb.mesh.position.x=0;
    // flicker when hurt
    this.bb.mesh.material.opacity = this.invuln>0 ? (Math.sin(performance.now()/40)>0?0.35:1) : 1;
    this.bb.mesh.material.transparent=true;
  }

  _footprint(b){ return this.pos.x>b.minx-RADIUS && this.pos.x<b.maxx+RADIUS &&
                        this.pos.z>b.minz-RADIUS && this.pos.z<b.maxz+RADIUS; }

  _resolveFloor(world){
    const prevFeet=this.pos.y - this.vel.y*0; // current
    let groundY=-Infinity;
    for(const f of world.floors){
      if(this._footprint(f) && f.top <= this.pos.y + 0.55) groundY=Math.max(groundY,f.top);
    }
    // also tops of walls (can stand on them)
    for(const w of world.walls){ if(w.open) continue;
      if(this._footprint(w) && w.top<=this.pos.y+0.55) groundY=Math.max(groundY,w.top); }
    if(this.pos.y<=groundY && this.vel.y<=0){
      if(!this.onGround && this.vel.y<-12){ sfx.land(); burst(this.scene,this.pos.clone(),0xcfe0ff,8,0.3,0.3,0.2);}
      this.pos.y=groundY; this.vel.y=0; this.onGround=true;
      // safe spot bookkeeping (not over chasm)
      if(groundY>=0 && !(this.pos.z>-30 && this.pos.z<-12)) this.lastSafe.copy(this.pos).setY(groundY+0.01);
    } else { this.onGround=false; }
  }

  _resolveWalls(world, axis){
    for(const w of world.walls){
      if(w.open) continue;
      // only block if player is below the top of the wall (else standing on it)
      if(this.pos.y > w.top-0.3) continue;
      if(this.pos.x>w.minx-RADIUS && this.pos.x<w.maxx+RADIUS &&
         this.pos.z>w.minz-RADIUS && this.pos.z<w.maxz+RADIUS){
        if(axis==='x'){
          if(this.vel.x>0) this.pos.x=w.minx-RADIUS; else if(this.vel.x<0) this.pos.x=w.maxx+RADIUS;
          this.vel.x=0;
        } else {
          if(this.vel.z>0) this.pos.z=w.minz-RADIUS; else if(this.vel.z<0) this.pos.z=w.maxz+RADIUS;
          this.vel.z=0;
        }
      }
    }
  }
  _inDeadly(world){
    for(const d of world.deadly){
      if(this.pos.x>d.minx&&this.pos.x<d.maxx&&this.pos.z>d.minz&&this.pos.z<d.maxz){
        // standing on a platform inside the chasm? then not deadly
        let onPlat=false;
        for(const f of world.floors){ if(f.top>-1 && this._footprint(f) && Math.abs(this.pos.y-f.top)<0.4){onPlat=true;break;} }
        if(!onPlat) return true;
      }
    }
    return false;
  }
  // is an enemy within melee reach in front?
  meleeHits(targetPos){
    if(this.attackT<=0) return false;
    const d=targetPos.clone().sub(this.pos); if(Math.abs(d.y)>3) return false;
    const dist=Math.hypot(d.x,d.z); if(dist>2.6) return false;
    const f=this.facingLeft?-1:1;
    return Math.sign(d.x)===f || dist<1.4;
  }
}

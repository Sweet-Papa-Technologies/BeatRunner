import * as THREE from 'three';
import { loadAssets, url } from './assets.js';
import { initEngine, engine, render, updateCamera, updateParticles, initInput, justPressed, clearPressed, burst, shake } from './engine.js';
import { initAudio, resumeAudio, playMusic, sfx } from './audio.js';
import { buildWorld } from './world.js';
import { Player } from './player.js';
import { Companions } from './companion.js';
import { Boss } from './boss.js';
import { UI } from './ui.js';
import { Cutscene } from './cutscene.js';

const $=id=>document.getElementById(id);

class Game{
  constructor(){
    this.ui=new UI(); this.cutscene=new Cutscene();
    this.state='boot'; this.busy=false;
    this.combatTargets=[]; this.gems=0;
    this.boss=null; this.bossStarted=false;
    this.flags={sage:false, fire:false, gateOpen:false, victory:false};
  }

  async boot(){
    initAudio(); initInput();
    await initEngine($('scene'));
    this.camera=engine.camera; this.scene=engine.scene;
    await loadAssets((p,name)=>{ $('bar-fill').style.width=Math.round(p*100)+'%';
      $('load-status').textContent='Summoning… '+name; });
    $('bar-fill').style.width='100%';
    // build the world now (needs textures)
    this.world=buildWorld(this.scene);
    this.player=new Player(this.scene,this);
    this.companions=new Companions(this.scene,this);
    engine.camTarget.copy(this.player.pos);
    engine.camera.position.copy(this.player.pos).add(engine.camOffset);
    // start render loop immediately (renders world behind overlays)
    this._last=performance.now();
    requestAnimationFrame(this._loop.bind(this));
    this._toTitle();
  }

  _toTitle(){
    this.state='title';
    $('loader').classList.add('hidden');
    $('title').classList.remove('hidden');
    document.querySelector('.title-art').style.backgroundImage=`url(${url('title_bg')})`;
    $('fade').classList.add('clear');
    $('btn-start').onclick=()=>{ resumeAudio(); this._beginIntro(); };
    $('btn-skip').onclick =()=>{ resumeAudio(); this._startGame(true); };
  }

  async _beginIntro(){
    $('title').classList.add('hidden');
    this.state='cutscene';
    playMusic('calm',{fade:2});
    await this.cutscene.play([
      {image:'scene1', _first:true, narr:'n1', hold:7,
       text:'Long ago, the Vale of Lumina thrived in harmony with the elemental spirits…'},
      {image:'scene3', narr:'n1b', hold:6,
       text:'But the Shadow King shattered the Crystal of Balance, and darkness crept across the land.'},
      {image:'scene2', narr:'n2', hold:7,
       text:'You are Kael, the last Spirit Warden. With the elemental spirits at your side, restore the light.'},
    ]);
    this._startGame(false);
  }

  async _startGame(skipIntro){
    $('title').classList.add('hidden');
    this.state='play';
    this.ui.showHUD();
    this.ui.setHearts(this.player.hp,this.player.maxHp);
    this.ui.setGems(0);
    this.ui.buildRoster([], -1);
    this.ui.setObjective('Find the Spirit Sage in the meadow');
    playMusic('overworld',{fade:2.5});
    await this.ui.fadeIn(1200);
    if(skipIntro){ this.ui.banner('MONSTER QUEST',1.4); }
  }

  // ---------------- main loop ----------------
  _loop(now){
    const dt=Math.min(0.05,(now-this._last)/1000); this._last=now;
    this._animateWorld(dt, now/1000);
    if(this.state==='play'){
      if(!this.busy){ this.player.update(dt,this.world); this.companions.update(dt); }
      else { clearPressed(); }
      if(this.boss) this.boss.update(dt);
      this._interactions(dt);
      // keep companions floating even while busy
      if(this.busy && this.companions.bb){ this.companions.update(0); }
      this.player.bb.faceCamera(this.camera);
      updateCamera(this.player.pos, dt);
    } else {
      // idle camera drift on title
      updateCamera(this.player?this.player.pos:new THREE.Vector3(), dt);
    }
    updateParticles(dt);
    render();
    requestAnimationFrame(this._loop.bind(this));
  }

  _animateWorld(dt,t){
    const W=this.world; if(!W) return;
    for(const d of W.decor){ d.m.rotation.y+=dt*d.spin; d.m.position.y=d.base+Math.sin(t*2+d.base)*0.15; }
    if(W.lava) W.lava.material.emissiveIntensity=0.8+Math.sin(t*3)*0.25;
    if(W.motePoints){ W.motePoints.rotation.y+=dt*0.02;
      W.motePoints.material.opacity=0.6+Math.sin(t*2)*0.2; }
    // gems & wild markers bob / face camera
    for(const o of (W.interact||[])){
      if(o.done) continue;
      if(o.type==='gem'){ o.bb.position.y=(o.baseY||0)+1+Math.sin(t*3+o.pos.x)*0.2; o.bb.mesh.rotation.y+=dt*2; o.bb.faceCamera(this.camera); }
      if(o.type==='wild'){ o.bb.bob(t,0.18,3); o.bb.faceCamera(this.camera);
        if(o.ring) o.ring.material.opacity=0.4+Math.sin(t*4)*0.3; }
      if(o.type==='npc'){ o.bb.bob(t,0.08,2); o.bb.faceCamera(this.camera); }
      if(o.type==='brazier' && o.lit){ o.flame.bob(t,0.2,8); o.flame.faceCamera(this.camera);
        o.light.intensity=2.2+Math.sin(t*12)*0.6; }
    }
  }

  // ---------------- interactions ----------------
  _interactions(dt){
    const W=this.world, p=this.player.pos;
    let hintShown=false;
    for(const o of W.interact){
      if(o.done) continue;
      const d=Math.hypot(p.x-o.pos.x, p.z-o.pos.z);
      if(o.type==='gem' && d<o.radius && Math.abs(p.y-(o.baseY||0))<2.5){
        o.done=true; this.gems++; this.ui.setGems(this.gems); sfx.gem();
        burst(this.scene,o.bb.position.clone(),0x4fe3d0,20,0.5,0.6);
        this.scene.remove(o.bb); if(o.light)this.scene.remove(o.light);
      }
      else if(o.type==='npc' && d<o.radius && !this.flags.sage && !this.busy){
        this._sageTalk();
      }
      else if(o.type==='wild' && d<o.radius){
        if(!this.companions.has(o.elem)){
          hintShown=true; this.ui.hint(`Press  F  to capture ${o.sprite.toUpperCase()}`);
          if(justPressed('f')){ this._capture(o); }
        }
      }
    }
    // light braziers with fire shots
    for(const o of W.interact){
      if(o.type==='brazier' && !o.lit){
        for(const s of this.companions.shots){
          if(s.elem==='fire' && Math.hypot(s.m.position.x-o.pos.x,s.m.position.z-o.pos.z)<2.4 && s.m.position.y<3){
            this._lightBrazier(o); break;
          }
        }
      }
    }
    if(!hintShown) this.ui.hideHint();

    // boss trigger
    if(this.flags.gateOpen && !this.bossStarted && p.z< -53){
      this._startBoss();
    }
  }

  async _sageTalk(){
    this.flags.sage=true; this.busy=true; this.player.control=false;
    await this.ui.dialogue([
      "Kael… at last you have awakened, young Warden.",
      "Darkness has swallowed the Shadow Temple to the north.",
      "You cannot face it alone. Seek the elemental spirits — befriend them, and they will lend you their power.",
      "An Ember spirit plays nearby. Approach it and press F to capture it!",
    ], {name:'Spirit Sage', portrait:'sage'});
    this.ui.setObjective('Capture the Fire spirit, Ember (press F)');
    this.busy=false; this.player.control=true;
  }

  async _capture(o){
    o.done=true; this.busy=true; this.player.control=false;
    this.ui.hideHint();
    sfx.capture(); shake(0.5);
    burst(this.scene,o.bb.position.clone().setY(1.5),0xffffff,40,0.7,0.8);
    if(o.ring) this.scene.remove(o.ring);
    this.scene.remove(o.bb);
    this.companions.capture(o.elem);
    const names={fire:'Ember',water:'Aqua',vine:'Sprout'};
    this.ui.banner(`${names[o.elem]} joined your team!`,1.6);
    await this.ui.dialogue([
      `${names[o.elem]} the ${o.elem} spirit is now your companion!`,
      o.elem==='fire'
        ? "Press E to unleash Ember's flame. Aim at foes — or at the temple braziers to light them!"
        : "Press E to attack with its elemental power. Switch companions with 1, 2, 3.",
    ], {name:names[o.elem], portrait:o.sprite});
    this.busy=false; this.player.control=true;
    if(o.elem==='fire' && !this.flags.fire){
      this.flags.fire=true;
      this.ui.setObjective('Cross the chasm to the Shadow Temple');
    }
  }

  _lightBrazier(o){
    o.lit=true; o.flame.visible=true; o.light.intensity=2.4; sfx.open();
    burst(this.scene,o.pos.clone(),0xff8a3a,30,0.6,0.7);
    const lit=this.world.interact.filter(x=>x.type==='brazier'&&x.lit).length;
    const total=this.world.interact.filter(x=>x.type==='brazier').length;
    this.ui.banner(`Brazier lit  (${lit}/${total})`,1.1);
    if(lit===total){ this._openGate(); }
    else this.ui.setObjective(`Light the temple braziers with Ember  (${lit}/${total})`);
  }

  async _openGate(){
    this.flags.gateOpen=true;
    const g=this.world.gate; g.open=true; g.wall.open=true;
    sfx.bossRoar(); shake(1.0);
    this.ui.banner('The Shadow Gate opens!',1.8);
    this.ui.setObjective('Enter the Shadow Temple');
    burst(this.scene,new THREE.Vector3(0,4,-52),0x9a6bff,50,0.9,1.0);
    // animate seal away
    const seal=g.seal; const t0=performance.now();
    const fade=()=>{ const k=Math.min(1,(performance.now()-t0)/1200);
      seal.material.opacity=0.55*(1-k); g.bar.position.y=7+k*6;
      if(k<1) requestAnimationFrame(fade); else { seal.visible=false; } };
    fade();
  }

  async _startBoss(){
    this.bossStarted=true;
    playMusic('boss',{fade:1.5});
    this.ui.banner('⚔  THE SHADOW KING  ⚔',2.2);
    this.ui.setObjective('Defeat the Shadow King!');
    this.boss=new Boss(this.scene,this);
    this.ui.showBoss();
    shake(1.4);
  }

  // ---------------- outcomes ----------------
  async onPlayerDeath(){
    if(this.busy) return; this.busy=true; this.player.control=false;
    await this.ui.fadeOut(700);
    this.ui.banner('You fall… but the light endures',1.4);
    this.player.respawn();
    if(this.bossStarted && this.boss && this.boss.alive){
      this.player.pos.set(0,0,-56); this.player.lastSafe.set(0,0,-56);
    }
    engine.camera.position.copy(this.player.pos).add(engine.camOffset);
    engine.camTarget.copy(this.player.pos);
    await this.ui.fadeIn(800);
    this.busy=false; this.player.control=true;
  }

  async onBossDefeated(){
    this.flags.victory=true; this.busy=true; this.player.control=false;
    this.ui.hideBoss();
    shake(2);
    burst(this.scene,this.boss.pos.clone(),0xffffff,80,1.2,1.4);
    for(let i=0;i<6;i++) setTimeout(()=>{ shake(1.2);
      burst(this.scene,this.boss.pos.clone().add(new THREE.Vector3((Math.random()-.5)*8,Math.random()*6,(Math.random()-.5)*8)),0x9a6bff,30,0.8,0.9); }, i*220);
    sfx.victory();
    setTimeout(async ()=>{
      this.scene.remove(this.boss.bb); if(this.boss.aura)this.scene.remove(this.boss.aura);
      this.combatTargets=[];
      this.ui.banner('✦ VICTORY ✦',2.4);
      await new Promise(r=>setTimeout(r,2600));
      this.state='cutscene';
      playMusic('calm',{fade:2});
      await this.cutscene.play([
        {image:'scene1', _first:true, hold:6,
         text:'With the Shadow King vanquished, the Crystal of Balance is whole once more.'},
        {image:'scene2', hold:6,
         text:'Light floods the Vale of Lumina. The spirits dance, and Kael is hailed as the true Spirit Warden.'},
        {image:'title_bg', hold:6,
         text:'Thank you for playing  ✦  MONSTER QUEST: Spirit Warden  ✦'},
      ]);
      this._victoryScreen();
    }, 1600);
  }

  _victoryScreen(){
    this.state='title';
    this.ui.hideHUD();
    $('title').classList.remove('hidden');
    document.querySelector('.title-content').innerHTML=
      '<h1 class="title-main">THE END</h1>'+
      '<h2 class="title-sub">✦ YOU SAVED LUMINA ✦</h2>'+
      `<p class="title-hint">Spirits befriended: ${this.companions.roster.length} / 3 · Gems: ${this.gems}</p>`+
      '<button id="btn-again" class="menu-btn">↺ PLAY AGAIN</button>';
    $('btn-again').onclick=()=>location.reload();
  }
}

const game=new Game();
game.boot().catch(e=>{
  console.error(e);
  $('load-status').textContent='Error: '+e.message;
});
window._game=game;

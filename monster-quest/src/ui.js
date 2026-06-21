import { url } from './assets.js';
import { SPECIES } from './companion.js';
import { sfx } from './audio.js';

const $=id=>document.getElementById(id);

export class UI{
  constructor(){
    this.hud=$('hud'); this.dlgEl=$('dialogue');
    this._dlgResolve=null; this._dlgQueue=[];
    // global advance for dialogue
    const adv=()=>{ if(this._dlgResolve) this._advanceDialogue(); };
    addEventListener('keydown',e=>{ if((e.key===' '||e.key==='Enter') && this._dlgResolve){e.preventDefault(); adv();} });
    this.dlgEl.addEventListener('click',adv);
  }
  showHUD(){ this.hud.classList.remove('hidden'); }
  hideHUD(){ this.hud.classList.add('hidden'); }

  setHearts(hp,max,pop=false){
    const el=$('hearts'); el.innerHTML='';
    for(let i=0;i<max;i++){
      const img=document.createElement('img');
      img.src=url('heart'); img.className='heart'+(i<hp?'':' empty');
      if(pop&&i===hp-1) img.classList.add('pop');
      el.appendChild(img);
    }
  }
  setGems(n){ $('gems').textContent=n; }
  setObjective(t){ $('obj-text').textContent=t; }

  buildRoster(roster, active){
    const el=$('roster'); el.innerHTML='';
    const slots=Math.max(3,roster.length);
    for(let i=0;i<slots;i++){
      const slot=document.createElement('div');
      slot.className='slot'+(i===active?' active':'')+(roster[i]?'':' empty');
      const key=document.createElement('span'); key.className='key'; key.textContent=i+1; slot.appendChild(key);
      const img=document.createElement('img');
      const elem=roster[i];
      img.src=url(elem?SPECIES[elem].sprite:'gem'); slot.appendChild(img);
      if(elem){ const tag=document.createElement('span'); tag.className='elem'; tag.style.color='#fff';
        tag.textContent=SPECIES[elem].name; slot.appendChild(tag); }
      const cd=document.createElement('div'); cd.className='cd'; slot.appendChild(cd);
      el.appendChild(slot);
    }
    this._slots=el.children;
  }
  flashSlot(i,cd){
    if(!this._slots||!this._slots[i]) return;
    const c=this._slots[i].querySelector('.cd');
    c.style.transition='none'; c.style.transform='scaleY(1)';
    requestAnimationFrame(()=>{ c.style.transition=`transform ${cd}s linear`; c.style.transform='scaleY(0)'; });
  }

  // ----- dialogue -----
  dialogue(lines, who={}){
    // lines: array of strings. who:{name,portrait(sprite name)}
    return new Promise(res=>{
      this._dlgQueue=lines.slice(); this._dlgWho=who; this._dlgResolve=res;
      this.dlgEl.classList.remove('hidden');
      $('dlg-name').textContent=who.name||'';
      $('dlg-portrait').style.backgroundImage= who.portrait? `url(${url(who.portrait)})`:'none';
      this._showLine();
    });
  }
  _showLine(){
    const txt=this._dlgQueue[0]||'';
    const el=$('dlg-text'); el.textContent='';
    // typewriter
    clearInterval(this._tw); let i=0; this._typing=true;
    this._tw=setInterval(()=>{ el.textContent=txt.slice(0,++i); if(i>=txt.length){clearInterval(this._tw);this._typing=false;} },18);
  }
  _advanceDialogue(){
    if(this._typing){ // finish line instantly
      clearInterval(this._tw); $('dlg-text').textContent=this._dlgQueue[0]; this._typing=false; sfx.select(); return;
    }
    sfx.select(); this._dlgQueue.shift();
    if(this._dlgQueue.length===0){
      this.dlgEl.classList.add('hidden');
      const r=this._dlgResolve; this._dlgResolve=null; r&&r();
    } else this._showLine();
  }

  // ----- hint toast -----
  hint(t){ const el=$('hint-toast'); el.textContent=t; el.classList.remove('hidden'); }
  hideHint(){ $('hint-toast').classList.add('hidden'); }

  // ----- banner -----
  banner(text,dur=1.6){
    const b=$('banner'), t=$('banner-text');
    t.textContent=text; b.classList.remove('hidden');
    t.style.animation='none'; void t.offsetWidth; t.style.animation='bannerin .6s ease both';
    clearTimeout(this._bt); this._bt=setTimeout(()=>b.classList.add('hidden'),dur*1000);
  }

  // ----- boss bar -----
  showBoss(){ $('boss-bar-wrap').classList.remove('hidden'); this.setBoss(1); }
  hideBoss(){ $('boss-bar-wrap').classList.add('hidden'); }
  setBoss(frac){ $('boss-fill').style.width=Math.max(0,frac*100)+'%'; }

  // ----- fades -----
  fadeIn(ms=1000){ return new Promise(r=>{ $('fade').classList.add('clear'); setTimeout(r,ms); }); }
  fadeOut(ms=1000){ return new Promise(r=>{ $('fade').classList.remove('clear'); setTimeout(r,ms); }); }
}

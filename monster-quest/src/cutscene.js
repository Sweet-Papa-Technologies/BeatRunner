import { url } from './assets.js';
import { playNarration, stopNarration } from './audio.js';

const $=id=>document.getElementById(id);

export class Cutscene{
  constructor(){
    this.el=$('cutscene'); this.img=$('cs-image'); this.txt=$('cs-text');
    this.box=$('cs-textbox');
    this._advance=null; this._skip=null;
    $('cs-skip').addEventListener('click',()=>{ if(this._skip)this._skip(); });
    const adv=(e)=>{ if(this._advance){ if(e&&e.code==='Space')e.preventDefault(); this._advance(); } };
    this.el.addEventListener('click',adv);
    this._keyHandler=(e)=>{ if((e.code==='Space'||e.code==='Enter')&&this._advance){e.preventDefault();this._advance();} };
  }

  // beats: [{image, text, narr, hold}]
  play(beats){
    return new Promise(async (resolve)=>{
      this.el.classList.remove('hidden');
      addEventListener('keydown',this._keyHandler);
      let skipped=false;
      this._skip=()=>{ skipped=true; if(this._step)this._step(); };
      for(let i=0;i<beats.length && !skipped;i++){
        await this._beat(beats[i]);
      }
      stopNarration();
      removeEventListener('keydown',this._keyHandler);
      this._advance=null; this._skip=null;
      this.el.classList.add('hidden');
      resolve();
    });
  }

  _beat(b){
    return new Promise((done)=>{
      this._step=done;
      // image transition
      this.img.classList.remove('show');
      this.box.classList.remove('show');
      setTimeout(()=>{
        this.img.style.backgroundImage=`url(${url(b.image)})`;
        // restart ken-burns
        this.img.style.transition='none'; this.img.style.transform='scale(1.04)';
        void this.img.offsetWidth;
        this.img.style.transition='opacity 1.1s ease, transform 9s linear';
        this.img.classList.add('show');
        this._typeText(b.text||'');
        this.box.classList.add('show');
      },b._first?0:550);

      // narration
      let narrDone=false;
      const startNarr=()=>{ if(b.narr){ playNarration(b.narr).then(()=>{narrDone=true;}); } else narrDone=true; };
      setTimeout(startNarr, 700);

      let finished=false;
      const finish=()=>{ if(finished)return; finished=true; this._advance=null; clearInterval(this._tw); done(); };
      this._advance=finish;
      // auto-advance after hold (and narration) if user doesn't click
      const hold=(b.hold||5)*1000;
      this._auto=setTimeout(function check(){
        // wait until narration done, then small delay
      }, hold);
      // poll for narration completion to auto-advance
      const poll=setInterval(()=>{
        if(finished){ clearInterval(poll); return; }
        if(narrDone){ clearInterval(poll); this._autoFin=setTimeout(finish, b.narr?900:hold); }
      },200);
    });
  }
  _typeText(t){
    clearInterval(this._tw); let i=0; this.txt.textContent='';
    this._tw=setInterval(()=>{ this.txt.textContent=t.slice(0,++i); if(i>=t.length)clearInterval(this._tw); },28);
  }
}

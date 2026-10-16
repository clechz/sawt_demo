// One owner for exact readback audio, including stale async callbacks.
export class ReadbackPlayer {
  constructor({api, createAudio=()=>new Audio(), releaseAudio=()=>{}, attachAudio=()=>{}, mute, phase, failure, retry, setTimer=(...args)=>globalThis.setTimeout(...args), clearTimer=id=>globalThis.clearTimeout(id)}) {
    Object.assign(this,{api,createAudio,releaseAudio,attachAudio,mute,phase,failure,retry,setTimer,clearTimer});
    this.generation=0;
    this.audio=null;
    this.active=false;
  }
  // Unlock this exact media element during the caller's start-button gesture.
  // Creating a new element after async checkout can lose autoplay permission.
  unlock() {
    if(!this.unlockedAudio)this.unlockedAudio=this.createAudio();
    const audio=this.unlockedAudio;
    audio.src='data:audio/wav;base64,UklGRiYAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQIAAAAAAA==';
    const attempt=audio.play();
    return Promise.resolve(attempt).catch(()=>{});
  }
  cancel() {
    this.clearTimer(this.stallTimer);
    this.generation++;
    this.active=false;
    if(this.audio) {
      this.audio.onplaying=this.audio.onended=this.audio.onerror=this.audio.onwaiting=this.audio.onstalled=null;
      try { this.releaseAudio(this.audio); } catch { /* Optional visuals cannot block cancellation. */ }
      this.audio.pause();
      this.audio.removeAttribute('src');
      this.audio.load();
      this.audio=null;
    }
    this.mute(false);
    this.retry(false);
  }
  async play(callId) {
    this.cancel();
    this.active=true;
    const generation=this.generation;
    const current=()=>generation===this.generation;
    let receiptId;
    this.mute(true);
    this.phase('preparing');
    const fail=e=>{
      if(!current())return;
      if(receiptId)void this.api(`/api/calls/${callId}/playback`,{method:'POST',body:JSON.stringify({receipt_id:receiptId,phase:'failed',error_code:e.name==='NotAllowedError'?'autoplay_blocked':e.code==='readback_incomplete'?'incomplete':e.status===409?'superseded':'media_or_network'})}).catch(()=>{});
      this.cancel();
      const incomplete=e.code==='readback_incomplete';
      const changed=e.status===409&&!incomplete;
      this.failure(e.name==='NotAllowedError'?'اضغط تشغيل الصوت عشان تسمع ملخص طلبك. الطلب ما تأكد بعد.':incomplete?'الملخص ما اكتمل. اضغط إعادة الملخص ونسمعه من البداية.':changed?'طلبك تغيّر. بنراجع التعديل قبل الملخص الجديد.':e.message||'تعذر تشغيل الملخص. اضغط إعادة التشغيل.');
      this.retry(!changed);
      this.phase('paused');
    };
    const watchStall=()=>{
      if(!current())return;
      this.clearTimer(this.stallTimer);
      this.stallTimer=this.setTimer(()=>fail(new Error('الصوت تأخر. اضغط إعادة الملخص، طلبك محفوظ.')),10000);
    };
    watchStall();
    try {
      const response=await this.api(`/api/calls/${callId}/readback`,{method:'POST'});
      const receipt=await response.json();
      receiptId=receipt.receipt_id;
      if(!current())return;
      const audio=this.unlockedAudio||this.createAudio();
      this.attachAudio(audio);
      this.audio=audio;
      let started;
      audio.preload='none';
      audio.src=receipt.url;
      audio.onplaying=()=>{
        if(!current())return;
        this.clearTimer(this.stallTimer);
        if(started)return;
        this.phase('readback');
        started=this.api(`/api/calls/${callId}/playback`,{method:'POST',body:JSON.stringify({receipt_id:receipt.receipt_id,phase:'started'})});
        started.catch(fail);
      };
      audio.onended=async()=>{
        if(!current()||!started)return;
        this.clearTimer(this.stallTimer);
        try {
          await started;
          if(!current())return;
          await this.api(`/api/calls/${callId}/playback`,{method:'POST',body:JSON.stringify({receipt_id:receipt.receipt_id,phase:'completed',position:audio.currentTime})});
          if(!current())return;
          this.cancel();
          this.phase('confirm');
        }catch(e){fail(e);}
      };
      audio.onerror=()=>fail(new Error('تعذر تشغيل الملخص. اضغط إعادة التشغيل، أو قل لنا وش تبي تعدّل.'));
      audio.onwaiting=audio.onstalled=watchStall;
      await audio.play();
    }catch(e){fail(e);}
  }
}

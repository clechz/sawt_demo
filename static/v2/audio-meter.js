// Observe a COPY of native readback audio. Never reroute output or acquire a mic.
// Browsers without captureStream keep native playback and the ambient orb.
export class PlaybackMeter {
  constructor(createContext=()=>new AudioContext()) {
    this.createContext=createContext;
    this.context=null;
    this.release=null;
    this.analyser=null;
    this.samples=null;
  }
  prepare() {
    try {
      this.context??=this.createContext();
      void this.context.resume().catch(()=>{});
    } catch { /* Visualization must never prevent a call. */ }
  }
  attach(audio) {
    this.detach();
    if(!this.context||typeof audio.captureStream!=='function')return;
    let stream,source,analyser;
    const connect=()=>{
      if(source||!stream?.getAudioTracks().length)return;
      try {
        source=this.context.createMediaStreamSource(stream);
        analyser=this.context.createAnalyser();
        analyser.fftSize=256;
        source.connect(analyser); // No connection to speakers: avoids echo.
        this.analyser=analyser;
        this.samples=new Float32Array(analyser.fftSize);
      } catch { /* Native audio remains untouched. */ }
    };
    const playing=()=>{
      try { stream=audio.captureStream();stream.addEventListener('addtrack',connect);connect(); }
      catch { /* Unsupported media capture is a visual-only fallback. */ }
    };
    audio.addEventListener('playing',playing,{once:true});
    this.release=()=>{
      audio.removeEventListener('playing',playing);
      stream?.removeEventListener('addtrack',connect);
      source?.disconnect();analyser?.disconnect();
      // Only captured copies belong to this meter, never LiveKit tracks.
      stream?.getTracks().forEach(track=>track.stop());
    };
  }
  level() {
    if(!this.analyser||!this.samples||this.context?.state!=='running')return 0;
    try {
      this.analyser.getFloatTimeDomainData(this.samples);
      return Math.min(1,Math.sqrt(this.samples.reduce((sum,x)=>sum+x*x,0)/this.samples.length)*4);
    } catch { return 0; }
  }
  detach() {
    this.release?.();this.release=null;this.analyser=null;this.samples=null;
  }
  close() {
    this.detach();
    if(this.context)void this.context.close().catch(()=>{});
    this.context=null;
  }
}

// Read the existing published microphone; never request a second microphone or
// route it to speakers. Disconnecting the visualization must not stop the call.
export class MicrophoneMeter extends PlaybackMeter {
  attachTrack(track) {
    this.detach();
    if(!this.context||!track)return;
    try {
      const source=this.context.createMediaStreamSource(new MediaStream([track]));
      const analyser=this.context.createAnalyser();
      analyser.fftSize=512;
      source.connect(analyser);
      this.analyser=analyser;
      this.samples=new Float32Array(analyser.fftSize);
      this.release=()=>{source.disconnect();analyser.disconnect();};
    } catch { /* Fall back to participant level without affecting voice. */ }
  }
}

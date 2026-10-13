// End the media first. Network cleanup and visual feedback must never keep a mic live.
const attempt=fn=>{try{return fn();}catch{return undefined;}};
export function stopMediaNow(room,audioElements,player,fixture){
 for(const p of room?.localParticipant?.audioTrackPublications?.values()||[]){
  const track=p.track?.mediaStreamTrack;if(track){attempt(()=>{track.enabled=false;});attempt(()=>track.stop());}
 }
 attempt(()=>player.cancel());attempt(()=>fixture?.pause());
 for(const audio of audioElements){attempt(()=>{audio.muted=true;});attempt(()=>audio.pause());attempt(()=>{audio.srcObject=null;});attempt(()=>audio.remove());}
 audioElements.clear();
 const result=attempt(()=>room?.disconnect());
 return Promise.resolve(result).catch(()=>{});
}
export async function animateHangup(root=document){
 if(globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches)return;
 const orb=root.querySelector?.('.orb-control');if(!orb?.animate)return;
 let animation,timer;
 try{
  animation=orb.animate([{transform:'scale(1)',opacity:1},{transform:'scale(.72)',opacity:0}],
   {duration:420,easing:'cubic-bezier(.2,.7,.2,1)',fill:'forwards'});
  await Promise.race([animation.finished,new Promise(resolve=>{timer=globalThis.setTimeout(resolve,650);})]);
 }catch{/* Interrupted/unsupported animations never block hangup. */}
 finally{globalThis.clearTimeout(timer);attempt(()=>animation?.cancel());}
}
export async function closeSavedCall(call,accessCode,fetcher=globalThis.fetch){
 if(!call)return null;
 const abort=new AbortController();const timer=globalThis.setTimeout(()=>abort.abort(),4000);
 const headers={Authorization:`Bearer ${call.token}`,'X-Access-Code':accessCode,'Content-Type':'application/json'};
 try{
  const response=await fetcher(`/api/calls/${call.id}/end`,{method:'POST',headers,signal:abort.signal,keepalive:true});
  if(!response.ok)throw new Error('Call closure was not acknowledged');
  const state=await fetcher(`/api/calls/${call.id}?after=999999999`,{headers,signal:abort.signal,cache:'no-store'});
  if(!state.ok)throw new Error('Final order state was not available');
  return await state.json();
 }finally{globalThis.clearTimeout(timer);}
}

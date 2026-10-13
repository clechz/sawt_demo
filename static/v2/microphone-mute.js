/**
 * Mic-only mute: keep the WebRTC publication alive and send silent samples.
 * Calling LiveKit's setMicrophoneEnabled(false) may remove/stop the mic track,
 * disrupting a full-duplex voice session. This must NEVER touch the AI audio.
 */
export function setMicrophoneSilenced(room, silenced){
 const publications=room?.localParticipant?.audioTrackPublications;
 if(!publications || typeof publications.values!=='function')
  throw new Error('الميكروفون غير متصل. حاول مرة ثانية.');
 let changed=0;
 for(const publication of publications.values()){
  const track=publication?.track?.mediaStreamTrack;
  if(!track || track.readyState==='ended')continue;
  // The underlying MediaStreamTrack remains published and sends silence.
  // Do not call publication.mute(), unpublishTrack(), stop(), or room.disconnect().
  track.enabled=!silenced;
  changed++;
 }
 if(!changed)throw new Error('الميكروفون غير متصل. حاول مرة ثانية.');
 return changed;
}

// This is a control packet, never an instruction in the conversation context.
export async function syncMicrophoneMute(participant,callId,muted,sequence){
 await participant.publishData(new TextEncoder().encode(JSON.stringify({call_id:callId,muted,sequence})),{reliable:true,topic:'sawt-mic'});
}

// Muting capture must not mute playback, cancel work, or stop the audio clock.
export function setMicrophoneCapture(participant,muted){
 const tracks=[...participant.audioTrackPublications.values()]
  .filter(p=>p.source==='microphone'&&p.track?.mediaStreamTrack)
  .map(p=>p.track.mediaStreamTrack);
 if(!tracks.length)throw new Error('الميكروفون غير جاهز. حاول مرة ثانية.');
 for(const track of tracks)track.enabled=!muted;
}
export async function syncMicrophoneMute(participant,callId,muted,sequence){
 await participant.publishData(new TextEncoder().encode(JSON.stringify({
  call_id:callId,muted,sequence
 })),{reliable:true,topic:'sawt-mic'});
}

"use client";
import {useRef,useState} from 'react';
import {Mic,MicOff} from 'lucide-react';
import {VoicePoweredOrb} from '@/components/ui/voice-powered-orb';
import {Button} from '@/components/ui/button';

/** Component sandbox. Pass the same meter ref as the call; never open a second mic. */
export default function VoicePoweredOrbPage(){
  const [enabled,setEnabled]=useState(false);
  const [detected,setDetected]=useState(false);
  const level=useRef(0);
  return <div className="flex min-h-screen flex-col items-center justify-center gap-8 bg-background p-8">
    <div className="relative h-96 w-96 rounded-3xl bg-[#17102f]">
      <VoicePoweredOrb audioLevelRef={level} enableVoiceControl={enabled} onVoiceDetected={setDetected}/>
    </div>
    <Button onClick={()=>setEnabled(!enabled)} variant={enabled?'destructive':'default'} size="lg">
      {enabled?<MicOff className="mr-3 h-5 w-5"/>:<Mic className="mr-3 h-5 w-5"/>}
      {enabled?'Pause voice visualization':'Enable voice visualization'}
    </Button>
    <p className="max-w-md text-center text-muted-foreground">Connect the call audio meter to level.current. {detected?'Voice detected.':'Waiting for call audio.'}</p>
  </div>;
}

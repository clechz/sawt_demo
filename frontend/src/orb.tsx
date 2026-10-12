import {createRoot} from 'react-dom/client';
import {VoicePoweredOrb} from '@/components/ui/voice-powered-orb';
import {Phone, Mic, MicOff, ChevronLeft, X} from 'lucide-react';
import '@/styles/globals.css';

const level={current:0};
window.addEventListener('sawt:audio-level',event=>{level.current=(event as CustomEvent<number>).detail;});
const node=document.getElementById('voice-orb');
if(node)createRoot(node).render(<VoicePoweredOrb hue={0} voiceSensitivity={1.65} audioLevelRef={level} />);

const icons={hangup:Phone,mic:Mic,muted:MicOff,chevron:ChevronLeft,close:X};
for(const element of document.querySelectorAll<HTMLElement>('[data-icon]')){
  const Icon=icons[element.dataset.icon as keyof typeof icons];
  if(Icon)createRoot(element).render(<Icon size={20} strokeWidth={1.65} aria-hidden="true" />);
}

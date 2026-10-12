"use client";

import {useEffect, useRef, type FC, type RefObject} from 'react';
import {Renderer, Program, Mesh, Triangle, Vec3} from 'ogl';
import {cn} from '@/lib/utils';
import {vert, frag} from './orb-shaders';

interface VoicePoweredOrbProps {
  className?: string;
  hue?: number;
  enableVoiceControl?: boolean;
  voiceSensitivity?: number;
  maxRotationSpeed?: number;
  maxHoverIntensity?: number;
  onVoiceDetected?: (detected: boolean) => void;
  /** Shared call meter. This component never acquires or changes the microphone. */
  audioLevelRef?: RefObject<number>;
}

export const VoicePoweredOrb: FC<VoicePoweredOrbProps> = ({
  className, hue=0, enableVoiceControl=true, voiceSensitivity=1.5,
  maxRotationSpeed=.35, maxHoverIntensity=.32, onVoiceDetected, audioLevelRef,
}) => {
  const containerRef=useRef<HTMLDivElement>(null);
  const settings=useRef({hue,enableVoiceControl,voiceSensitivity,maxRotationSpeed,maxHoverIntensity,onVoiceDetected,audioLevelRef});
  settings.current={hue,enableVoiceControl,voiceSensitivity,maxRotationSpeed,maxHoverIntensity,onVoiceDetected,audioLevelRef};

  useEffect(()=>{
    const container=containerRef.current;
    if(!container)return;
    let renderer: Renderer | undefined;
    let program: Program | undefined;
    let geometry: Triangle | undefined;
    let mesh: Mesh | undefined;
    let observer: ResizeObserver | undefined;
    let frame=0, lastTime=0, visualTime=3, rotation=0, smoothLevel=0, detected=false, lost=false;
    const reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
    const cleanup=()=>{
      cancelAnimationFrame(frame);
      observer?.disconnect();
      document.removeEventListener('visibilitychange',visibility);
      reduced.removeEventListener('change',motion);
      if(renderer){
        renderer.gl.canvas.removeEventListener('webglcontextlost',contextLost);
        geometry?.remove();
        if(program)renderer.gl.deleteProgram(program.program);
        renderer.gl.canvas.remove();
        renderer.gl.getExtension('WEBGL_lose_context')?.loseContext();
        renderer=undefined;geometry=undefined;program=undefined;mesh=undefined;
      }
    };
    const contextLost=(event:Event)=>{
      event.preventDefault();lost=true;cancelAnimationFrame(frame);
      container.dataset.renderer='fallback';
    };
    const visibility=()=>{
      cancelAnimationFrame(frame);lastTime=0;
      if(!document.hidden&&!lost)frame=requestAnimationFrame(draw);
    };
    const motion=()=>{cancelAnimationFrame(frame);lastTime=0;frame=requestAnimationFrame(draw);};
    const draw=(time:number)=>{
      if(!renderer||!program||!mesh||lost||document.hidden)return;
      if(!reduced.matches&&lastTime&&time-lastTime<30){frame=requestAnimationFrame(draw);return;}
      const options=settings.current;
      const delta=lastTime?Math.min((time-lastTime)/1000,.05):0;
      lastTime=time;
      const input=options.audioLevelRef?.current??0;
      const raw=options.enableVoiceControl&&Number.isFinite(input)?Math.min(Math.max(input-.025,0)*options.voiceSensitivity,1):0;
      // Fast attack, slower release: speech feels responsive without jitter.
      smoothLevel+=(raw-smoothLevel)*(raw > smoothLevel ? .24 : .09);
      const nextDetected=smoothLevel>.06;
      if(nextDetected!==detected){detected=nextDetected;options.onVoiceDetected?.(detected);}
      if(!reduced.matches){
        rotation+=delta*(.025+smoothLevel*options.maxRotationSpeed);
        visualTime+=delta*(.16+smoothLevel*.7);
      }
      program.uniforms.iTime.value=reduced.matches?3:visualTime;
      program.uniforms.hue.value=options.hue;
      program.uniforms.rot.value=rotation;
      // Ambient color drifts slowly; shape movement comes only from measured speech.
      program.uniforms.hover.value=reduced.matches?0:smoothLevel;
      program.uniforms.energy.value=reduced.matches?0:smoothLevel;
      program.uniforms.hoverIntensity.value=options.maxHoverIntensity;
      renderer.render({scene:mesh});
      if(!reduced.matches)frame=requestAnimationFrame(draw);
    };
    try{
      renderer=new Renderer({alpha:true,premultipliedAlpha:true,antialias:false,dpr:Math.min(window.devicePixelRatio||1,1.5)});
      const gl=renderer.gl;
      gl.clearColor(0,0,0,0);
      gl.canvas.setAttribute('aria-hidden','true');
      gl.canvas.addEventListener('webglcontextlost',contextLost);
      container.appendChild(gl.canvas);
      geometry=new Triangle(gl);
      program=new Program(gl,{vertex:vert,fragment:frag,transparent:true,depthTest:false,depthWrite:false,uniforms:{
        iTime:{value:0},iResolution:{value:new Vec3(1,1,1)},hue:{value:settings.current.hue},
        hover:{value:0},rot:{value:0},hoverIntensity:{value:settings.current.maxHoverIntensity},energy:{value:0},
      }});
      mesh=new Mesh(gl,{geometry,program});
      const resize=()=>{
        if(!renderer||!program)return;
        const {width,height}=container.getBoundingClientRect();
        if(!width||!height)return;
        // OGL applies DPR itself. Multiplying dimensions again quadruples work.
        renderer.setSize(width,height);
        program.uniforms.iResolution.value.set(renderer.gl.canvas.width,renderer.gl.canvas.height,width/height);
        if(reduced.matches){cancelAnimationFrame(frame);frame=requestAnimationFrame(draw);}
      };
      observer=new ResizeObserver(resize);observer.observe(container);resize();
      document.addEventListener('visibilitychange',visibility);
      reduced.addEventListener('change',motion);
      container.dataset.renderer='webgl';
      frame=requestAnimationFrame(draw);
    }catch{
      cleanup();container.dataset.renderer='fallback';
    }
    return cleanup;
  },[]);
  return <div ref={containerRef} className={cn('relative h-full w-full',className)} aria-hidden="true" data-voice-orb="true" />;
};

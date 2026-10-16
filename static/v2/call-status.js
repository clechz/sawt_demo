// Backend progress and audible activity have separate priorities. Quiet audio
// must never replace a checkout, reconnecting, or saving state with "listening".
// One concise status describes actual backend work; no fabricated timers.
const phases={idle:'جاهزين لك',connecting:'جاري الاتصال',listening:'معك',waiting:'بانتظارك',processing:'جاري الرد',preparing:'أجهّز الملخص',readback:'ملخص طلبك',confirm:'بانتظار تأكيدك',paused:'الصوت متوقف',reconnecting:'جاري إعادة الاتصال',completed:'تم تأكيد الطلب',ending:'مع السلامة',ended:'انتهت المكالمة'};
const stages={understanding:'أراجع طلبك',resolving:'أراجع التفاصيل',search_menu:'أشوف المنيو',get_item:'أراجع الخيارات',add_item:'أضيف الصنف',update_item:'أعدّل طلبك',remove_item:'أشيل الصنف',set_branch:'أغيّر الفرع',set_service:'أعدّل طريقة الاستلام',checkout:'أجهّز الملخص',confirm_order:'أؤكد طلبك',lookup_order:'أشوف حالة طلبك'};
export function createCallStatus(render){
 let phase='idle',label='',epoch=-1,speaker='',heardAt=0;
 const show=text=>{if(text!==label){label=text;render(phase,text);}};
 return {
  phase(next){if(!phases[next])return;phase=next;speaker='';show(phases[next]);},
  progress(event){if(!Number.isInteger(event.epoch)||event.epoch<epoch||(phase==='waiting'&&event.epoch===epoch))return false;epoch=event.epoch;if(['ending','ended','completed','reconnecting'].includes(phase))return false;phase='processing';show(stages[event.stage]||phases.processing);return true;},
  interrupt(event){if(!Number.isInteger(event.epoch)||event.epoch<epoch||(phase==='waiting'&&event.epoch===epoch))return false;epoch=event.epoch;if(['processing','listening','waiting'].includes(phase)){phase='listening';show('نسمعك');}return true;},
  wait(event){if(!Number.isInteger(event.epoch)||event.epoch<epoch||['ending','ended','completed','reconnecting'].includes(phase))return false;epoch=event.epoch;phase='waiting';speaker='';show(phases.waiting);return true;},
  updated(event){if(!Number.isInteger(event.epoch)||event.epoch<epoch||['waiting','ending','ended','completed','reconnecting'].includes(phase))return false;epoch=event.epoch;phase='listening';speaker='';show(phases.listening);return true;},
  audio(local,remote,muted,now){if(phase!=='listening')return;const next=local>.035&&!muted?'نسمعك':remote>.025?'صوت يتكلم':'';if(next){speaker=next;heardAt=now;}else if(now-heardAt>650)speaker='';show(speaker||(muted?'الميكروفون مكتوم':'معك'));},
  reset(){epoch=-1;phase='idle';speaker='';heardAt=0;show(phases.idle);},
 };
}

// A compatibility check, not a claim about model quality or completed tasks.
const FIELDS = ['protocol', 'source_fingerprint', 'experience_version',
 'conversation_mode', 'voice', 'planner_model', 'voice_model'];
const MISMATCH = 'نسخة الوكيل الصوتي ما تطابق نسخة الموقع. يلزم تحديث الوكيل قبل المكالمة.';
function valid(contract) {
 return contract && contract.protocol === 1 &&
  /^[a-f0-9]{64}$/.test(contract.source_fingerprint) &&
  FIELDS.every(key => contract[key] !== undefined && contract[key] !== null);
}
export function validateCallBinding(call, requested) {
 const c = call?.required_worker;
 if (!valid(c) || c.experience_version !== requested.experience_version ||
     c.conversation_mode !== requested.conversation_mode || c.voice !== requested.voice)
  throw new Error('الموقع ما شغّل وضع المحادثة المطلوب. حدّث الموقع والوكيل مع بعض.');
}
export function validateReadyBinding(call, event) {
 const required = call?.required_worker, actual = event?.worker_contract;
 if (event?.call_id !== call?.id || !valid(required) || !valid(actual) ||
     FIELDS.some(key => required[key] !== actual[key])) throw new Error(MISMATCH);
 return actual;
}

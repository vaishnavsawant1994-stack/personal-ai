(()=>{
  'use strict';
  const PENDING_KEY='personal-ai:v1:pending-turn';
  const MAX_PENDING_AGE_MS=15*60*1000;
  const STATE_SCHEMA_VERSION=1;
  const CANONICAL_STATES=new Set(['IDLE','ACTIVE','LISTENING','UNDERSTANDING','THINKING','MEMORY_RETRIEVAL','KNOWLEDGE_RETRIEVAL','TOOL_ACTION','RESPONDING','NEEDS_APPROVAL','BACKGROUND','SUCCESS','WARNING','ERROR']);
  const STATE_POLL_MS=750,STATE_BACKOFF_MAX_MS=12000;
  let canonicalSequence=-1,canonicalRequestId=null,applyingCanonicalState=false;
  let statePollTimer=null,statePollFailures=0,stateRefreshInFlight=false,stateControllerClosed=false;
  let nextInputModality='text';
  let currentUiRequestId=null;
  let currentPlaybackRequestId=null;
  let playbackGeneration=0;
  let lastApprovalRequestId=null;
  let approvalReturnFocus=null;

  const uuid=()=>{
    const c=globalThis.crypto;
    if(c&&typeof c.randomUUID==='function')return c.randomUUID();
    if(!c||typeof c.getRandomValues!=='function')throw new Error('Secure request identity is unavailable in this browser context.');
    const b=new Uint8Array(16);c.getRandomValues(b);b[6]=(b[6]&15)|64;b[8]=(b[8]&63)|128;
    const h=[...b].map(x=>x.toString(16).padStart(2,'0')).join('');
    return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;
  };
  const rawPending=()=>{try{return JSON.parse(sessionStorage.getItem(PENDING_KEY)||'null')}catch{return null}};
  const loadPending=()=>{const p=rawPending();if(!p)return null;if(!p.created_at||Date.now()-Number(p.created_at)>MAX_PENDING_AGE_MS){try{sessionStorage.removeItem(PENDING_KEY)}catch{};return null}return p};
  const savePending=value=>{try{sessionStorage.setItem(PENDING_KEY,JSON.stringify(value))}catch{}};
  const clearPending=id=>{const p=rawPending();if(!p||p.request_id===id)try{sessionStorage.removeItem(PENDING_KEY)}catch{}};
  const terminalHttp=status=>status>=400&&status<500&&![408,409,425,429].includes(status);

  const renderVoiceControls=()=>{
    try{
      $('micButton').classList.toggle('active',handsFree&&!speaking);
      $('micButton').classList.toggle('speaking',speaking);
      $('micButton').setAttribute('aria-label',speaking?'Interrupt and listen':(handsFree?'Stop hands-free conversation':'Start hands-free conversation'));
    }catch{}
  };

  const configureStage5Accessibility=()=>{
    try{
      const panel=$('approvalPanel');
      if(panel){panel.setAttribute('role','alertdialog');panel.setAttribute('aria-modal','true');panel.setAttribute('aria-labelledby','approvalTitle');panel.setAttribute('aria-describedby','approvalDescription')}
      const stateLabel=$('stateLabel');if(stateLabel)stateLabel.setAttribute('aria-label','Personal AI semantic state: Idle');
      const core=typeof document!=='undefined'&&typeof document.querySelector==='function'?document.querySelector('.core-stage'):null;
      if(core){core.removeAttribute('aria-hidden');core.setAttribute('role','img');core.setAttribute('aria-label','Personal AI living core. The current semantic state is announced below.');const canvas=typeof core.querySelector==='function'?core.querySelector('canvas'):null;if(canvas)canvas.setAttribute('aria-hidden','true')}
    }catch{}
  };
  configureStage5Accessibility();

  const semanticRenderer=globalThis.setState;
  if(typeof semanticRenderer==='function'){
    globalThis.setState=function stage5StateRenderer(name,detail){
      renderVoiceControls();
      if(!applyingCanonicalState)return;
      return semanticRenderer(name,detail);
    };
  }

  const applyCanonicalState=snapshot=>{
    if(!snapshot||Number(snapshot.schema_version)!==STATE_SCHEMA_VERSION)return false;
    const sequence=Number(snapshot.sequence),canonicalName=String(snapshot.state||'').trim().toUpperCase();
    if(!Number.isInteger(sequence)||sequence<0||sequence<=canonicalSequence||!CANONICAL_STATES.has(canonicalName))return false;
    const requestId=snapshot.request_id==null?null:String(snapshot.request_id);
    canonicalSequence=sequence;canonicalRequestId=requestId;
    if(typeof setState==='function'){
      applyingCanonicalState=true;
      try{setState(canonicalName.toLowerCase().replaceAll('_','-'),String(snapshot.label||''))}finally{applyingCanonicalState=false}
    }
    try{
      const safeLabel=String(snapshot.label||canonicalName.replaceAll('_',' '));
      const stateLabel=$('stateLabel');if(stateLabel){stateLabel.textContent=safeLabel;stateLabel.setAttribute('aria-label',`Personal AI semantic state: ${safeLabel}`)}
      document.documentElement.dataset.aiState=canonicalName.toLowerCase();document.documentElement.dataset.aiSequence=String(sequence);
    }catch{}
    return true;
  };
  const scheduleCanonicalRefresh=(delay=STATE_POLL_MS)=>{
    if(stateControllerClosed||statePollTimer!==null)return;
    statePollTimer=setTimeout(()=>{statePollTimer=null;refreshCanonicalState()},Math.max(0,delay));
  };
  const refreshCanonicalState=async()=>{
    if(stateControllerClosed||stateRefreshInFlight)return false;
    if(typeof document!=='undefined'&&document.visibilityState==='hidden'){scheduleCanonicalRefresh(STATE_POLL_MS);return false}
    stateRefreshInFlight=true;
    try{
      const snapshot=await api('/runtime-state');statePollFailures=0;applyCanonicalState(snapshot);scheduleCanonicalRefresh(STATE_POLL_MS);return true;
    }catch{
      statePollFailures=Math.min(statePollFailures+1,6);
      scheduleCanonicalRefresh(Math.min(STATE_BACKOFF_MAX_MS,STATE_POLL_MS*(2**statePollFailures)));return false;
    }finally{stateRefreshInFlight=false}
  };
  const onVisibilityChange=()=>{if(document.visibilityState==='visible'){if(statePollTimer!==null){clearTimeout(statePollTimer);statePollTimer=null}refreshCanonicalState()}};
  const closeStateController=()=>{stateControllerClosed=true;if(statePollTimer!==null){clearTimeout(statePollTimer);statePollTimer=null}try{document.removeEventListener('visibilitychange',onVisibilityChange)}catch{}};
  try{document.addEventListener('visibilitychange',onVisibilityChange);globalThis.addEventListener('pagehide',closeStateController,{once:true})}catch{}
  globalThis.personalAiApplyCanonicalState=applyCanonicalState;
  globalThis.personalAiRuntimeStateSnapshot=()=>({schema_version:STATE_SCHEMA_VERSION,state_sequence:canonicalSequence,request_id:canonicalRequestId});
  refreshCanonicalState();

  const voiceClientEvent=(event,requestId,detail='')=>api('/voice/client-event',{
    method:'POST',body:JSON.stringify({event,request_id:requestId||null,detail:String(detail||'').slice(0,160)})
  }).catch(()=>{});

  const legacyCreateRecognition=globalThis.createRecognition;
  if(typeof legacyCreateRecognition==='function'){
    globalThis.createRecognition=function stage3CreateRecognition(){
      const instance=legacyCreateRecognition();if(!instance)return instance;const onstart=instance.onstart;
      instance.onstart=function(event){if(onstart)onstart.call(this,event);voiceClientEvent('listening_started',currentUiRequestId)};
      const onresult=instance.onresult;instance.onresult=function(event){for(let i=event.resultIndex;i<event.results.length;i++){if(event.results[i].isFinal){nextInputModality='voice';break}}if(onresult)return onresult.call(this,event)};return instance;
    };
  }

  const stopPlayback=(notify=true)=>{const interrupted=currentPlaybackRequestId;playbackGeneration++;try{if(globalThis.speechSynthesis)globalThis.speechSynthesis.cancel()}catch{}try{speaking=false;currentUtterance=null}catch{}renderVoiceControls();if(notify&&interrupted)voiceClientEvent('playback_interrupted',interrupted);return interrupted};
  function canonicalSpeakReply(text,requestId){
    const rid=requestId||lastApprovalRequestId||currentPlaybackRequestId||currentUiRequestId;lastApprovalRequestId=null;stopPlayback(false);currentPlaybackRequestId=rid||null;const generation=++playbackGeneration;
    if(!globalThis.speechSynthesis){voiceClientEvent('tts_error',rid,'speech_synthesis_unavailable');$('voiceAlert').textContent='Spoken replies are unavailable in this browser. The answer is shown on screen.';if(handsFree)scheduleListening(400);return}
    stopRecognition();let attempt=0,finished=false;const stale=()=>generation!==playbackGeneration||currentPlaybackRequestId!==rid;
    const finish=()=>{if(finished||stale())return;finished=true;voiceClientEvent('tts_completed',rid);speaking=false;currentUtterance=null;renderVoiceControls();$('voiceAlert').textContent='';if(!pendingApproval&&handsFree&&preference('continuous_voice',true))scheduleListening(350);else if(!pendingApproval){handsFree=false;renderVoiceControls()}};
    const fail=detail=>{if(finished||stale())return;finished=true;voiceClientEvent('tts_error',rid,detail||'speech_synthesis_blocked');speaking=false;currentUtterance=null;renderVoiceControls();$('voiceAlert').textContent='The spoken reply could not play. The canonical text answer is still available.';if(handsFree&&!pendingApproval)scheduleListening(450)};
    const play=()=>{if(stale()||finished)return;attempt++;let started=false;const utterance=makeUtterance(text,{start:()=>{if(stale())return;started=true;speaking=true;renderVoiceControls();voiceClientEvent('tts_started',rid)},end:finish,error:event=>{if(stale()||finished)return;if(event&&event.error==='interrupted'){finish();return}if(attempt<2)setTimeout(play,80);else fail(event&&event.error)}});currentUtterance=utterance;globalThis.speechSynthesis.cancel();globalThis.speechSynthesis.resume();globalThis.speechSynthesis.speak(utterance);globalThis.speechSynthesis.resume();setTimeout(()=>{if(!started&&!finished&&!stale()){if(attempt<2)play();else fail('start_timeout')}},1600)};play();
  }
  globalThis.speakReply=canonicalSpeakReply;
  const legacyShowApproval=globalThis.showApproval;
  if(typeof legacyShowApproval==='function'){
    globalThis.showApproval=function stage3ShowApproval(approval){
      lastApprovalRequestId=(approval&&approval.request_id)||currentUiRequestId||null;
      try{approvalReturnFocus=document.activeElement&&typeof document.activeElement.focus==='function'?document.activeElement:null}catch{approvalReturnFocus=null}
      const result=legacyShowApproval(approval);
      try{const cancel=$('rejectApproval');if(cancel&&typeof cancel.focus==='function')setTimeout(()=>cancel.focus(),0)}catch{}
      return result;
    };
  }
  const legacyClearApproval=globalThis.clearApproval;
  if(typeof legacyClearApproval==='function'){
    globalThis.clearApproval=function stage5ClearApproval(){
      const result=legacyClearApproval();const target=approvalReturnFocus;approvalReturnFocus=null;
      try{if(target&&typeof target.focus==='function')setTimeout(()=>target.focus(),0)}catch{}
      return result;
    };
  }
  globalThis.interruptAndListen=async function stage3InterruptAndListen(){const requestId=currentPlaybackRequestId;const wasSpeaking=Boolean(speaking||(globalThis.speechSynthesis&&globalThis.speechSynthesis.speaking));stopPlayback(false);handsFree=true;renderVoiceControls();try{await api('/voice/barge',{method:'POST',body:JSON.stringify({speaking:wasSpeaking,request_id:requestId})})}catch{}scheduleListening(100)};

  const mic=$('micButton');if(mic){mic.onclick=async()=>{if(speaking||(globalThis.speechSynthesis&&globalThis.speechSynthesis.speaking)){await globalThis.interruptAndListen();return}if(turnInFlight&&currentUiRequestId){try{await api('/voice/operation/cancel',{method:'POST',body:JSON.stringify({request_id:currentUiRequestId})});$('voiceAlert').textContent='Cancelling the current operation safely…';handsFree=true;renderVoiceControls()}catch(error){$('voiceAlert').textContent=error.message}return}if(handsFree){handsFree=false;stopRecognition();renderVoiceControls();return}handsFree=true;renderVoiceControls();try{await primeVoice();startListening()}catch(error){handsFree=false;renderVoiceControls();$('voiceAlert').textContent=error.message}}}

  const approveButton=$('approveApproval');if(approveButton){approveButton.onclick=async()=>{if(!pendingApproval)return;const approval=pendingApproval;const approvalRequestId=approval.request_id||lastApprovalRequestId||null;clearApproval();handsFree=true;renderVoiceControls();try{const result=await api('/approval/'+encodeURIComponent(approval.id)+'/approve',{method:'POST',body:'{}'});const resultRequestId=result.request_id||approvalRequestId;$('reply').textContent=result.reply;if(result.status==='approval_required'&&result.approval){showApproval({...result.approval,request_id:result.approval.request_id||resultRequestId})}else{appendMessage('assistant_message',result.reply);if(!currentUiRequestId||currentUiRequestId===resultRequestId)canonicalSpeakReply(result.reply,resultRequestId);else voiceClientEvent('playback_interrupted',resultRequestId,'stale_approval_result')}refreshCanonicalState()}catch(error){handsFree=false;renderVoiceControls();$('voiceAlert').textContent=error.message;refreshCanonicalState()}}}
  const rejectButton=$('rejectApproval');if(rejectButton){rejectButton.onclick=async()=>{if(!pendingApproval)return;const approval=pendingApproval;const approvalRequestId=approval.request_id||lastApprovalRequestId||null;clearApproval();handsFree=true;renderVoiceControls();try{const result=await api('/approval/'+encodeURIComponent(approval.id)+'/reject',{method:'POST',body:'{}'});const resultRequestId=result.request_id||approvalRequestId;$('reply').textContent=result.reply;appendMessage('approval_rejected',result.reply);if(!currentUiRequestId||currentUiRequestId===resultRequestId)canonicalSpeakReply(result.reply,resultRequestId);else voiceClientEvent('playback_interrupted',resultRequestId,'stale_approval_result');refreshCanonicalState()}catch(error){handsFree=false;renderVoiceControls();$('voiceAlert').textContent=error.message;refreshCanonicalState()}}}

  globalThis.sendTurn=async function v1SendTurn(text){
    const clean=String(text||'').trim();if(!clean||turnInFlight)return;const candidateModality=nextInputModality==='voice'?'voice':'text';nextInputModality='text';let pending=loadPending();const samePending=pending&&pending.text===clean&&String(pending.conversation_id||'')===String(currentConversationId||'');if(!samePending){pending={request_id:uuid(),text:clean,conversation_id:currentConversationId||null,input_modality:candidateModality,created_at:Date.now()};savePending(pending)}else if(!pending.input_modality){pending.input_modality=candidateModality;savePending(pending)}currentUiRequestId=pending.request_id;lastApprovalRequestId=null;if(currentPlaybackRequestId&&currentPlaybackRequestId!==pending.request_id)stopPlayback(true);stopRecognition();turnInFlight=true;$('voiceAlert').textContent='';$('transcript').textContent=clean;$('reply').textContent='';if(!samePending)appendMessage('user_message',clean);
    try{let result,lastError;for(let attempt=0;attempt<2;attempt++){try{result=await api('/voice/turn',{method:'POST',headers:{'X-Personal-AI-Input-Modality':pending.input_modality||'text'},body:JSON.stringify({request_id:pending.request_id,transcript:clean,conversation_id:currentConversationId})});lastError=null;break}catch(error){lastError=error;if(terminalHttp(error.status))break;await new Promise(resolve=>setTimeout(resolve,180*(attempt+1)))}}if(lastError)throw lastError;clearPending(pending.request_id);if(currentUiRequestId!==pending.request_id)return;currentConversationId=result.conversation_id||currentConversationId;if(result.conversation_title){currentConversationTitle=result.conversation_title;$('conversationTitle').textContent=currentConversationTitle}$('reply').textContent=result.reply;turnInFlight=false;if(result.status==='approval_required')showApproval(result.approval);else appendMessage('assistant_message',result.reply);canonicalSpeakReply(result.reply,pending.request_id);refreshConversationList($('conversationSearch').value).catch(()=>{});refreshCanonicalState()}catch(error){if(currentUiRequestId!==pending.request_id)return;turnInFlight=false;if(terminalHttp(error.status))clearPending(pending.request_id);if(error.message!=='turn_cancelled'){$('voiceAlert').textContent=error.message;appendMessage('approval_rejected',error.message)}if(handsFree)scheduleListening(500);refreshCanonicalState()}
  };
})();
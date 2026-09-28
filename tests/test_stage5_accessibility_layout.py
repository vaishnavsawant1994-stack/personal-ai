from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _run_node(source: str) -> dict:
    node = shutil.which('node')
    if not node:
        pytest.fail('Node.js is required for Stage-5 Home accessibility qualification')
    process = subprocess.run(
        [node, '-e', source],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert process.returncode == 0, process.stderr or process.stdout
    lines = [line for line in process.stdout.splitlines() if line.strip()]
    assert lines, process.stderr
    return json.loads(lines[-1])


def test_pwa_accessibility_focus_core_label_and_semantic_state_are_behavioral():
    script = r"""
const fs=require('fs');
const source=fs.readFileSync('pwa/v1-runtime.js','utf8');
const timers=[];let timerId=0;const focusLog=[];const elements=new Map();
const makeElement=id=>({
  id,attrs:{},classList:{toggle:()=>{}},textContent:'',value:'',onclick:null,
  setAttribute(name,value){this.attrs[name]=String(value)},
  removeAttribute(name){delete this.attrs[name]},
  focus(){focusLog.push(id)},
});
const element=id=>{if(!elements.has(id))elements.set(id,makeElement(id));return elements.get(id)};
const canvas=makeElement('neuralCanvas');
const core=makeElement('core-stage');core.attrs['aria-hidden']='true';core.querySelector=selector=>selector==='canvas'?canvas:null;
const returnFocus={focus(){focusLog.push('return-target')}};
const docListeners={};const globalListeners={};

globalThis.handsFree=false;globalThis.speaking=false;globalThis.turnInFlight=false;globalThis.pendingApproval=null;
globalThis.currentConversationId=null;globalThis.currentConversationTitle='';globalThis.currentUtterance=null;
globalThis.preference=()=>true;globalThis.scheduleListening=()=>{};globalThis.stopRecognition=()=>{};
globalThis.makeUtterance=()=>({});globalThis.appendMessage=()=>{};globalThis.refreshConversationList=async()=>{};globalThis.createRecognition=undefined;
globalThis.clearApproval=()=>{globalThis.pendingApproval=null};
globalThis.showApproval=approval=>{globalThis.pendingApproval=approval};
globalThis.sessionStorage={getItem:()=>null,setItem:()=>{},removeItem:()=>{}};
globalThis.crypto=require('crypto').webcrypto;
globalThis.$=id=>element(id);
globalThis.setState=()=>{};
globalThis.document={
  visibilityState:'visible',documentElement:{dataset:{}},activeElement:returnFocus,
  querySelector:selector=>selector==='.core-stage'?core:null,
  addEventListener:(name,fn)=>{docListeners[name]=fn},
  removeEventListener:(name,fn)=>{if(docListeners[name]===fn)delete docListeners[name]},
};
globalThis.addEventListener=(name,fn)=>{globalListeners[name]=fn};
globalThis.setTimeout=(fn,delay)=>{const id=++timerId;timers.push({id,fn,delay,fired:false,cleared:false});return id};
globalThis.clearTimeout=id=>{const timer=timers.find(item=>item.id===id);if(timer)timer.cleared=true};
let stateCalls=0;
globalThis.api=async path=>{
  if(path==='/runtime-state'){
    stateCalls++;
    return {schema_version:1,state:'WARNING',sequence:9,request_id:'r9',label:'Attention needed'};
  }
  return {};
};
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  eval(source);await flush();
  const panel=element('approvalPanel');const stateLabel=element('stateLabel');
  globalThis.showApproval({id:'A1',request_id:'r9',tool:'send_email'});
  const focusInto=timers.find(item=>item.delay===0&&!item.fired&&!item.cleared);if(focusInto){focusInto.fired=true;focusInto.fn()}
  globalThis.clearApproval();
  const focusBack=timers.find(item=>item.delay===0&&!item.fired&&!item.cleared);if(focusBack){focusBack.fired=true;focusBack.fn()}
  console.log(JSON.stringify({
    panel:panel.attrs,
    core:core.attrs,
    canvas:canvas.attrs,
    stateText:stateLabel.textContent,
    stateAria:stateLabel.attrs['aria-label'],
    focusLog,
    stateCalls,
  }));
})().catch(error=>{console.error(error);process.exit(1)});
"""
    result = _run_node(script)
    assert result['panel']['role'] == 'alertdialog'
    assert result['panel']['aria-modal'] == 'true'
    assert result['panel']['aria-labelledby'] == 'approvalTitle'
    assert result['panel']['aria-describedby'] == 'approvalDescription'
    assert result['core']['role'] == 'img'
    assert 'living core' in result['core']['aria-label'].lower()
    assert 'aria-hidden' not in result['core']
    assert result['canvas']['aria-hidden'] == 'true'
    assert result['stateText'] == 'Attention needed'
    assert result['stateAria'] == 'Personal AI semantic state: Attention needed'
    assert result['focusLog'][:2] == ['rejectApproval', 'return-target']
    assert result['stateCalls'] == 1


def test_home_keyboard_text_alternatives_reduced_motion_and_responsive_breakpoints_are_present():
    page = (ROOT / 'pwa' / 'index.html').read_text(encoding='utf-8')
    runtime = (ROOT / 'pwa' / 'v1-runtime.js').read_text(encoding='utf-8')

    # Keyboard-accessible native controls and icon text alternatives.
    assert 'id="message"' in page and 'aria-label="Message Personal AI"' in page
    assert 'id="sendButton"' in page and 'aria-label="Send message"' in page
    assert 'id="micButton"' in page and 'aria-label="Start hands-free conversation"' in page
    assert 'id="attachmentButton"' in page and 'aria-label="Add a document"' in page
    assert 'id="rejectApproval" type="button"' in page
    assert 'id="approveApproval" class="approve" type="button"' in page
    assert "setAttribute('role','alertdialog')" in runtime
    assert "setTimeout(()=>cancel.focus(),0)" in runtime
    assert "setTimeout(()=>target.focus(),0)" in runtime

    # Semantic state/error text is announced independently of color or animation.
    assert 'aria-live="polite"' in page
    assert 'role="alert"' in page
    assert 'Personal AI semantic state:' in runtime

    # Reduced-motion and software-responsive contracts cover desktop default,
    # tablet/mobile width, and short mobile/PWA height without claiming devices.
    assert '@media(prefers-reduced-motion:reduce)' in page
    assert '@media(max-width:900px)' in page
    assert '@media(max-height:760px) and (max-width:900px)' in page
    assert 'width:min(1120px,100%)' in page
    assert 'width:calc(100% - 28px)' in page
    assert 'height:100dvh' in page
    assert 'env(safe-area-inset-bottom)' in page

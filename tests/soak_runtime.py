from __future__ import annotations
import argparse,asyncio,base64,gc,os,sqlite3,sys,time,psutil,tempfile
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from memory.store import MemoryStore
from automation.conditions import evaluate_condition
from devices.gateway import DeviceGateway,DeviceCommand
from security.vault import SecretVault
from voice.openai_realtime import OpenAIRealtimeVoiceSession

class Events:
 def emit(self,*args,**kwargs):pass
class Registry:pass

def realtime_settings():
 return SimpleNamespace(openai_api_key='test',realtime_provider='openai',realtime_model='gpt-realtime-2.1',realtime_voice='marin',realtime_reasoning_effort='low',realtime_safety_identifier='',realtime_instructions='test',realtime_sample_rate=24000)

async def verify_device_pending_cleanup(gateway,i):
 try:await gateway.request('offline',DeviceCommand('device_info',{},f'soak-{i}'),timeout=.01)
 except RuntimeError:pass
 assert not gateway._pending

def main():
 p=argparse.ArgumentParser();p.add_argument('--seconds',type=int,default=45);a=p.parse_args();proc=psutil.Process(os.getpid());start=proc.memory_info().rss;peak=start;deadline=time.time()+a.seconds;i=0
 with tempfile.TemporaryDirectory() as d:
  root=Path(d);db=root/'soak.sqlite3';store=MemoryStore(db);current_password='soak-password';vault=SecretVault(root/'vault.json',current_password);gateway=DeviceGateway(Registry(),Events());realtime=OpenAIRealtimeVoiceSession(realtime_settings(),Events())
  while time.time()<deadline:
   store.remember(type='note',subject=f's{i%100}',content=f'c{i}',source='soak',confidence=.5,verified=False,tags=['soak']);store.search('c',limit=10);assert evaluate_condition({'path':'n','op':'gte','value':1},{'n':1})
   if i%50==0:
    vault.set('rotation-probe',str(i));assert vault.get('rotation-probe')==str(i)
    encoded=base64.b64encode(f'audio-{i}'.encode()).decode();realtime.handle_event({'type':'response.output_audio.delta','delta':encoded});assert realtime._play_q.get_nowait()==f'audio-{i}'.encode()
   if i%250==0:asyncio.run(verify_device_pending_cleanup(gateway,i))
   if i%500==0:
    current_password=f'soak-password-{i}';vault.rotate_password(current_password);assert vault.get('rotation-probe')==str(i)
    gc.collect();peak=max(peak,proc.memory_info().rss)
   i+=1
  integrity=sqlite3.connect(db).execute('PRAGMA integrity_check').fetchone()[0];assert integrity=='ok'
  vault_reloaded=SecretVault(root/'vault.json',current_password);assert vault_reloaded.get('rotation-probe') is not None
 end=proc.memory_info().rss;growth=end-start
 if growth>256*1024*1024:raise SystemExit(f'memory growth too high: {growth}')
 print({'iterations':i,'rss_start':start,'rss_peak':peak,'rss_end':end,'rss_growth':growth,'sqlite_integrity':integrity,'pending_device_requests':len(gateway._pending)})
if __name__=='__main__':main()

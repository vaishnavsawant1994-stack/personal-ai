from __future__ import annotations
import io,json,requests
from pathlib import Path
class ModelRouter:
    def __init__(self,settings): self.settings=settings
    def _provider(self):
        if self.settings.ai_provider=='openrouter': return 'https://openrouter.ai/api/v1',self.settings.openrouter_api_key,self.settings.openrouter_model
        return self.settings.local_ai_url,None,self.settings.local_ai_model
    def chat(self,prompt:str,*,system:str='You are a helpful personal AI assistant.',history:list[dict]|None=None,temperature:float=.3)->str:
        base,key,model=self._provider(); return self._chat_call(base,key,model,[{'role':'system','content':system},*(history or []),{'role':'user','content':prompt}],temperature)
    def json(self,prompt:str,*,system:str='Return valid JSON only.')->dict:
        raw=self.chat(prompt,system=system,temperature=.1).strip()
        if raw.startswith('```'): raw=raw.replace('```json','').replace('```','').strip()
        return json.loads(raw)
    def vision(self,prompt:str,image_data_url:str)->str:
        base,key,model=self._provider(); model=self.settings.vision_model or model; return self._chat_call(base,key,model,[{'role':'user','content':[{'type':'text','text':prompt},{'type':'image_url','image_url':{'url':image_data_url}}]}],.1)
    def embed(self,text:str)->list[float]:
        base,key,_=self._provider(); headers={'Content-Type':'application/json'}
        if key: headers['Authorization']=f'Bearer {key}'
        r=requests.post(f'{base}/embeddings',headers=headers,json={'model':self.settings.embedding_model,'input':text},timeout=90); r.raise_for_status(); return list(map(float,r.json()['data'][0]['embedding']))
    def transcribe(self,path:Path)->str:
        base,key,_=self._provider(); headers={}
        if key: headers['Authorization']=f'Bearer {key}'
        with open(path,'rb') as f:r=requests.post(f'{base}/audio/transcriptions',headers=headers,files={'file':(Path(path).name,f,'audio/wav')},data={'model':self.settings.stt_model},timeout=120)
        r.raise_for_status(); return str(r.json().get('text','')).strip()
    def synthesize(self,text:str)->bytes:
        base,key,_=self._provider(); headers={'Content-Type':'application/json'}
        if key: headers['Authorization']=f'Bearer {key}'
        r=requests.post(f'{base}/audio/speech',headers=headers,json={'model':self.settings.tts_model,'voice':self.settings.tts_voice,'input':text,'format':'wav'},timeout=120); r.raise_for_status(); return r.content
    def speak(self,text:str):
        try:
            import sounddevice as sd,soundfile as sf; audio,sr=sf.read(io.BytesIO(self.synthesize(text)),dtype='float32'); sd.play(audio,sr); sd.wait(); return
        except Exception:
            import pyttsx3; e=pyttsx3.init(); e.say(text); e.runAndWait()
    @staticmethod
    def _chat_call(base,key,model,messages,temperature):
        headers={'Content-Type':'application/json'}
        if key: headers['Authorization']=f'Bearer {key}'
        r=requests.post(f'{base}/chat/completions',headers=headers,json={'model':model,'messages':messages,'temperature':temperature},timeout=120); r.raise_for_status(); return r.json()['choices'][0]['message']['content'].strip()

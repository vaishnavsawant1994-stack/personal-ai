from __future__ import annotations
from pathlib import Path
import base64
class ScreenUnderstanding:
    def __init__(self,models=None,data_dir:Path|None=None): self.models=models; self.data_dir=Path(data_dir or Path.home()/'.personal_ai')
    def capture(self,monitor:int=1)->Path:
        import mss
        from PIL import Image
        path=self.data_dir/'screenshots'/'vision-latest.png'; path.parent.mkdir(parents=True,exist_ok=True)
        with mss.mss() as sct:
            mon=sct.monitors[monitor]; raw=sct.grab(mon); Image.frombytes('RGB',raw.size,raw.rgb).save(path)
        return path
    def prepare_payload(self,question:str='Describe the visible screen.'):
        path=self.capture(); encoded=base64.b64encode(path.read_bytes()).decode('ascii'); return {'screenshot':str(path),'question':question,'image_data_url':f'data:image/png;base64,{encoded}'}
    def analyze(self,question:str='Describe the visible screen.',monitor:int=1):
        payload=self.prepare_payload(question)
        if not self.models: return payload
        return {'screenshot':payload['screenshot'],'question':question,'analysis':self.models.vision(question,payload['image_data_url'])}

from pathlib import Path
import sounddevice as sd
import soundfile as sf

class Recorder:
    def record(self,path:Path,seconds:float=5.0,samplerate:int=16000):
        path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); data=sd.rec(int(seconds*samplerate),samplerate=samplerate,channels=1,dtype="float32"); sd.wait(); sf.write(path,data,samplerate); return path

class TTSService:
    def __init__(self): self._engine=None
    def speak(self,text:str):
        if self._engine is None:
            import pyttsx3; self._engine=pyttsx3.init()
        self._engine.say(text); self._engine.runAndWait()

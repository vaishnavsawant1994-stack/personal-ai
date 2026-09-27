from __future__ import annotations
import argparse,json,time
from core.config import settings
from core.events import EventBus
from voice.openai_realtime import OpenAIRealtimeVoiceSession

def main():
    p=argparse.ArgumentParser();p.add_argument('--seconds',type=int,default=45);a=p.parse_args()
    if not settings.openai_api_key:raise SystemExit('OPENAI_API_KEY is required')
    import sounddevice as sd
    default=sd.default.device
    if default is None:raise SystemExit('No default audio devices configured')
    events=EventBus(); session=OpenAIRealtimeVoiceSession(settings,events)
    session.start(); deadline=time.time()+a.seconds
    try:
        while time.time()<deadline:
            if session.connected and session.metrics['response_count']>0 and session.metrics['audio_chunks_out']>0:break
            time.sleep(.25)
    finally:session.stop()
    evidence={'audio_device':str(default),'connected':session.connected,'metrics':session.metrics}
    print(json.dumps(evidence,sort_keys=True))
    if session.metrics['connect_attempts']<1:raise SystemExit('Realtime connection was never attempted')
    if session.metrics['response_count']<1 or session.metrics['audio_chunks_out']<1:raise SystemExit('No end-to-end spoken Realtime response observed; speak into the microphone during the probe')

if __name__=='__main__':main()

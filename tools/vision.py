from vision.screen_understanding import ScreenUnderstanding
from tools.registry import Tool,Risk
def register(reg,models,settings):
    vision=ScreenUnderstanding(models=models,data_dir=settings.data_dir)
    reg.register(Tool('screen_understand','Capture and interpret current screen with multimodal model; params: question,monitor',lambda p:vision.analyze(str(p.get('question','Describe the visible screen.')),int(p.get('monitor',1))),Risk.READ_ONLY))

from __future__ import annotations
import json
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTabWidget,QTextBrowser
class ControlPanel(QDialog):
    def __init__(self,runtime,parent=None):
        super().__init__(parent); self.runtime=runtime; self.setWindowTitle('Personal AI — Control & Dashboard'); self.resize(900,650); lay=QVBoxLayout(self); top=QHBoxLayout(); top.addWidget(QLabel('CONTROL CENTER')); top.addStretch(1); b=QPushButton('Refresh'); b.clicked.connect(self.refresh); top.addWidget(b); lay.addLayout(top); self.tabs=QTabWidget(); lay.addWidget(self.tabs); self.views={}
        for name in ['Overview','Devices','Automations','Integrations','Security']:
            view=QTextBrowser(); self.views[name]=view; self.tabs.addTab(view,name)
        self.refresh()
    def refresh(self):
        rt=self.runtime; graph=rt['second_brain'].graph(); self.views['Overview'].setPlainText(json.dumps({'memory_nodes':len(graph.get('nodes',[])),'memory_edges':len(graph.get('edges',[])),'tools':len(rt['tools'].all()),'automations':len(rt['automations'].list()),'devices':len(rt['device_registry'].list())},indent=2)); self.views['Devices'].setPlainText(json.dumps(rt['device_registry'].list(),indent=2,default=str)); self.views['Automations'].setPlainText(json.dumps(rt['automations'].list(),indent=2,default=str)); self.views['Integrations'].setPlainText(json.dumps(rt['integrations'].list(),indent=2,default=str)); self.views['Security'].setPlainText(json.dumps({'autonomy_mode':rt['tools'].settings.autonomy_mode,'vault_enabled':rt.get('vault') is not None,'remote_control':'authenticated device bearer token','pairing':'loopback initiated','browser_profile':'persistent local profile'},indent=2))

from __future__ import annotations
from pathlib import Path
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QCheckBox,QComboBox,QPushButton,QMessageBox,QFileDialog,QPlainTextEdit

class SettingsPanel(QDialog):
    def __init__(self,runtime,parent=None):
        super().__init__(parent);self.runtime=runtime;self.prefs=runtime['preferences'];self.setWindowTitle('Personal AI Settings');self.resize(620,650)
        lay=QVBoxLayout(self);lay.addWidget(QLabel('<h2>Personal AI Settings</h2>'))
        self.name=QLineEdit(str(self.prefs.get('preferred_name','')));self.name.setPlaceholderText('What should Personal AI call you?');lay.addWidget(QLabel('Preferred name'));lay.addWidget(self.name)
        self.wake=QLineEdit(str(self.prefs.get('wake_phrase','Hey Personal')));lay.addWidget(QLabel('Wake phrase'));lay.addWidget(self.wake)
        self.mode=QComboBox();self.mode.addItems(['observe','suggest','ask','act']);self.mode.setCurrentText(str(self.prefs.get('autonomy_mode','ask')));lay.addWidget(QLabel('Autonomy'));lay.addWidget(self.mode)
        self.voice=QCheckBox('Start voice when Personal AI opens');self.voice.setChecked(bool(self.prefs.get('launch_voice_on_start')));lay.addWidget(self.voice)
        self.hints=QCheckBox('Show contextual memory hints');self.hints.setChecked(bool(self.prefs.get('show_memory_hints',True)));lay.addWidget(self.hints)
        self.motion=QCheckBox('Reduce motion');self.motion.setChecked(bool(self.prefs.get('reduce_motion')));lay.addWidget(self.motion)
        self.contrast=QCheckBox('High contrast');self.contrast.setChecked(bool(self.prefs.get('high_contrast')));lay.addWidget(self.contrast)
        row=QHBoxLayout();save=QPushButton('Save settings');save.clicked.connect(self.save);backup=QPushButton('Create backup');backup.clicked.connect(self.create_backup);restore=QPushButton('Restore backup…');restore.clicked.connect(self.restore_backup);row.addWidget(save);row.addWidget(backup);row.addWidget(restore);lay.addLayout(row)
        lay.addWidget(QLabel('Local diagnostics'));self.diagnostics=QPlainTextEdit();self.diagnostics.setReadOnly(True);self.refresh();lay.addWidget(self.diagnostics,1);refresh=QPushButton('Refresh diagnostics');refresh.clicked.connect(self.refresh);lay.addWidget(refresh)
    def save(self):
        phrase=self.wake.text().strip() or 'Hey Personal';mode=self.mode.currentText();self.prefs.update(onboarding_complete=True,preferred_name=self.name.text().strip(),wake_phrase=phrase,launch_voice_on_start=self.voice.isChecked(),show_memory_hints=self.hints.isChecked(),reduce_motion=self.motion.isChecked(),high_contrast=self.contrast.isChecked(),autonomy_mode=mode)
        gate=self.runtime.get('wake_phrase');tools=self.runtime.get('tools')
        if gate:gate.phrases=(phrase,);gate.reset()
        if tools and hasattr(tools,'set_autonomy_mode'):tools.set_autonomy_mode(mode)
        parent=self.parent()
        if parent and hasattr(parent,'pulse') and hasattr(parent.pulse,'set_reduce_motion'):parent.pulse.set_reduce_motion(self.motion.isChecked())
        QMessageBox.information(self,'Saved','Preferences saved locally. High-contrast changes apply fully after restart; autonomy, wake phrase and reduced motion apply now.')
    def create_backup(self):
        path=self.runtime['backups'].create();QMessageBox.information(self,'Backup created',str(path))
    def restore_backup(self):
        path,_=QFileDialog.getOpenFileName(self,'Restore Personal AI backup',str(Path.home()),'Personal AI Backup (*.paibackup)')
        if not path:return
        answer=QMessageBox.question(self,'Restore backup','This will replace matching Personal AI data files. Continue?')
        if answer!=QMessageBox.StandardButton.Yes:return
        result=self.runtime['backups'].restore(Path(path));QMessageBox.information(self,'Restore complete',f"Restored {result['restored']} files. Restart Personal AI to reload restored state.")
    def refresh(self):
        import json
        telemetry=self.runtime['telemetry'].snapshot();graph=self.runtime['memory'].graph();devices=self.runtime['device_registry'].list();plugins=self.runtime['plugins'].list() if hasattr(self.runtime['plugins'],'list') else []
        report={'telemetry':telemetry,'memory':{'nodes':len(graph.get('nodes',[])),'edges':len(graph.get('edges',[]))},'devices':len(devices),'plugins':len(plugins),'autonomy':getattr(self.runtime.get('tools'),'autonomy_mode','ask'),'backup_dir':str(self.runtime['backups'].backup_dir)};self.diagnostics.setPlainText(json.dumps(report,indent=2,default=str))

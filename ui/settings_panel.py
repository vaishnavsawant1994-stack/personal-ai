from __future__ import annotations
import json
from ui.design_system import stylesheet
from pathlib import Path
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QCheckBox,QComboBox,QPushButton,QMessageBox,QFileDialog,QPlainTextEdit,QScrollArea,QWidget
from security.policy_targets import application_identity,normalize_origin

class SettingsPanel(QDialog):
    def __init__(self,runtime,parent=None):
        super().__init__(parent);self.runtime=runtime;self.prefs=runtime['preferences'];self.setWindowTitle('Personal AI Settings')
        self.setStyleSheet(stylesheet(bool(self.prefs.get('high_contrast'))))
        self.resize(900,740)
        outer=QVBoxLayout(self);scroll=QScrollArea();scroll.setWidgetResizable(True);content=QWidget();scroll.setWidget(content);outer.addWidget(scroll);lay=QVBoxLayout(content);lay.addWidget(QLabel('<h2>Personal AI Settings</h2>'))
        self.name=QLineEdit(str(self.prefs.get('preferred_name','')));self.name.setPlaceholderText('What should Personal AI call you?');lay.addWidget(QLabel('Preferred name'));lay.addWidget(self.name)
        self.wake=QLineEdit(str(self.prefs.get('wake_phrase','Hey Personal')));lay.addWidget(QLabel('Wake phrase'));lay.addWidget(self.wake)
        self.mode=QComboBox();self.mode.addItems(['observe','suggest','ask','act']);self.mode.setCurrentText(str(self.prefs.get('autonomy_mode','ask')));lay.addWidget(QLabel('Autonomy'));lay.addWidget(self.mode)
        self.privacy=QComboBox();self.privacy.addItems(['local_only','local_preferred','external_allowed']);self.privacy.setCurrentText(str(self.prefs.get('model_privacy_mode','local_preferred')));lay.addWidget(QLabel('Model privacy'));lay.addWidget(self.privacy)
        self.voice=QCheckBox('Start voice when Personal AI opens');self.voice.setChecked(bool(self.prefs.get('launch_voice_on_start')));lay.addWidget(self.voice)
        self.hints=QCheckBox('Show contextual memory hints');self.hints.setChecked(bool(self.prefs.get('show_memory_hints',True)));lay.addWidget(self.hints)
        self.motion=QCheckBox('Reduce motion');self.motion.setChecked(bool(self.prefs.get('reduce_motion')));lay.addWidget(self.motion)
        self.contrast=QCheckBox('High contrast');self.contrast.setChecked(bool(self.prefs.get('high_contrast')));lay.addWidget(self.contrast)
        row=QHBoxLayout();save=QPushButton('Save settings');save.clicked.connect(self.save);backup=QPushButton('Create backup');backup.clicked.connect(self.create_backup);restore=QPushButton('Restore backup…');restore.clicked.connect(self.restore_backup);row.addWidget(save);row.addWidget(backup);row.addWidget(restore);lay.addLayout(row)
        lay.addWidget(QLabel('<h3>Apps & Tools — Effective permissions</h3>'));lay.addWidget(QLabel('Default is deny. Permission changes require owner reauthentication and are versioned/audited locally.'))
        prow=QHBoxLayout();self.policy_type=QComboBox();self.policy_type.addItems(['domain','application','path','destination','clipboard']);self.policy_target=QLineEdit();self.policy_target.setPlaceholderText('HTTPS origin, executable path, allowed root, or exact destination');prow.addWidget(self.policy_type);prow.addWidget(self.policy_target,1);lay.addLayout(prow)
        orow=QHBoxLayout();self.policy_ops=QLineEdit();self.policy_ops.setPlaceholderText('Allowed operations, comma-separated');self.policy_expiry=QLineEdit();self.policy_expiry.setPlaceholderText('Expiry minutes (optional)');orow.addWidget(self.policy_ops,1);orow.addWidget(self.policy_expiry);lay.addLayout(orow)
        self.policy_password=QLineEdit();self.policy_password.setEchoMode(QLineEdit.EchoMode.Password);self.policy_password.setPlaceholderText('Owner password — checked now, never stored in policy/logs');lay.addWidget(self.policy_password)
        brow=QHBoxLayout();add=QPushButton('Add permission');add.clicked.connect(self.add_policy);self.policy_revoke_id=QLineEdit();self.policy_revoke_id.setPlaceholderText('Policy ID');toggle=QPushButton('Enable / Disable');toggle.clicked.connect(self.toggle_policy);revoke=QPushButton('Revoke');revoke.clicked.connect(self.revoke_policy);reset=QPushButton('Reset safe defaults');reset.clicked.connect(self.reset_policies);brow.addWidget(add);brow.addWidget(self.policy_revoke_id,1);brow.addWidget(toggle);brow.addWidget(revoke);brow.addWidget(reset);lay.addLayout(brow)
        self.policy_view=QPlainTextEdit();self.policy_view.setReadOnly(True);self.policy_view.setMaximumHeight(170);lay.addWidget(self.policy_view);prefresh=QPushButton('Refresh permissions');prefresh.clicked.connect(self.refresh_policy_view);lay.addWidget(prefresh)
        lay.addWidget(QLabel('<h3>Activities — Recovery review</h3>'));lay.addWidget(QLabel('Inspect verified steps, uncertainty, redacted evidence, compensation limits and audit references. Consequential recovery decisions still pass through the Trusted Action Core and recent owner reauthentication.'))
        rrow=QHBoxLayout();self.recovery_tx=QLineEdit();self.recovery_tx.setPlaceholderText('Operator transaction ID');rrefresh=QPushButton('Inspect recovery');rrefresh.clicked.connect(self.refresh_recovery_view);rexport=QPushButton('Export recovery report');rexport.clicked.connect(self.export_recovery_report);rrow.addWidget(self.recovery_tx,1);rrow.addWidget(rrefresh);rrow.addWidget(rexport);lay.addLayout(rrow)
        self.recovery_view=QPlainTextEdit();self.recovery_view.setReadOnly(True);self.recovery_view.setMaximumHeight(210);lay.addWidget(self.recovery_view)
        lay.addWidget(QLabel('<h3>Models — Health & routing</h3>'));lay.addWidget(QLabel('Privacy-safe provider health, circuit state, retry/failover counts and recent generation routing. Health checks never send conversation prompts.'))
        self.model_view=QPlainTextEdit();self.model_view.setReadOnly(True);self.model_view.setMaximumHeight(230);lay.addWidget(self.model_view);mrow=QHBoxLayout();mrefresh=QPushButton('Refresh model status');mrefresh.clicked.connect(self.refresh_model_view);mprobe=QPushButton('Run bounded health check');mprobe.clicked.connect(lambda:self.refresh_model_view(True));mrow.addWidget(mrefresh);mrow.addWidget(mprobe);lay.addLayout(mrow)
        lay.addWidget(QLabel('Local diagnostics'));self.diagnostics=QPlainTextEdit();self.diagnostics.setReadOnly(True);self.refresh();lay.addWidget(self.diagnostics,1);refresh=QPushButton('Refresh diagnostics');refresh.clicked.connect(self.refresh);lay.addWidget(refresh);self.refresh_policy_view();self.refresh_model_view()
        for label in content.findChildren(QLabel):label.setWordWrap(True)
    def save(self):
        phrase=self.wake.text().strip() or 'Hey Personal';mode=self.mode.currentText();privacy=self.privacy.currentText();self.prefs.update(onboarding_complete=True,preferred_name=self.name.text().strip(),wake_phrase=phrase,launch_voice_on_start=self.voice.isChecked(),show_memory_hints=self.hints.isChecked(),reduce_motion=self.motion.isChecked(),high_contrast=self.contrast.isChecked(),autonomy_mode=mode,model_privacy_mode=privacy)
        gate=self.runtime.get('wake_phrase');tools=self.runtime.get('tools');models=self.runtime.get('models')
        if gate:gate.phrases=(phrase,);gate.reset()
        if tools and hasattr(tools,'set_autonomy_mode'):tools.set_autonomy_mode(mode)
        if models and hasattr(models,'set_owner_privacy'):models.set_owner_privacy(privacy)
        parent=self.parent()
        if parent and hasattr(parent,'pulse') and hasattr(parent.pulse,'set_reduce_motion'):parent.pulse.set_reduce_motion(self.motion.isChecked())
        QMessageBox.information(self,'Saved','Preferences saved locally. High-contrast changes apply fully after restart; autonomy, privacy, wake phrase and reduced motion apply now.')
    def _reauthenticated(self):
        owner=self.runtime.get('owner_access');password=self.policy_password.text();self.policy_password.clear()
        if not owner or not owner.password_configured():QMessageBox.warning(self,'Reauthentication required','Configure the owner password before changing critical permissions.');return False
        if not owner.verify_password(password):QMessageBox.warning(self,'Reauthentication required','Owner reauthentication failed. No permission was changed.');return False
        return True
    def _policy_target_identity(self):
        kind=self.policy_type.currentText();raw=self.policy_target.text().strip()
        if not raw:raise ValueError('A target is required.')
        if kind=='domain':
            origin=normalize_origin(raw);return {'scheme':origin.scheme,'host':origin.host,'port':origin.port,'include_subdomains':False,'allow_ip_literal':False,'allow_private_network':False}
        if kind=='application':return application_identity(raw)
        if kind=='path':return {'root':str(Path(raw).expanduser().resolve(strict=False)),'allow_network':False,'allow_mounted':False}
        if kind=='clipboard':return {'destination':raw}
        return {'identity':raw}
    def add_policy(self):
        tools=self.runtime.get('tools');gateway=getattr(tools,'policy_gateway',None)
        if gateway is None:QMessageBox.warning(self,'Unavailable','Policy gateway unavailable; safe default remains deny.');return
        if not self._reauthenticated():return
        try:
            target=self._policy_target_identity();ops=[item.strip() for item in self.policy_ops.text().split(',') if item.strip()]
            if not ops:raise ValueError('At least one operation is required.')
            expiry=self.policy_expiry.text().strip();expires_at=None
            if expiry:expires_at=__import__('time').time()+max(1,int(expiry))*60
            row=gateway.add_policy(owner_id='owner',target_type=self.policy_type.currentText(),target_identity=target,allowed_operations=ops,security_epoch=tools.current_security_epoch(),actor='owner_settings',reauthenticated=True,expires_at=expires_at);self.policy_revoke_id.setText(row['policy_id']);self.refresh_policy_view();QMessageBox.information(self,'Permission added','Permission saved locally. Everything else remains denied by default.')
        except Exception as exc:QMessageBox.warning(self,'Permission not changed',str(exc))
    def toggle_policy(self):
        tools=self.runtime.get('tools');gateway=getattr(tools,'policy_gateway',None);pid=self.policy_revoke_id.text().strip()
        if gateway is None or not pid:return
        current=gateway.store.get(pid)
        if not current:QMessageBox.warning(self,'Not found','No matching owner policy was found.');return
        if not self._reauthenticated():return
        enabled=not bool(current.get('active'))
        if gateway.set_policy_active(pid,owner_id='owner',enabled=enabled,actor='owner_settings',reauthenticated=True):self.refresh_policy_view();QMessageBox.information(self,'Permission updated','Permission enabled.' if enabled else 'Permission disabled. Future actions are denied until re-enabled.')
    def revoke_policy(self):
        tools=self.runtime.get('tools');gateway=getattr(tools,'policy_gateway',None);pid=self.policy_revoke_id.text().strip()
        if gateway is None or not pid:return
        if not self._reauthenticated():return
        if gateway.revoke_policy(pid,owner_id='owner',actor='owner_settings',reauthenticated=True):self.refresh_policy_view();QMessageBox.information(self,'Permission revoked','Future actions will be re-evaluated against current policy.')
        else:QMessageBox.warning(self,'Not found','No matching owner policy was found.')
    def reset_policies(self):
        tools=self.runtime.get('tools');gateway=getattr(tools,'policy_gateway',None)
        if gateway is None:return
        if QMessageBox.question(self,'Reset permissions','Revoke all active Personal AI permissions and return to default deny?')!=QMessageBox.StandardButton.Yes:return
        if not self._reauthenticated():return
        count=gateway.reset_to_safe_defaults('owner',actor='owner_settings',reauthenticated=True);self.refresh_policy_view();QMessageBox.information(self,'Safe defaults restored',f'Revoked {count} active permission(s).')
    def refresh_policy_view(self):
        tools=self.runtime.get('tools');snapshot=tools.policy_snapshot('owner') if tools and hasattr(tools,'policy_snapshot') else {'policies':[],'recent_use':[],'safe_default':'deny'}
        safe={'safe_default':snapshot.get('safe_default'),'schema_version':snapshot.get('schema_version'),'policies':[{'policy_id':p.get('policy_id'),'version':p.get('version'),'target_type':p.get('target_type'),'target_identity':p.get('target_identity'),'allowed_operations':p.get('allowed_operations'),'denied_operations':p.get('denied_operations'),'expires_at':p.get('expires_at'),'active':p.get('active')} for p in snapshot.get('policies',[])],'recent_use':snapshot.get('recent_use',[])[:10]};self.policy_view.setPlainText(json.dumps(safe,indent=2,default=str))
    def refresh_recovery_view(self):
        txid=self.recovery_tx.text().strip();tools=self.runtime.get('tools')
        if not txid:self.recovery_view.setPlainText('Enter an operator transaction ID.');return
        try:
            report=tools.recovery_snapshot(txid) if tools and hasattr(tools,'recovery_snapshot') else None
            if report is None:raise RuntimeError('Recovery authority unavailable')
            self.recovery_view.setPlainText(json.dumps(report,indent=2,default=str))
        except KeyError:self.recovery_view.setPlainText('No matching operator transaction was found.')
        except Exception as exc:self.recovery_view.setPlainText(f'Recovery view unavailable: {type(exc).__name__}')
    def export_recovery_report(self):
        txid=self.recovery_tx.text().strip();tools=self.runtime.get('tools')
        if not txid:return
        try:
            authority=tools.ensure_recovery_authority();report=authority.export_report(txid)
            path,_=QFileDialog.getSaveFileName(self,'Export recovery report',f'recovery-{txid[:12]}.json','JSON (*.json)')
            if not path:return
            Path(path).write_text(json.dumps(report,indent=2,default=str),encoding='utf-8');QMessageBox.information(self,'Recovery report exported','A redacted, checksummed recovery report was exported.')
        except Exception as exc:QMessageBox.warning(self,'Export failed',f'Recovery report could not be exported ({type(exc).__name__}).')
    def refresh_model_view(self,probe=False):
        models=self.runtime.get('models')
        try:
            report=models.health_status(probe=probe) if models and hasattr(models,'health_status') else models.status(probe=probe)
            self.model_view.setPlainText(json.dumps(report,indent=2,default=str))
        except Exception as exc:self.model_view.setPlainText(f'Model diagnostics unavailable: {type(exc).__name__}')
    def create_backup(self):
        path=self.runtime['backups'].create();QMessageBox.information(self,'Backup created',str(path))
    def restore_backup(self):
        path,_=QFileDialog.getOpenFileName(self,'Restore Personal AI backup',str(Path.home()),'Personal AI Backup (*.paibackup)')
        if not path:return
        answer=QMessageBox.question(self,'Restore backup','This will replace matching Personal AI data files. Continue?')
        if answer!=QMessageBox.StandardButton.Yes:return
        result=self.runtime['backups'].restore(Path(path));QMessageBox.information(self,'Restore complete',f"Restored {result['restored']} files. Restart Personal AI to reload restored state.")
    def refresh(self):
        telemetry=self.runtime['telemetry'].snapshot();graph=self.runtime['memory'].graph();devices=self.runtime['device_registry'].list();plugins=self.runtime['plugins'].list() if hasattr(self.runtime['plugins'],'list') else [];tools=self.runtime.get('tools');models=self.runtime.get('models')
        model_summary=models.health_status(probe=False).get('w8',{}) if models and hasattr(models,'health_status') else {}
        report={'telemetry':telemetry,'model_observability':model_summary,'memory':{'nodes':len(graph.get('nodes',[])),'edges':len(graph.get('edges',[]))},'devices':len(devices),'plugins':len(plugins),'autonomy':getattr(tools,'autonomy_mode','ask'),'backup_dir':str(self.runtime['backups'].backup_dir),'policy_safe_default':'deny','operator_recovery_schema':getattr(getattr(tools,'recovery_authority',None),'SCHEMA_VERSION',None)};self.diagnostics.setPlainText(json.dumps(report,indent=2,default=str))

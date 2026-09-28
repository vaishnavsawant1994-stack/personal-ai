from desktop.observation_policy import build_observation_record
from desktop.operator_transactions import OperatorBinding, OperatorTransactionStore


BINDING = OperatorBinding('owner','device','session',4)


def _record():
    screen={'observation_id':'obs-evidence','captured_at':100.0,'expires_at':200.0,'retention_expires_at':300.0,'screenshot_evidence_ref':'screenshots/obs.png','screen_fingerprint':'abc','sanitized_checksum':'abc','redaction_count':2,'redaction_status':'sanitized','redaction_method':'browser_native_element_mask','coordinate_space_version':1,'capture_source':'browser_native','visual_evidence_unavailable':False}
    app={'available':True,'identity_digest':'app','application':'browser','executable':'browser.exe','process_id':1,'process_start_token':'start','window_id':'window','window_title_sha256':'title'}
    return build_observation_record(binding=BINDING,transaction_id='tx',application=app,screen=screen,browser=None,reason='test',initiator='authenticated_transaction')


def test_evidence_metadata_survives_store_restart(tmp_path):
    path=tmp_path/'operator.sqlite3'; store=OperatorTransactionStore(path); record=_record(); store.save_observation(record)
    recovered=OperatorTransactionStore(path).observation(record['observation_id'])
    meta=recovered['sensitivity']
    assert meta['evidence_id']=='obs-evidence'
    assert meta['sanitized_checksum']=='abc'
    assert meta['redaction_status']=='sanitized'
    assert meta['redaction_method']=='browser_native_element_mask'
    assert meta['coordinate_space_version']==1
    assert meta['capture_source']=='browser_native'
    assert meta['retention_expires_at']==300.0

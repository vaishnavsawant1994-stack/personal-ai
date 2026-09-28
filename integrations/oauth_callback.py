from __future__ import annotations
import hashlib,json,time

def resolve_oauth_context(state_store,*,state,owner_id,device_id,session_id,security_epoch,now=None):
    """Resolve durable OAuth routing without consuming the one-use state or verifier."""
    stamp=time.time() if now is None else float(now); digest=hashlib.sha256(str(state).encode()).hexdigest()
    with state_store._con() as con:
        con.execute('BEGIN IMMEDIATE'); row=con.execute('SELECT * FROM oauth_transactions WHERE state_digest=?',(digest,)).fetchone()
        if not row: con.rollback(); raise PermissionError('OAuth transaction is invalid or already consumed')
        if row['status']!='pending': con.rollback(); raise PermissionError('OAuth transaction is invalid or already consumed')
        if stamp>float(row['expires_at']):
            con.execute("UPDATE oauth_transactions SET status='expired',failure_code='expired' WHERE state_digest=? AND status='pending'",(digest,)); con.commit(); state_store._delete_verifier(digest); raise PermissionError('OAuth transaction expired')
        checks=[('owner',row['owner_id'],owner_id),('device',row['device_id'],device_id),('session',row['session_id'],session_id),('security epoch',str(row['security_epoch']),str(int(security_epoch)))]
        mismatch=next((name for name,a,b in checks if (a or None)!=(b or None)),None)
        if mismatch: con.rollback(); raise PermissionError(f'OAuth {mismatch} mismatch')
        con.rollback()
    return {'connector_id':row['connector_id'],'provider_id':row['provider_id'],'redirect_uri':row['redirect_uri'],'scopes':json.loads(row['scopes_json']),'state_digest':digest}

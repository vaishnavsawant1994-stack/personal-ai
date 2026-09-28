from __future__ import annotations
import base64
from email.message import EmailMessage
from tools.registry import Risk, Tool, VerificationResult
from security.request_context import current_trusted_request

def _identity():
    ctx=current_trusted_request()
    return {'owner_id':'owner','device_id':getattr(ctx,'device_id',None),'session_id':getattr(ctx,'session_id',None)}

def _connector_call(adapter, method_name, *args, destination='', **kwargs):
    method=getattr(adapter, method_name)
    if getattr(adapter, 'gateway', None) is not None:
        return method(*args, destination=destination, **_identity(), **kwargs)
    return method(*args, **kwargs)


def register(registry,adapters):
    adapters=dict(adapters or {})
    gmail=adapters.get('gmail')
    if gmail is not None:
        registry.register(Tool('gmail_list_messages','List Gmail messages; params: query,max_results',lambda p:gmail.list_messages(q=str(p.get('query',''))[:500],max_results=max(1,min(int(p.get('max_results',20)),100))),Risk.READ_ONLY,connector_id='gmail',capability='gmail.read',minimum_risk=Risk.READ_ONLY))
        registry.register(Tool('gmail_get_message','Read Gmail message metadata; params: message_id',lambda p:gmail.get_message(str(p['message_id']),format='metadata'),Risk.READ_ONLY,connector_id='gmail',capability='gmail.read'))
        registry.register(Tool('gmail_search_messages','Search Gmail messages; params: query,max_results',lambda p:gmail.search_messages(str(p.get('query',''))[:500],max(1,min(int(p.get('max_results',20)),100))),Risk.READ_ONLY,connector_id='gmail',capability='gmail.search'))
        def raw_message(params):
            recipient=str(params['to']).strip(); subject=str(params.get('subject','')).strip()[:500]; body=str(params.get('body',''))[:100000]
            if '@' not in recipient or any(c in recipient for c in '\r\n'):raise ValueError('A valid recipient email is required')
            msg=EmailMessage(); msg['To']=recipient; msg['Subject']=subject; msg.set_content(body); return base64.urlsafe_b64encode(msg.as_bytes()).decode().rstrip('=')
        def send_email(params):return _connector_call(gmail,'send_raw',raw_message(params),destination=str(params['to']).strip())
        def verify_sent(params,result):
            mid=str((result or {}).get('id') or '') if isinstance(result,dict) else ''
            opid=str((result or {}).get('_personal_ai_operation_id') or '') if isinstance(result,dict) else ''
            if opid and getattr(gmail,'gateway',None):
                gmail.gateway.state.transition_operation(opid,'verified' if mid else 'failed',verification_state='verified' if mid else 'verification_failed')
                gmail.gateway.state.audit('operation.verified' if mid else 'operation.verification_failed',connector_id='gmail',correlation_id=opid,payload={'operation':'gmail.send'})
            return VerificationResult(bool(mid),'provider message id returned' if mid else 'provider message id missing',{'provider_resource_id':mid} if mid else {})
        registry.register(Tool('gmail_send_message','Send an email; params: to,subject,body. Always requires owner approval.',send_email,Risk.EXTERNAL_SIDE_EFFECT,verifier=verify_sent,verification_required=True,connector_id='gmail',capability='gmail.send',minimum_risk=Risk.EXTERNAL_SIDE_EFFECT,prohibited_data_classifications=('secret','restricted')))
        def draft_email(params):return _connector_call(gmail,'create_draft',raw_message(params),destination=str(params['to']).strip())
        registry.register(Tool('gmail_create_draft','Create an email draft; params: to,subject,body.',draft_email,Risk.REVERSIBLE,verifier=verify_sent,verification_required=True,connector_id='gmail',capability='gmail.draft',minimum_risk=Risk.REVERSIBLE,prohibited_data_classifications=('secret',)))
        registry.register(Tool('gmail_modify_message','Modify Gmail labels; params: message_id,add_labels,remove_labels.',lambda p:gmail.modify_message(str(p['message_id']),list(p.get('add_labels') or []),list(p.get('remove_labels') or [])),Risk.REVERSIBLE,verifier=lambda p,r:VerificationResult(bool(r),'provider modification response received',{}),verification_required=True,connector_id='gmail',capability='gmail.modify',minimum_risk=Risk.REVERSIBLE))
        registry.register(Tool('gmail_delete_message','Permanently delete a Gmail message. Prohibited by default.',lambda p:gmail.delete_message(str(p['message_id'])),Risk.CRITICAL,connector_id='gmail',capability='gmail.delete',minimum_risk=Risk.CRITICAL,requires_reauth=True,prohibited=True))
    calendar=adapters.get('calendar')
    if calendar is not None:
        registry.register(Tool('calendar_list_events','List calendar events; params: calendar_id,timeMin,timeMax,maxResults',lambda p:calendar.list_events(str(p.get('calendar_id','primary')),timeMin=p.get('timeMin'),timeMax=p.get('timeMax'),maxResults=max(1,min(int(p.get('maxResults',20)),100)),singleEvents=True,orderBy='startTime'),Risk.READ_ONLY,connector_id='calendar',capability='calendar.read'))
        registry.register(Tool('calendar_search_events','Search calendar events; params: query,calendar_id',lambda p:calendar.list_events(str(p.get('calendar_id','primary')),q=str(p.get('query',''))[:500],maxResults=max(1,min(int(p.get('maxResults',20)),100)),singleEvents=True,orderBy='startTime'),Risk.READ_ONLY,connector_id='calendar',capability='calendar.search'))
        def create_event(p):return _connector_call(calendar,'create_event',dict(p['event']),str(p.get('calendar_id','primary')),destination=str(p.get('calendar_id','primary')))
        def verify_event(p,r):
            eid=str((r or {}).get('id') or '') if isinstance(r,dict) else ''
            opid=str((r or {}).get('_personal_ai_operation_id') or '') if isinstance(r,dict) else ''
            if opid and getattr(calendar,'gateway',None):
                calendar.gateway.state.transition_operation(opid,'verified' if eid else 'failed',verification_state='verified' if eid else 'verification_failed')
                calendar.gateway.state.audit('operation.verified' if eid else 'operation.verification_failed',connector_id='calendar',correlation_id=opid,payload={'operation':'calendar'})
            return VerificationResult(bool(eid),'provider event id returned' if eid else 'provider event id missing',{'provider_resource_id':eid} if eid else {})
        def rollback_create(p,r):
            eid=str((r or {}).get('id') or '') if isinstance(r,dict) else ''; opid=str((r or {}).get('_personal_ai_operation_id') or '') if isinstance(r,dict) else ''
            if not eid:raise RuntimeError('created event id unavailable for rollback')
            try:
                calendar.delete_event(eid,str(p.get('calendar_id','primary')))
                if opid and getattr(calendar,'gateway',None):calendar.gateway.state.transition_operation(opid,'rolled_back',verification_state='verified');calendar.gateway.state.audit('rollback.completed',connector_id='calendar',correlation_id=opid,payload={'operation':'calendar.create'})
                return {'rolled_back':True,'event_id':eid}
            except Exception:
                if opid and getattr(calendar,'gateway',None):calendar.gateway.state.transition_operation(opid,'rollback_failed');calendar.gateway.state.audit('rollback.failed',connector_id='calendar',correlation_id=opid,payload={'operation':'calendar.create'})
                raise
        registry.register(Tool('calendar_create_event','Create a calendar event; params: event,calendar_id. Requires owner approval.',create_event,Risk.EXTERNAL_SIDE_EFFECT,verifier=verify_event,rollback=rollback_create,rollback_description='Delete the newly created event when its provider id is known.',verification_required=True,connector_id='calendar',capability='calendar.create',minimum_risk=Risk.EXTERNAL_SIDE_EFFECT,prohibited_data_classifications=('secret',)))
        registry.register(Tool('calendar_update_event','Update a calendar event; params: event_id,event,calendar_id. Requires owner approval.',lambda p:_connector_call(calendar,'update_event',str(p['event_id']),dict(p['event']),str(p.get('calendar_id','primary')),destination=str(p.get('calendar_id','primary'))),Risk.EXTERNAL_SIDE_EFFECT,verifier=verify_event,verification_required=True,connector_id='calendar',capability='calendar.update',minimum_risk=Risk.EXTERNAL_SIDE_EFFECT,prohibited_data_classifications=('secret',)))
        def verify_delete(p,r):
            try:exists=calendar.verify_event(str(p['event_id']),str(p.get('calendar_id','primary')))
            except Exception:exists=False
            return VerificationResult(not exists,'event no longer present' if not exists else 'event is still present',{})
        registry.register(Tool('calendar_delete_event','Delete a calendar event; params: event_id,calendar_id. Requires explicit owner approval.',lambda p:_connector_call(calendar,'delete_event',str(p['event_id']),str(p.get('calendar_id','primary')),destination=str(p.get('calendar_id','primary'))),Risk.DESTRUCTIVE,verifier=verify_delete,verification_required=True,requires_reauth=True,connector_id='calendar',capability='calendar.delete',minimum_risk=Risk.DESTRUCTIVE))
    slack=adapters.get('slack')
    if slack is not None:
        registry.register(Tool(
            'slack_read_messages',
            'Read recent Slack channel messages; params: channel,limit',
            lambda p:_connector_call(
                slack,'history',str(p['channel']),max(1,min(int(p.get('limit',50)),100)),
                destination=str(p['channel']),
            ),
            Risk.READ_ONLY,connector_id='slack',capability='slack.read',
        ))
        def send_slack(params):
            channel=str(params['channel']).strip()
            return _connector_call(
                slack,'post_message',channel,str(params['text'])[:40000],destination=channel,
            )
        def verify_slack(params,result):
            ok=bool(isinstance(result,dict) and result.get('ok') and result.get('ts'))
            opid=str((result or {}).get('_personal_ai_operation_id') or '') if isinstance(result,dict) else ''
            if opid and getattr(slack,'gateway',None):
                slack.gateway.state.transition_operation(
                    opid,'verified' if ok else 'failed',
                    verification_state='verified' if ok else 'verification_failed',
                )
                slack.gateway.state.audit(
                    'operation.verified' if ok else 'operation.verification_failed',
                    connector_id='slack',correlation_id=opid,payload={'operation':'slack.send'},
                )
            evidence={'provider_message_ts':str(result.get('ts'))[:200]} if ok else {}
            return VerificationResult(ok,'provider message timestamp returned' if ok else 'provider message timestamp missing',evidence)
        registry.register(Tool(
            'slack_send_message',
            'Send a Slack channel message; params: channel,text. Requires owner approval.',
            send_slack,Risk.EXTERNAL_SIDE_EFFECT,
            verifier=verify_slack,verification_required=True,
            connector_id='slack',capability='slack.send',
            minimum_risk=Risk.EXTERNAL_SIDE_EFFECT,
            prohibited_data_classifications=('secret',),
        ))
    home=adapters.get('home_assistant')
    if home is not None:
        registry.register(Tool(
            'home_assistant_read_state',
            'Read a Home Assistant entity state; params: entity_id',
            lambda p:_connector_call(home,'state',str(p['entity_id']),destination=str(p['entity_id'])),
            Risk.READ_ONLY,connector_id='home_assistant',capability='home_assistant.read',
        ))
        def call_home_service(params):
            data=dict(params.get('data') or {})
            destination=str(data.get('entity_id') or f"{params['domain']}.{params['service']}")
            return _connector_call(
                home,'call_service',str(params['domain']),str(params['service']),data,
                destination=destination,
            )
        def verify_home_service(params,result):
            data=dict(params.get('data') or {})
            entity_id=str(data.get('entity_id') or '').strip()
            service=str(params.get('service') or '').strip().lower()
            expected={'turn_on':'on','turn_off':'off'}.get(service)
            verified=False;evidence={}
            if entity_id and expected:
                try:
                    observed=_connector_call(home,'state',entity_id,destination=entity_id)
                    actual=str((observed or {}).get('state') or '').lower() if isinstance(observed,dict) else ''
                    verified=actual==expected
                    evidence={'entity_id':entity_id[:240],'expected_state':expected,'observed_state':actual[:120]}
                except Exception:
                    verified=False
            opid=str((result or {}).get('_personal_ai_operation_id') or '') if isinstance(result,dict) else ''
            if opid and getattr(home,'gateway',None):
                home.gateway.state.transition_operation(
                    opid,'verified' if verified else 'recovery_review_required',
                    verification_state='verified' if verified else 'verification_failed',
                    retry_decision='no_blind_retry' if not verified else None,
                )
                home.gateway.state.audit(
                    'operation.verified' if verified else 'recovery.review_required',
                    connector_id='home_assistant',correlation_id=opid,
                    payload={'operation':'home_assistant.call_service','entity_id':entity_id[:240]},
                )
            return VerificationResult(
                verified,
                'fresh entity state matches requested service' if verified else 'service effect could not be independently verified',
                evidence,
            )
        registry.register(Tool(
            'home_assistant_call_service',
            'Call a Home Assistant service; params: domain,service,data. Requires owner approval.',
            call_home_service,Risk.EXTERNAL_SIDE_EFFECT,
            verifier=verify_home_service,verification_required=True,
            connector_id='home_assistant',capability='home_assistant.call_service',
            minimum_risk=Risk.EXTERNAL_SIDE_EFFECT,
        ))

from pathlib import Path
import os
from dataclasses import replace
from integrations.registry import IntegrationRegistry,Integration
from integrations.adapters import GmailAdapter,GoogleCalendarAdapter,SlackAdapter,HomeAssistantAdapter
from integrations.google_write import GoogleDriveWriteAdapter,GoogleSheetsWriteAdapter
from integrations.oauth import OAuthAccountManager,OAuthProvider
from integrations.contracts import builtin_manifests, gmail_manifest, calendar_manifest, drive_manifest, sheets_manifest, slack_manifest, home_assistant_manifest
from integrations.state import ConnectorStateStore
from integrations.gateway import ConnectorGateway
from security.approvals import ApprovalManager

GOOGLE_AUTH='https://accounts.google.com/o/oauth2/v2/auth'; GOOGLE_TOKEN='https://oauth2.googleapis.com/token'; GOOGLE_REVOKE='https://oauth2.googleapis.com/revoke'
SLACK_AUTH='https://slack.com/oauth/v2/authorize'; SLACK_TOKEN='https://slack.com/api/oauth.v2.access'; SLACK_REVOKE='https://slack.com/api/auth.revoke'

def _runtime_manifest(manifest):
    declared=list(manifest.required_oauth_scopes)+list(manifest.optional_oauth_scopes)
    required=set(manifest.required_oauth_scopes)
    for operation in manifest.operations:
        if operation.prohibited:
            continue
        for scope in operation.required_scopes:
            if scope not in required and scope not in declared:
                declared.append(scope)
    optional=tuple(scope for scope in declared if scope not in required)
    return replace(manifest,optional_oauth_scopes=optional)

def provider_catalog(settings):
    out={}
    if getattr(settings,'google_client_id',''):
        out['google']=OAuthProvider('google',GOOGLE_AUTH,GOOGLE_TOKEN,settings.google_client_id,['openid','email','https://www.googleapis.com/auth/gmail.readonly','https://www.googleapis.com/auth/gmail.compose','https://www.googleapis.com/auth/gmail.send','https://www.googleapis.com/auth/gmail.modify','https://www.googleapis.com/auth/calendar.readonly','https://www.googleapis.com/auth/calendar','https://www.googleapis.com/auth/drive.readonly','https://www.googleapis.com/auth/drive.file','https://www.googleapis.com/auth/spreadsheets.readonly','https://www.googleapis.com/auth/spreadsheets'],getattr(settings,'google_client_secret',''),GOOGLE_REVOKE)
    if getattr(settings,'slack_client_id',''):
        out['slack']=OAuthProvider('slack',SLACK_AUTH,SLACK_TOKEN,settings.slack_client_id,['channels:history','chat:write'],getattr(settings,'slack_client_secret',''),SLACK_REVOKE)
    return out

def build_integrations(settings,vault=None):
    state=ConnectorStateStore(Path(settings.data_dir)/'connectors.sqlite3',vault=vault); gateway=ConnectorGateway(state); reg=IntegrationRegistry(state_store=state)
    for manifest in builtin_manifests():reg.register_manifest(_runtime_manifest(manifest))
    approval=ApprovalManager(path=Path(settings.data_dir)/'trusted-actions.sqlite3')
    providers=provider_catalog(settings)
    redirect_uri=(os.getenv('OAUTH_REDIRECT_URI','').strip() or getattr(settings,'oauth_redirect_uri','') or 'http://127.0.0.1:8766/oauth/callback')
    allowed={redirect_uri,'http://127.0.0.1:8766/oauth/callback'}
    oauth=OAuthAccountManager(vault,redirect_uri=redirect_uri,state_store=state,allowed_redirects=allowed,security_epoch_provider=approval.current_security_epoch) if vault else None
    reg.gateway=gateway; reg.oauth=oauth; reg.providers=providers
    adapters={}; google_token=None; google_scopes=None
    if oauth and 'google' in providers:
        try:
            google_token=oauth.token(providers['google']); google_scopes=set(oauth.token_record(providers['google']).get('granted_scopes') or [])
        except Exception:pass
    gmail_token=google_token or getattr(settings,'gmail_token',''); calendar_token=google_token or getattr(settings,'calendar_token','')
    if gmail_token:
        a=GmailAdapter(gmail_token,gateway=gateway); a.granted_scopes=google_scopes if google_token else None; adapters['gmail']=a; reg.register(Integration('gmail','Gmail',set(o.name for o in gmail_manifest().operations),lambda:bool(a.list_messages(max_results=1) is not None),gmail_manifest(),True))
    if calendar_token:
        a=GoogleCalendarAdapter(calendar_token,gateway=gateway); a.granted_scopes=google_scopes if google_token else None; adapters['calendar']=a; reg.register(Integration('calendar','Google Calendar',set(o.name for o in calendar_manifest().operations),lambda:bool(a.list_events(maxResults=1) is not None),calendar_manifest(),True))
    if google_token:
        a=GoogleDriveWriteAdapter(google_token,gateway=gateway,granted_scopes=google_scopes); adapters['drive']=a; reg.register(Integration('drive','Google Drive',set(o.name for o in drive_manifest().operations),lambda:bool(a.list_files(page_size=1) is not None),drive_manifest(),True))
        s=GoogleSheetsWriteAdapter(google_token,gateway=gateway,granted_scopes=google_scopes); adapters['sheets']=s; reg.register(Integration('sheets','Google Sheets',set(o.name for o in sheets_manifest().operations),None,sheets_manifest(),True))
    slack_token=getattr(settings,'slack_token','')
    if oauth and 'slack' in providers:
        try:slack_token=oauth.token(providers['slack'])
        except Exception:pass
    if slack_token:
        a=SlackAdapter(slack_token,gateway=gateway); adapters['slack']=a; reg.register(Integration('slack','Slack',set(o.name for o in slack_manifest().operations),lambda:bool(a.auth_test()),slack_manifest(),True))
    if getattr(settings,'home_assistant_url','') and getattr(settings,'home_assistant_token',''):
        a=HomeAssistantAdapter(settings.home_assistant_url,settings.home_assistant_token,gateway=gateway); adapters['home_assistant']=a; reg.register(Integration('home_assistant','Home Assistant',set(o.name for o in home_assistant_manifest().operations),lambda:bool(a.states() is not None),home_assistant_manifest(),True))
    if google_scopes is not None:
        reg.sync_provider_scopes('google',google_scopes)
    for manifest in reg.manifests.list():
        configured=manifest.connector_id in adapters
        current=state.health(manifest.connector_id)
        if not configured and current['state']=='disconnected':state.set_health(manifest.connector_id,'not_configured')
    return reg,adapters,oauth,providers

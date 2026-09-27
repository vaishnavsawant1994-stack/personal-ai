from integrations.registry import IntegrationRegistry,Integration
from integrations.adapters import GmailAdapter,GoogleCalendarAdapter,SlackAdapter,HomeAssistantAdapter
from integrations.oauth import OAuthAccountManager,OAuthProvider
GOOGLE_AUTH='https://accounts.google.com/o/oauth2/v2/auth'; GOOGLE_TOKEN='https://oauth2.googleapis.com/token'; SLACK_AUTH='https://slack.com/oauth/v2/authorize'; SLACK_TOKEN='https://slack.com/api/oauth.v2.access'
def provider_catalog(settings):
    out={}
    if settings.google_client_id:
        out['google']=OAuthProvider('google',GOOGLE_AUTH,GOOGLE_TOKEN,settings.google_client_id,['openid','email','https://www.googleapis.com/auth/gmail.readonly','https://www.googleapis.com/auth/gmail.send','https://www.googleapis.com/auth/calendar'],settings.google_client_secret)
    if settings.slack_client_id:
        out['slack']=OAuthProvider('slack',SLACK_AUTH,SLACK_TOKEN,settings.slack_client_id,['channels:history','chat:write'],settings.slack_client_secret)
    return out
def build_integrations(settings,vault=None):
    reg=IntegrationRegistry(); adapters={}; oauth=OAuthAccountManager(vault) if vault else None; providers=provider_catalog(settings)
    google_token=None
    if oauth and 'google' in providers:
        try:google_token=oauth.token(providers['google'])
        except Exception:pass
    gmail_token=google_token or settings.gmail_token; calendar_token=google_token or settings.calendar_token
    if gmail_token:
        a=GmailAdapter(gmail_token); adapters['gmail']=a; reg.register(Integration('gmail','Gmail',{'read_mail','send_mail'},lambda:bool(a.list_messages(max_results=1) is not None)))
    if calendar_token:
        a=GoogleCalendarAdapter(calendar_token); adapters['calendar']=a; reg.register(Integration('calendar','Google Calendar',{'read_events','create_event','update_event','delete_event'},lambda:bool(a.list_events(maxResults=1) is not None)))
    slack_token=settings.slack_token
    if oauth and 'slack' in providers:
        try:slack_token=oauth.token(providers['slack'])
        except Exception:pass
    if slack_token:
        a=SlackAdapter(slack_token); adapters['slack']=a; reg.register(Integration('slack','Slack',{'read_messages','send_message'},lambda:bool(a.auth_test())))
    if settings.home_assistant_url and settings.home_assistant_token:
        a=HomeAssistantAdapter(settings.home_assistant_url,settings.home_assistant_token); adapters['home_assistant']=a; reg.register(Integration('home_assistant','Home Assistant',{'read_state','call_service'},lambda:bool(a.states() is not None)))
    return reg,adapters,oauth,providers

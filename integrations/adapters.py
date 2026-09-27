from __future__ import annotations
import requests
class IntegrationError(RuntimeError):pass
class BearerREST:
    def __init__(self,base_url,token,timeout=30):self.base_url=base_url.rstrip('/'); self.token=token; self.timeout=timeout
    def set_token(self,token):self.token=token
    def request(self,method,path,**kwargs):
        h={'Authorization':f'Bearer {self.token}','Accept':'application/json',**kwargs.pop('headers',{})}; r=requests.request(method,f'{self.base_url}/{path.lstrip("/")}',headers=h,timeout=self.timeout,**kwargs)
        if r.status_code>=400:raise IntegrationError(f'{r.status_code}: {r.text[:500]}')
        return r.json() if r.content else None
class GmailAdapter(BearerREST):
    def __init__(self,token):super().__init__('https://gmail.googleapis.com/gmail/v1',token)
    def list_messages(self,q='',max_results=20):return self.request('GET','users/me/messages',params={'q':q,'maxResults':max_results})
    def get_message(self,message_id,format='metadata'):return self.request('GET',f'users/me/messages/{message_id}',params={'format':format})
    def send_raw(self,raw_base64url):return self.request('POST','users/me/messages/send',json={'raw':raw_base64url})
class GoogleCalendarAdapter(BearerREST):
    def __init__(self,token):super().__init__('https://www.googleapis.com/calendar/v3',token)
    def list_events(self,calendar_id='primary',**params):return self.request('GET',f'calendars/{calendar_id}/events',params=params)
    def create_event(self,event,calendar_id='primary'):return self.request('POST',f'calendars/{calendar_id}/events',json=event)
    def update_event(self,event_id,event,calendar_id='primary'):return self.request('PATCH',f'calendars/{calendar_id}/events/{event_id}',json=event)
    def delete_event(self,event_id,calendar_id='primary'):return self.request('DELETE',f'calendars/{calendar_id}/events/{event_id}')
class SlackAdapter(BearerREST):
    def __init__(self,token):super().__init__('https://slack.com/api',token)
    def _ok(self,data):
        if not data.get('ok'):raise IntegrationError(str(data.get('error','slack error')))
        return data
    def auth_test(self):return self._ok(self.request('POST','auth.test'))
    def history(self,channel,limit=50):return self._ok(self.request('GET','conversations.history',params={'channel':channel,'limit':limit}))
    def post_message(self,channel,text):return self._ok(self.request('POST','chat.postMessage',json={'channel':channel,'text':text}))
class HomeAssistantAdapter(BearerREST):
    def __init__(self,base_url,token):super().__init__(f'{base_url.rstrip("/")}/api',token)
    def states(self):return self.request('GET','states')
    def state(self,entity_id):return self.request('GET',f'states/{entity_id}')
    def call_service(self,domain,service,data):return self.request('POST',f'services/{domain}/{service}',json=data)

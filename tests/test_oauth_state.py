from integrations.oauth import OAuthAccountManager,OAuthProvider
class V:
    def __init__(self):self.d={}
    def set(self,k,v):self.d[k]=v
    def get(self,k,d=None):return self.d.get(k,d)
    def delete(self,k):self.d.pop(k,None)
def test_oauth_begin_has_pkce_and_state():
    m=OAuthAccountManager(V());p=OAuthProvider('x','https://a','https://t','cid',['one']);o=m.begin(p);assert o['state'] in m._pending;assert 'code_challenge=' in o['url'];assert 'state=' in o['url']

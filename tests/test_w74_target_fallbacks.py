import pytest

from browser.safe_operator import BrowserAction, SafeBrowserOperator


class Locator:
    def __init__(self,count=1): self._count=count
    def count(self): return self._count


class Mouse:
    def __init__(self): self.clicked=None
    def click(self,x,y): self.clicked=(x,y)


class Page:
    def __init__(self,dom_count=1,a11y_count=0): self.dom_count=dom_count; self.a11y_count=a11y_count; self.mouse=Mouse()
    def locator(self,path): return Locator(self.dom_count)
    def get_by_role(self,role,name=None,exact=None): return Locator(self.a11y_count)


def target(**overrides):
    value={'target_id':'t1','path':'button:nth-of-type(1)','role':'button','label':'Continue','text':'Continue','type':'button','name':'','placeholder':'','actionable':True,'sensitive':False,'visible':True,'topmost':True,'geometry_digest':'g1','box':{'x':10,'y':20,'width':40,'height':20}}
    value.update(overrides); return value


def op(): return object.__new__(SafeBrowserOperator)


def test_dom_locator_is_first_priority():
    mode,handle=op()._resolve_target(Page(dom_count=1,a11y_count=1),target(),BrowserAction('click','tx',target_id='t1'))
    assert mode=='dom'


def test_accessibility_locator_is_second_priority_when_dom_unavailable():
    mode,handle=op()._resolve_target(Page(dom_count=0,a11y_count=1),target(path=''),BrowserAction('click','tx',target_id='t1'))
    assert mode=='accessibility'


def test_coordinate_fallback_requires_explicit_visual_binding():
    page=Page(dom_count=0,a11y_count=0); t=target(path='')
    with pytest.raises(PermissionError):
        op()._resolve_target(page,t,BrowserAction('click','tx',target_id='t1',parameters={'allow_coordinate_fallback':True}))


def test_verified_coordinate_fallback_is_click_only_and_uses_target_center():
    page=Page(dom_count=0,a11y_count=0); t=target(path='')
    action=BrowserAction('click','tx',target_id='t1',parameters={'allow_coordinate_fallback':True,'verified_visual_target_id':'t1'})
    mode,point=op()._resolve_target(page,t,action)
    assert mode=='coordinate' and point==(30.0,30.0)


def test_coordinate_fallback_refuses_hidden_or_covered_target():
    action=BrowserAction('click','tx',target_id='t1',parameters={'allow_coordinate_fallback':True,'verified_visual_target_id':'t1'})
    for bad in (target(path='',visible=False),target(path='',topmost=False),target(path='',actionable=False)):
        with pytest.raises(PermissionError): op()._resolve_target(Page(0,0),bad,action)


def test_coordinate_fallback_cannot_be_enabled_for_typing():
    with pytest.raises(ValueError):
        op()._validate(BrowserAction('type','tx',target_id='t1',value='x',parameters={'allow_coordinate_fallback':True,'verified_visual_target_id':'t1'}))


def test_coordinate_fallback_parameters_are_approval_digest_bound_not_raw_visual_content():
    params=op()._safe_params(BrowserAction('click','tx',target_id='t1',parameters={'allow_coordinate_fallback':True,'verified_visual_target_id':'t1'}))
    assert params['coordinate_fallback_requested'] is True
    assert params['visual_target_digest'] and params['visual_target_digest']!='t1'

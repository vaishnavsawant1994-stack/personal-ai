from __future__ import annotations
import time,uuid
from dataclasses import dataclass,field
@dataclass
class DesktopAction:
    kind:str; params:dict; undo:dict|None=None; verified:bool=False
@dataclass
class DesktopTransaction:
    id:str=field(default_factory=lambda:str(uuid.uuid4())); actions:list[DesktopAction]=field(default_factory=list); committed:bool=False; created_at:float=field(default_factory=time.time)
class DesktopTransactionManager:
    def __init__(self,controller):self.controller=controller; self.active={}
    def begin(self):
        tx=DesktopTransaction(); self.active[tx.id]=tx; return tx
    def execute(self,tx:DesktopTransaction,kind:str,**params):
        before=self.controller.snapshot(); result=getattr(self.controller,kind)(**params); after=self.controller.snapshot(); action=DesktopAction(kind,params,self.controller.undo_descriptor(kind,before,params),self.controller.verify_change(before,after,kind)); tx.actions.append(action); return {'result':result,'verified':action.verified,'tx_id':tx.id}
    def rollback(self,tx:DesktopTransaction):
        results=[]
        for action in reversed(tx.actions):
            if action.undo:results.append(self.controller.apply_undo(action.undo))
        self.active.pop(tx.id,None); return results
    def commit(self,tx:DesktopTransaction):tx.committed=True; self.active.pop(tx.id,None); return {'committed':True,'tx_id':tx.id}

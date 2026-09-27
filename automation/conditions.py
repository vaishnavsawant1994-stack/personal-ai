from __future__ import annotations
import operator
OPS={'eq':operator.eq,'ne':operator.ne,'gt':operator.gt,'gte':operator.ge,'lt':operator.lt,'lte':operator.le,'contains':lambda a,b:b in a,'truthy':lambda a,_:bool(a)}
def resolve_path(obj,path):
    cur=obj
    for part in path.split('.'):
        if isinstance(cur,dict): cur=cur.get(part)
        else: cur=getattr(cur,part,None)
    return cur
def evaluate_condition(condition:dict,context:dict)->bool:
    if not condition:return True
    if 'all' in condition:return all(evaluate_condition(x,context) for x in condition['all'])
    if 'any' in condition:return any(evaluate_condition(x,context) for x in condition['any'])
    op=condition.get('op','eq'); fn=OPS.get(op)
    if not fn: raise ValueError(f'unsupported condition op: {op}')
    return bool(fn(resolve_path(context,condition['path']),condition.get('value')))

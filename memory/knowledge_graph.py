from __future__ import annotations
from collections import defaultdict, deque
class KnowledgeGraph:
    def __init__(self,store): self.store=store
    def neighbors(self,memory_id:str,direction='both'):
        g=self.store.graph(); out=[]
        for e in g.get('edges',[]):
            if direction in ('out','both') and e['source_id']==memory_id: out.append({'direction':'out',**e})
            if direction in ('in','both') and e['target_id']==memory_id: out.append({'direction':'in',**e})
        return out
    def subgraph(self,seed_ids:list[str],depth:int=2):
        g=self.store.graph(); nodes={n['id']:n for n in g.get('nodes',[])}; adj=defaultdict(list)
        for e in g.get('edges',[]): adj[e['source_id']].append((e['target_id'],e)); adj[e['target_id']].append((e['source_id'],e))
        seen=set(seed_ids); q=deque((x,0) for x in seed_ids); edges={}
        while q:
            node,d=q.popleft()
            if d>=depth: continue
            for nxt,e in adj[node]:
                edges[e['id']]=e
                if nxt not in seen: seen.add(nxt); q.append((nxt,d+1))
        return {'nodes':[nodes[x] for x in seen if x in nodes],'edges':list(edges.values())}

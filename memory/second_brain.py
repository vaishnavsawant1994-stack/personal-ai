from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math

from memory.knowledge_graph import KnowledgeGraph


@dataclass
class MemoryCandidate:
    type: str
    subject: str
    content: str
    confidence: float
    source: str = 'conversation'
    verified: bool = False
    tags: list[str] | None = None
    importance: float = 0.5
    sensitivity: str = 'normal'
    occurred_at: str | None = None
    evidence: list | None = None
    metadata: dict | None = None
    relationships: list[dict] | None = None


class SecondBrain:
    VOLATILE_TYPES = {'preference', 'fact', 'status', 'goal'}
    HALF_LIFE_DAYS = {
        'event': 120.0,
        'conversation': 90.0,
        'note': 180.0,
        'status': 45.0,
        'project': 365.0,
        'goal': 365.0,
        'fact': 730.0,
        'preference': 1095.0,
        'person': 1825.0,
    }

    def __init__(self, store, models=None, vector_store=None):
        self.store = store
        self.models = models
        self.vector_store = vector_store
        self.kg = KnowledgeGraph(store)

    @staticmethod
    def _bounded(value, default=0.5):
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return float(default)

    def remember(self, candidate: MemoryCandidate) -> str:
        exact = self.store.search(candidate.content[:120], limit=10)
        for row in exact:
            if row['content'].strip().lower() == candidate.content.strip().lower():
                self.store.update_memory(
                    row['id'],
                    confidence=max(float(row.get('confidence') or 0), self._bounded(candidate.confidence)),
                    importance=max(float(row.get('importance') or 0.5), self._bounded(candidate.importance)),
                    verified=bool(row.get('verified')) or bool(candidate.verified),
                )
                return row['id']

        prior = self.store.active_subject(candidate.type, candidate.subject, limit=20)
        memory_id = self.store.remember(
            type=candidate.type,
            subject=candidate.subject,
            content=candidate.content,
            source=candidate.source,
            confidence=self._bounded(candidate.confidence),
            verified=candidate.verified,
            tags=candidate.tags or [],
            importance=self._bounded(candidate.importance),
            sensitivity=candidate.sensitivity,
            occurred_at=candidate.occurred_at,
            evidence=candidate.evidence or [],
            metadata=candidate.metadata or {},
        )

        for older in prior:
            if older['content'].strip().lower() == candidate.content.strip().lower():
                continue
            old_confidence = float(older.get('confidence') or 0.0)
            newer_supported = candidate.source in {'user', 'user-message', 'explicit-user'} and candidate.confidence + 0.05 >= old_confidence
            if candidate.type.lower() in self.VOLATILE_TYPES and newer_supported:
                self.store.supersede(
                    older['id'],
                    memory_id,
                    reason='newer explicit user-supported memory supersedes earlier active value',
                )
            else:
                self.store.conflict(
                    older['id'],
                    memory_id,
                    resolution='unresolved',
                    reason='same memory subject has materially different supported content',
                )

        for relation in candidate.relationships or []:
            try:
                target_id = str(relation['target_id'])
                relation_name = str(relation.get('relation', 'related_to'))
                if self.store.get(target_id):
                    self.store.relate(memory_id, relation_name, target_id)
            except Exception:
                pass

        if self.vector_store:
            try:
                self.vector_store.upsert(memory_id, f'{candidate.subject}\n{candidate.content}')
            except Exception:
                pass
        return memory_id

    @staticmethod
    def _age_days(row: dict):
        raw = row.get('last_used_at') or row.get('occurred_at') or row.get('created_at')
        if not raw:
            return 0.0
        try:
            dt = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 86400.0)
        except Exception:
            return 0.0

    def salience(self, row: dict, semantic_score: float | None = None):
        memory_type = str(row.get('type', 'note')).lower()
        half_life = self.HALF_LIFE_DAYS.get(memory_type, 240.0)
        decay = math.pow(0.5, self._age_days(row) / max(1.0, half_life))
        importance = self._bounded(row.get('importance'), 0.5)
        confidence = self._bounded(row.get('confidence'), 0.5)
        verified = 1.0 if row.get('verified') else 0.0
        use_count = max(0, int(row.get('use_count') or 0))
        usage = min(1.0, math.log1p(use_count) / math.log(12.0))
        semantic = self._bounded(semantic_score, 0.35 if semantic_score is None else semantic_score)
        score = (
            semantic * 0.32
            + importance * 0.25
            + confidence * 0.18
            + verified * 0.08
            + usage * 0.07
            + decay * 0.10
        )
        if row.get('valid_to'):
            score *= 0.28
        return max(0.0, min(1.0, score)), decay

    def context(self, query: str, limit: int = 8) -> list[dict]:
        combined = {}
        if self.vector_store:
            try:
                graph_nodes = {node['id']: node for node in self.store.graph().get('nodes', [])}
                for hit in self.vector_store.search(query, limit=max(limit * 3, 12)):
                    if hit['memory_id'] in graph_nodes:
                        combined[hit['memory_id']] = {
                            **graph_nodes[hit['memory_id']],
                            'semantic_score': hit['score'],
                        }
            except Exception:
                pass
        for row in self.store.search(query, limit=max(limit * 3, 12), active_only=False):
            combined.setdefault(row['id'], row)
        if not combined:
            for word in [word for word in query.split() if len(word) > 3][:6]:
                for row in self.store.search(word, limit=max(limit * 2, 8), active_only=False):
                    combined.setdefault(row['id'], row)

        ranked = []
        for row in combined.values():
            score, decay = self.salience(row, row.get('semantic_score'))
            ranked.append(
                {
                    **row,
                    'salience_score': round(score, 6),
                    'decay_factor': round(decay, 6),
                    'memory_state': 'historical' if row.get('valid_to') else 'active',
                }
            )
        ranked.sort(key=lambda item: (item['salience_score'], item.get('updated_at') or ''), reverse=True)
        selected = ranked[: max(1, int(limit))]
        for row in selected:
            try:
                self.store.record_usage(row['id'], query=query, score=row['salience_score'])
            except Exception:
                pass
        return selected

    def temporal(self, query: str = '', *, start=None, end=None, memory_type=None, limit=50):
        rows = self.store.temporal_search(query, start=start, end=end, memory_type=memory_type, limit=limit)
        result = []
        for row in rows:
            score, decay = self.salience(row)
            result.append({**row, 'salience_score': round(score, 6), 'decay_factor': round(decay, 6)})
        return result

    def graph(self):
        return self.store.graph()

    def related(self, memory_id, depth=2):
        return self.kg.subgraph([memory_id], depth)

    def memory_detail(self, memory_id: str):
        row = self.store.get(memory_id)
        if not row:
            return None
        score, decay = self.salience(row)
        return {
            **row,
            'salience_score': round(score, 6),
            'decay_factor': round(decay, 6),
            'usage_history': self.store.usage(memory_id, 100),
            'relationships': self.related(memory_id, depth=1),
            'conflicts': [
                item
                for item in self.store.conflicts(500)
                if item['older_id'] == memory_id or item['newer_id'] == memory_id
            ],
        }

    def extract_candidates(self, user_text: str, assistant_text: str | None = None):
        if not self.models:
            return []
        prompt = f'''Extract only durable user facts, preferences, people, projects, goals, decisions or events explicitly supported by USER TEXT. Never treat assistant claims as user facts. Return JSON exactly like:\n{{"memories":[{{"type":"fact|preference|project|person|goal|decision|event|note","subject":"...","content":"...","confidence":0.0,"importance":0.0,"sensitivity":"normal|sensitive","occurred_at":null,"evidence":[],"tags":[]}}]}}\nUSER TEXT:\n{user_text}'''
        try:
            data = self.models.json(prompt, system='Return conservative memory candidates as JSON only. Do not infer unsupported personal facts.')
        except Exception:
            return []
        output = []
        for item in data.get('memories', []):
            try:
                candidate = MemoryCandidate(
                    type=str(item.get('type', 'note')),
                    subject=str(item.get('subject', '')).strip(),
                    content=str(item.get('content', '')).strip(),
                    confidence=self._bounded(item.get('confidence'), 0.5),
                    source='user-message',
                    verified=False,
                    tags=list(item.get('tags') or []),
                    importance=self._bounded(item.get('importance'), 0.5),
                    sensitivity=str(item.get('sensitivity', 'normal')),
                    occurred_at=item.get('occurred_at'),
                    evidence=list(item.get('evidence') or []),
                    metadata={},
                )
                if candidate.subject and candidate.content:
                    output.append(candidate)
            except Exception:
                pass
        return output

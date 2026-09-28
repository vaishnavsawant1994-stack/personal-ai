from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math

from memory.knowledge_graph import KnowledgeGraph
from memory.policy import is_never_store, require_storable


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
    RANK_WEIGHTS = {
        'semantic': 0.30,
        'importance': 0.23,
        'confidence': 0.17,
        'verified': 0.07,
        'usage': 0.06,
        'recency': 0.10,
        'relationship': 0.07,
    }
    HISTORICAL_MULTIPLIER = 0.28
    DEFAULT_ALLOWED_SENSITIVITIES = frozenset({'normal'})

    def __init__(self, store, models=None, vector_store=None):
        self.store = store
        self.models = models
        self.vector_store = vector_store
        self.kg = KnowledgeGraph(store)
        try:
            store.second_brain = self
        except Exception:
            pass

    @staticmethod
    def _bounded(value, default=0.5):
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _json_list(value):
        if isinstance(value, list):
            return value
        if not value:
            return []
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    @staticmethod
    def _iso_now():
        return datetime.now(timezone.utc).isoformat()

    @classmethod
    def _allowed(cls, allowed_sensitivities):
        if allowed_sensitivities is None:
            return set(cls.DEFAULT_ALLOWED_SENSITIVITIES)
        return {str(item).strip().lower() for item in allowed_sensitivities if str(item).strip()}

    def remember(self, candidate: MemoryCandidate) -> str:
        require_storable(sensitivity=candidate.sensitivity, metadata=candidate.metadata)
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
            newer_supported = candidate.source in {'user', 'user-message', 'explicit-user', 'explicit-owner'} and candidate.confidence + 0.05 >= old_confidence
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

    @staticmethod
    def _source_age_days(row: dict):
        raw = row.get('occurred_at') or row.get('created_at')
        if not raw:
            return 0.0
        try:
            dt = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 86400.0)
        except Exception:
            return 0.0

    def salience(self, row: dict, semantic_score: float | None = None, relationship_score: float | None = None):
        memory_type = str(row.get('type', 'note')).lower()
        half_life = self.HALF_LIFE_DAYS.get(memory_type, 240.0)
        decay = math.pow(0.5, self._age_days(row) / max(1.0, half_life))
        importance = self._bounded(row.get('importance'), 0.5)
        confidence = self._bounded(row.get('confidence'), 0.5)
        verified = 1.0 if row.get('verified') else 0.0
        use_count = max(0, int(row.get('use_count') or 0))
        usage = min(1.0, math.log1p(use_count) / math.log(12.0))
        semantic = self._bounded(semantic_score, 0.35 if semantic_score is None else semantic_score)
        relationship = self._bounded(relationship_score, 0.0)
        contributions = {
            'semantic': semantic * self.RANK_WEIGHTS['semantic'],
            'importance': importance * self.RANK_WEIGHTS['importance'],
            'confidence': confidence * self.RANK_WEIGHTS['confidence'],
            'verified': verified * self.RANK_WEIGHTS['verified'],
            'usage': usage * self.RANK_WEIGHTS['usage'],
            'recency': decay * self.RANK_WEIGHTS['recency'],
            'relationship': relationship * self.RANK_WEIGHTS['relationship'],
        }
        score = sum(contributions.values())
        multiplier = self.HISTORICAL_MULTIPLIER if row.get('valid_to') else 1.0
        score *= multiplier
        return max(0.0, min(1.0, score)), decay, contributions, multiplier

    def _visible_graph(self, allowed_sensitivities):
        allowed = self._allowed(allowed_sensitivities)
        graph = self.store.graph()
        nodes = {
            str(node['id']): node
            for node in graph.get('nodes', [])
            if str(node.get('sensitivity') or 'normal').strip().lower() in allowed
            and str(node.get('sensitivity') or 'normal').strip().lower() != 'never_store'
        }
        edges = [
            edge for edge in graph.get('edges', [])
            if str(edge.get('source_id')) in nodes and str(edge.get('target_id')) in nodes
        ]
        return nodes, edges

    def _relationship_context(self, combined: dict, *, allowed_sensitivities, max_related: int):
        if not combined or max_related <= 0:
            return
        nodes, edges = self._visible_graph(allowed_sensitivities)
        adjacency: dict[str, set[str]] = {}
        for edge in edges:
            source_id = str(edge.get('source_id') or '')
            target_id = str(edge.get('target_id') or '')
            adjacency.setdefault(source_id, set()).add(target_id)
            adjacency.setdefault(target_id, set()).add(source_id)
        seeds = list(combined)
        added = 0
        for seed_id in seeds:
            for related_id in sorted(adjacency.get(str(seed_id), set())):
                if related_id in combined or related_id not in nodes:
                    continue
                combined[related_id] = {**nodes[related_id], 'relationship_score': 0.35, 'retrieval_mode': 'relationship'}
                added += 1
                if added >= max_related:
                    return

    def _explanation_maps(self, allowed_sensitivities):
        nodes, edges = self._visible_graph(allowed_sensitivities)
        relationship_counts: dict[str, int] = {}
        for edge in edges:
            for key in ('source_id', 'target_id'):
                memory_id = str(edge.get(key) or '')
                if memory_id in nodes:
                    relationship_counts[memory_id] = relationship_counts.get(memory_id, 0) + 1
        conflict_map: dict[str, list[dict]] = {}
        try:
            conflicts = self.store.conflicts(1000)
        except Exception:
            conflicts = []
        for conflict in conflicts:
            for key in ('older_id', 'newer_id'):
                memory_id = str(conflict.get(key) or '')
                if memory_id in nodes:
                    conflict_map.setdefault(memory_id, []).append(conflict)
        return relationship_counts, conflict_map

    def _retrieval_explanation(
        self,
        row: dict,
        *,
        query: str,
        salience_score: float,
        decay: float,
        contributions: dict,
        historical_multiplier: float,
        relationship_count: int,
        conflicts: list[dict],
        used_at: str | None,
    ):
        semantic_score = row.get('semantic_score')
        state = 'historical' if row.get('valid_to') else 'active'
        truth_state = 'SUPERSEDED' if row.get('superseded_by') else ('HISTORICAL' if row.get('valid_to') else 'CURRENT')
        contradiction_state = 'none'
        if row.get('superseded_by'):
            contradiction_state = 'superseded'
        elif any(str(item.get('resolution', '')).lower() == 'unresolved' for item in conflicts):
            contradiction_state = 'unresolved_conflict'
        elif conflicts:
            contradiction_state = str(conflicts[0].get('resolution') or 'resolved')

        reasons = []
        mode = str(row.get('retrieval_mode') or ('semantic' if semantic_score is not None else 'lexical'))
        if semantic_score is not None:
            reasons.append(f"semantic match {float(semantic_score):.3f}")
        elif mode == 'relationship':
            reasons.append('relationship-expanded context')
        else:
            reasons.append('lexical/subject match')
        reasons.append(f"relevance {float(salience_score):.3f}")
        if row.get('verified'):
            reasons.append('owner-verified')
        if state == 'historical':
            reasons.append('historical memory retained with reduced rank')
        age_days = round(self._source_age_days(row), 3)
        if age_days < 7:
            reasons.append('recent')
        elif age_days > 365:
            reasons.append('older memory with recency decay')
        if relationship_count:
            reasons.append(f'{relationship_count} visible graph relationship(s) available')
        if contradiction_state != 'none':
            reasons.append(f'contradiction state: {contradiction_state}')

        return {
            'retrieved': True,
            'memory_id': row.get('id'),
            'subject': row.get('subject'),
            'type': row.get('type'),
            'source': row.get('source'),
            'source_timestamp': row.get('occurred_at') or row.get('created_at'),
            'confidence': float(row.get('confidence') or 0.0),
            'verified': bool(row.get('verified')),
            'sensitivity': row.get('sensitivity') or 'normal',
            'age_days': age_days,
            'recency_decay': round(float(decay), 6),
            'semantic_score': round(float(semantic_score), 6) if semantic_score is not None else None,
            'relevance_score': round(float(salience_score), 6),
            'salience_score': round(float(salience_score), 6),
            'importance_contribution': round(float(contributions.get('importance', 0.0)), 6),
            'recency_contribution': round(float(contributions.get('recency', 0.0)), 6),
            'relationship_count': int(relationship_count),
            'relationship_contribution': round(float(contributions.get('relationship', 0.0)), 6),
            'historical_multiplier': round(float(historical_multiplier), 6),
            'retrieval_mode': mode,
            'memory_state': state,
            'truth_state': truth_state,
            'contradiction_state': contradiction_state,
            'superseded_by': row.get('superseded_by'),
            'selection_reason': '; '.join(reasons),
            'retrieval_query': query,
            'used_at': used_at,
            'evidence_references': self._json_list(row.get('evidence_json')),
        }

    def context(
        self,
        query: str,
        limit: int = 8,
        *,
        allowed_sensitivities: set[str] | None = None,
        current_only: bool = False,
        include_related: bool = True,
        max_context_chars: int | None = None,
    ) -> list[dict]:
        query = str(query or '').strip()
        bounded_limit = max(1, min(int(limit), 500))
        allowed = self._allowed(allowed_sensitivities)
        combined = {}
        if self.vector_store and query:
            try:
                graph_nodes, _ = self._visible_graph(allowed)
                for hit in self.vector_store.search(query, limit=max(bounded_limit * 3, 12)):
                    if hit['memory_id'] in graph_nodes:
                        combined[hit['memory_id']] = {
                            **graph_nodes[hit['memory_id']],
                            'semantic_score': hit['score'],
                            'retrieval_mode': 'semantic',
                        }
            except Exception:
                pass
        for row in self.store.search(query, limit=max(bounded_limit * 3, 12), active_only=False):
            sensitivity = str(row.get('sensitivity') or 'normal').strip().lower()
            if sensitivity not in allowed or sensitivity == 'never_store':
                continue
            combined.setdefault(row['id'], {**row, 'retrieval_mode': 'lexical'})
        if not combined and query:
            for word in [word for word in query.split() if len(word) > 3][:6]:
                for row in self.store.search(word, limit=max(bounded_limit * 2, 8), active_only=False):
                    sensitivity = str(row.get('sensitivity') or 'normal').strip().lower()
                    if sensitivity not in allowed or sensitivity == 'never_store':
                        continue
                    combined.setdefault(row['id'], {**row, 'retrieval_mode': 'lexical-fallback'})

        if include_related:
            self._relationship_context(combined, allowed_sensitivities=allowed, max_related=max(bounded_limit * 2, 8))

        ranked = []
        for row in combined.values():
            sensitivity = str(row.get('sensitivity') or 'normal').lower()
            if sensitivity == 'never_store' or sensitivity not in allowed:
                continue
            if current_only and row.get('valid_to'):
                continue
            score, decay, contributions, multiplier = self.salience(row, row.get('semantic_score'), row.get('relationship_score'))
            ranked.append({
                **row,
                'salience_score': round(score, 6),
                'decay_factor': round(decay, 6),
                'memory_state': 'historical' if row.get('valid_to') else 'active',
                'truth_state': 'SUPERSEDED' if row.get('superseded_by') else ('HISTORICAL' if row.get('valid_to') else 'CURRENT'),
                '_rank_contributions': contributions,
                '_historical_multiplier': multiplier,
            })
        ranked.sort(key=lambda item: (0 if item.get('valid_to') else 1, item['salience_score'], item.get('updated_at') or ''), reverse=True)

        selected = []
        used_chars = 0
        char_budget = None if max_context_chars is None else max(256, min(int(max_context_chars), 1_000_000))
        for row in ranked:
            estimated_chars = len(str(row.get('subject') or '')) + len(str(row.get('content') or ''))
            if char_budget is not None and selected and used_chars + estimated_chars > char_budget:
                continue
            selected.append(row)
            used_chars += estimated_chars
            if len(selected) >= bounded_limit:
                break

        relationship_counts, conflict_map = self._explanation_maps(allowed)
        for row in selected:
            used_at = None
            try:
                usage_id = self.store.record_usage(row['id'], query=query, score=row['salience_score'])
                if usage_id:
                    usage = self.store.usage(row['id'], 1)
                    used_at = usage[0].get('used_at') if usage else self._iso_now()
            except Exception:
                pass
            contributions = row.pop('_rank_contributions', {})
            historical_multiplier = row.pop('_historical_multiplier', 1.0)
            row['retrieval_explanation'] = self._retrieval_explanation(
                row,
                query=query,
                salience_score=row['salience_score'],
                decay=row['decay_factor'],
                contributions=contributions,
                historical_multiplier=historical_multiplier,
                relationship_count=relationship_counts.get(str(row['id']), 0),
                conflicts=conflict_map.get(str(row['id']), []),
                used_at=used_at,
            )
        return selected

    def current_truth(self, query: str, limit: int = 8, *, allowed_sensitivities: set[str] | None = None, max_context_chars: int | None = None):
        return self.context(query, limit, allowed_sensitivities=allowed_sensitivities, current_only=True, max_context_chars=max_context_chars)

    def explain_retrieval(
        self,
        memory_id: str,
        query: str,
        *,
        allowed_sensitivities: set[str] | None = None,
        candidate_limit: int = 100,
        current_only: bool = False,
    ):
        for row in self.context(query, max(1, min(int(candidate_limit), 500)), allowed_sensitivities=allowed_sensitivities, current_only=current_only):
            if row.get('id') == memory_id:
                return row.get('retrieval_explanation')
        return None

    def temporal(
        self,
        query: str = '',
        *,
        start=None,
        end=None,
        memory_type=None,
        limit=50,
        allowed_sensitivities: set[str] | None = None,
    ):
        allowed = self._allowed(allowed_sensitivities)
        rows = self.store.temporal_search(query, start=start, end=end, memory_type=memory_type, limit=limit)
        result = []
        for row in rows:
            sensitivity = str(row.get('sensitivity') or 'normal').strip().lower()
            if sensitivity not in allowed or sensitivity == 'never_store':
                continue
            score, decay, _, _ = self.salience(row)
            result.append({
                **row,
                'salience_score': round(score, 6),
                'decay_factor': round(decay, 6),
                'memory_state': 'historical' if row.get('valid_to') else 'active',
                'truth_state': 'SUPERSEDED' if row.get('superseded_by') else ('HISTORICAL' if row.get('valid_to') else 'CURRENT'),
                'contradiction_state': 'superseded' if row.get('superseded_by') else 'none',
            })
        return result

    def context_at(
        self,
        query: str,
        at: str,
        *,
        memory_type=None,
        limit=50,
        allowed_sensitivities: set[str] | None = None,
    ):
        at_dt = datetime.fromisoformat(str(at).replace('Z', '+00:00'))
        if at_dt.tzinfo is None:
            at_dt = at_dt.replace(tzinfo=timezone.utc)
        at_iso = at_dt.astimezone(timezone.utc).isoformat()
        rows = self.temporal(query, end=at_iso, memory_type=memory_type, limit=max(limit * 4, 50), allowed_sensitivities=allowed_sensitivities)
        visible = []
        for row in rows:
            valid_from = row.get('valid_from') or row.get('occurred_at') or row.get('created_at')
            valid_to = row.get('valid_to')
            if valid_from and str(valid_from) > at_iso:
                continue
            if valid_to and str(valid_to) <= at_iso:
                continue
            visible.append({**row, 'memory_state': 'current_at_time'})
        return visible[: max(1, min(int(limit), 500))]

    def graph(self):
        return self.store.graph()

    def related(self, memory_id, depth=2):
        return self.kg.subgraph([memory_id], depth)

    def memory_detail(self, memory_id: str):
        row = self.store.get(memory_id)
        if not row:
            return None
        score, decay, _, _ = self.salience(row)
        return {
            **row,
            'salience_score': round(score, 6),
            'decay_factor': round(decay, 6),
            'usage_history': self.store.usage(memory_id, 100),
            'relationships': self.related(memory_id, depth=1),
            'conflicts': [item for item in self.store.conflicts(500) if item['older_id'] == memory_id or item['newer_id'] == memory_id],
        }

    def delete(self, memory_id: str):
        deleted = self.store.delete_memory(memory_id)
        if deleted and self.vector_store:
            try:
                self.vector_store.delete(memory_id)
            except Exception:
                pass
        return deleted

    def apply_retention(self, *, older_than_days: int, sensitivity: str | None = None, dry_run: bool = True):
        result = self.store.apply_retention(older_than_days=older_than_days, sensitivity=sensitivity, dry_run=True)
        if not dry_run:
            for memory_id in result['memory_ids']:
                self.delete(memory_id)
            result['dry_run'] = False
        return result

    def extract_candidates(self, user_text: str, assistant_text: str | None = None):
        if not self.models:
            return []
        prompt = f'''Extract only durable user facts, preferences, people, projects, goals, decisions or events explicitly supported by USER TEXT. Never treat assistant claims as user facts. If the owner says not to remember, retain, or store something, classify it as never_store. Return JSON exactly like:\n{{"memories":[{{"type":"fact|preference|project|person|goal|decision|event|note","subject":"...","content":"...","confidence":0.0,"importance":0.0,"sensitivity":"normal|sensitive|secret|never_store","occurred_at":null,"evidence":[],"tags":[]}}]}}\nUSER TEXT:\n{user_text}'''
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
                if candidate.subject and candidate.content and not is_never_store(sensitivity=candidate.sensitivity, metadata=candidate.metadata):
                    output.append(candidate)
            except Exception:
                pass
        return output

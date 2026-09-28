from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Iterable


def _iso_sort_value(value):
    if not value:
        return ''
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return str(value)


class SecondBrainLifeGraph:
    """Read-through P5 bridge between authoritative Second Brain memory and Life Graph.

    Memory remains authoritative in ``SecondBrain``. The bridge deliberately does not
    copy memory content into the Life Graph database, which keeps deletion, retention
    and supersession semantics owned by the existing memory architecture.
    """

    DIRECT_TYPES = {
        'person', 'project', 'decision', 'event', 'goal', 'place', 'conversation',
    }

    def __init__(self, life_graph, second_brain=None):
        self.life_graph = life_graph
        self.second_brain = second_brain

    @staticmethod
    def _decode_json(value, fallback):
        if isinstance(value, type(fallback)):
            return value
        if not value:
            return fallback
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return fallback
        return decoded if isinstance(decoded, type(fallback)) else fallback

    @staticmethod
    def _allowed(allowed_sensitivities: Iterable[str] | None):
        if allowed_sensitivities is None:
            return {'normal'}
        return {str(item).strip().lower() for item in allowed_sensitivities if str(item).strip()}

    def _memory_projection(self, *, allowed_sensitivities=None):
        if self.second_brain is None:
            return {'nodes': [], 'edges': []}

        allowed = self._allowed(allowed_sensitivities)
        source_graph = self.second_brain.graph()
        visible_rows = []
        for row in source_graph.get('nodes', []):
            sensitivity = str(row.get('sensitivity') or 'normal').strip().lower()
            if sensitivity == 'never_store' or sensitivity not in allowed:
                continue
            visible_rows.append(row)

        visible_ids = {str(row['id']) for row in visible_rows if row.get('id')}
        nodes = []
        for row in visible_rows:
            memory_id = str(row['id'])
            memory_type = str(row.get('type') or 'memory').strip().lower()
            projected_type = memory_type if memory_type in self.DIRECT_TYPES else 'memory'
            metadata = self._decode_json(row.get('metadata_json'), {})
            evidence = self._decode_json(row.get('evidence_json'), [])
            nodes.append({
                'id': f'memory:{memory_id}',
                'type': projected_type,
                'label': str(row.get('subject') or memory_type or 'Memory'),
                'summary': str(row.get('content') or ''),
                'occurred_at': row.get('occurred_at'),
                'source': str(row.get('source') or 'memory'),
                'confidence': float(row.get('confidence') or 0.0),
                'metadata_json': json.dumps({
                    'origin': 'second_brain',
                    'memory_id': memory_id,
                    'memory_type': memory_type,
                    'sensitivity': str(row.get('sensitivity') or 'normal'),
                    'verified': bool(row.get('verified')),
                    'importance': float(row.get('importance') or 0.5),
                    'memory_state': 'historical' if row.get('valid_to') else 'active',
                    'valid_from': row.get('valid_from'),
                    'valid_to': row.get('valid_to'),
                    'superseded_by': row.get('superseded_by'),
                    'evidence': evidence,
                    'metadata': metadata,
                }, default=str, sort_keys=True),
                'created_at': row.get('created_at'),
                'updated_at': row.get('updated_at') or row.get('created_at'),
                'origin': 'second_brain',
                'memory_id': memory_id,
            })

        edges = []
        for relation in source_graph.get('edges', []):
            source_id = str(relation.get('source_id') or '')
            target_id = str(relation.get('target_id') or '')
            if source_id not in visible_ids or target_id not in visible_ids:
                continue
            edges.append({
                'id': f"memory-relation:{relation.get('id')}",
                'src': f'memory:{source_id}',
                'dst': f'memory:{target_id}',
                'relation': str(relation.get('relation') or 'related_to'),
                'rationale': 'Second Brain relationship',
                'source': 'second_brain',
                'confidence': 1.0,
                'created_at': relation.get('created_at'),
                'origin': 'second_brain',
            })

        existing_edge_ids = {edge['id'] for edge in edges}
        for row in visible_rows:
            older_id = str(row.get('id') or '')
            newer_id = str(row.get('superseded_by') or '')
            if not newer_id or newer_id not in visible_ids:
                continue
            edge_id = f'memory-supersedes:{newer_id}:{older_id}'
            if edge_id in existing_edge_ids:
                continue
            edges.append({
                'id': edge_id,
                'src': f'memory:{newer_id}',
                'dst': f'memory:{older_id}',
                'relation': 'supersedes',
                'rationale': 'Authoritative Second Brain supersession',
                'source': 'second_brain',
                'confidence': 1.0,
                'created_at': row.get('valid_to') or row.get('updated_at'),
                'origin': 'second_brain',
            })
            existing_edge_ids.add(edge_id)

        return {'nodes': nodes, 'edges': edges}

    def graph(self, *, type=None, limit=500, allowed_sensitivities=None):
        bounded_limit = max(1, min(int(limit), 2000))
        base = self.life_graph.graph(type=type, limit=bounded_limit)
        projection = self._memory_projection(allowed_sensitivities=allowed_sensitivities)

        nodes = [dict(node, origin=node.get('origin', 'life_graph')) for node in base.get('nodes', [])]
        memory_nodes = projection['nodes']
        if type:
            requested = str(type).strip().lower()
            memory_nodes = [node for node in memory_nodes if str(node.get('type')).lower() == requested]
        nodes.extend(memory_nodes)
        nodes.sort(
            key=lambda node: _iso_sort_value(node.get('occurred_at') or node.get('updated_at') or node.get('created_at')),
            reverse=True,
        )
        nodes = nodes[:bounded_limit]
        visible_node_ids = {node['id'] for node in nodes}

        edges = [
            dict(edge, origin=edge.get('origin', 'life_graph'))
            for edge in base.get('edges', [])
            if edge.get('src') in visible_node_ids or edge.get('dst') in visible_node_ids
        ]
        edges.extend(
            edge for edge in projection['edges']
            if edge.get('src') in visible_node_ids and edge.get('dst') in visible_node_ids
        )
        return {'nodes': nodes, 'edges': edges, 'linked_second_brain': self.second_brain is not None}

    def timeline(self, *, limit=100, allowed_sensitivities=None):
        snapshot = self.graph(limit=limit, allowed_sensitivities=allowed_sensitivities)
        return {'items': snapshot['nodes'], 'linked_second_brain': snapshot['linked_second_brain']}

    def status(self):
        if self.second_brain is None:
            return {'linked': False, 'memory_nodes': 0}
        projection = self._memory_projection(allowed_sensitivities={'normal', 'sensitive', 'secret'})
        return {'linked': True, 'memory_nodes': len(projection['nodes'])}

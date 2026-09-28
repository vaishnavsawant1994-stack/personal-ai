from memory.second_brain import MemoryCandidate, SecondBrain
from memory.store import MemoryStore
from future_intelligence.deep_brain import LifeGraph
from future_intelligence.second_brain_graph import SecondBrainLifeGraph


def bridge(tmp_path):
    store = MemoryStore(tmp_path / 'memory.sqlite3')
    second_brain = SecondBrain(store)
    life_graph = LifeGraph(tmp_path / 'life.sqlite3')
    return SecondBrainLifeGraph(life_graph, second_brain), second_brain, store, life_graph


def test_bridge_projects_second_brain_without_copying_memory_database_state(tmp_path):
    linked, second_brain, _, life_graph = bridge(tmp_path)
    memory_id = second_brain.remember(
        MemoryCandidate(
            type='project',
            subject='Personal AI',
            content='Personal AI is the active owner project.',
            confidence=.95,
            source='explicit-user',
            verified=True,
        )
    )
    life_node = life_graph.node('goal', 'Ship reliable Personal AI', summary='Qualification before release')

    base = life_graph.graph()
    assert {node['id'] for node in base['nodes']} == {life_node}

    snapshot = linked.graph()
    by_id = {node['id']: node for node in snapshot['nodes']}
    assert life_node in by_id
    assert f'memory:{memory_id}' in by_id
    assert by_id[f'memory:{memory_id}']['type'] == 'project'
    assert by_id[f'memory:{memory_id}']['origin'] == 'second_brain'
    assert snapshot['linked_second_brain'] is True

    assert {node['id'] for node in life_graph.graph()['nodes']} == {life_node}


def test_bridge_fails_closed_for_sensitive_memory_and_maps_unmodeled_memory_types(tmp_path):
    linked, second_brain, _, _ = bridge(tmp_path)
    normal_id = second_brain.remember(
        MemoryCandidate(type='preference', subject='UI', content='Owner prefers calm dark UI.', confidence=.9)
    )
    secret_id = second_brain.remember(
        MemoryCandidate(
            type='fact',
            subject='Private',
            content='Confidential owner-only detail.',
            confidence=.9,
            sensitivity='secret',
        )
    )

    default_snapshot = linked.graph()
    default_ids = {node['id'] for node in default_snapshot['nodes']}
    assert f'memory:{normal_id}' in default_ids
    assert f'memory:{secret_id}' not in default_ids
    normal_node = next(node for node in default_snapshot['nodes'] if node['id'] == f'memory:{normal_id}')
    assert normal_node['type'] == 'memory'

    privileged = linked.graph(allowed_sensitivities={'normal', 'secret'})
    assert f'memory:{secret_id}' in {node['id'] for node in privileged['nodes']}


def test_bridge_projects_relationships_and_authoritative_supersession(tmp_path):
    linked, second_brain, store, _ = bridge(tmp_path)
    project_id = second_brain.remember(
        MemoryCandidate(type='project', subject='Personal AI', content='Project is in qualification.', confidence=.8)
    )
    goal_id = second_brain.remember(
        MemoryCandidate(type='goal', subject='Release', content='Release only after qualification.', confidence=.9)
    )
    store.relate(project_id, 'supports', goal_id)

    old_id = second_brain.remember(
        MemoryCandidate(
            type='preference',
            subject='Voice',
            content='Owner prefers voice disabled by default.',
            confidence=.8,
            source='explicit-user',
        )
    )
    new_id = second_brain.remember(
        MemoryCandidate(
            type='preference',
            subject='Voice',
            content='Owner now prefers voice ready when explicitly activated.',
            confidence=.95,
            source='explicit-user',
        )
    )

    snapshot = linked.graph(limit=100)
    edges = {(edge['src'], edge['relation'], edge['dst']) for edge in snapshot['edges']}
    assert (f'memory:{project_id}', 'supports', f'memory:{goal_id}') in edges
    assert (f'memory:{new_id}', 'supersedes', f'memory:{old_id}') in edges

    old_node = next(node for node in snapshot['nodes'] if node['id'] == f'memory:{old_id}')
    assert '"memory_state": "historical"' in old_node['metadata_json']


def test_bridge_reflects_deletion_immediately_and_timeline_uses_live_memory(tmp_path):
    linked, second_brain, _, _ = bridge(tmp_path)
    memory_id = second_brain.remember(
        MemoryCandidate(type='event', subject='Qualification', content='P5 qualification started.', confidence=.9)
    )
    assert f'memory:{memory_id}' in {item['id'] for item in linked.timeline()['items']}

    assert second_brain.delete(memory_id) is True
    assert f'memory:{memory_id}' not in {item['id'] for item in linked.timeline()['items']}


def test_bridge_status_distinguishes_linked_from_unlinked(tmp_path):
    linked, _, _, life_graph = bridge(tmp_path)
    assert linked.status()['linked'] is True
    unlinked = SecondBrainLifeGraph(life_graph, None)
    assert unlinked.status() == {'linked': False, 'memory_nodes': 0}

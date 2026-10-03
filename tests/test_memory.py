from pathlib import Path
import pytest
from memory.store import MemoryStore

def test_memory_graph(tmp_path:Path):
    s=MemoryStore(tmp_path/"m.sqlite3"); a=s.remember(type="project",subject="Alpha",content="Project"); b=s.remember(type="person",subject="Sam",content="Contributor"); s.relate(b,"works_on",a); g=s.graph(); assert len(g["nodes"])==2 and len(g["edges"])==1


def test_graph_projection_is_bounded_and_keeps_real_edges(tmp_path: Path):
    store = MemoryStore(tmp_path / 'memory.sqlite3')
    ids = [store.remember(type='note', subject=f'Note {index}', content='Real note') for index in range(8)]
    store.relate(ids[0], 'related_to', ids[1])
    projected = store.graph_projection(limit=3, focal_id=ids[0])
    visible = {node['id'] for node in projected['nodes']}
    assert len(visible) <= 3
    assert ids[0] in visible
    assert projected['edges'] == [edge for edge in store.graph()['edges'] if edge['source_id'] in visible and edge['target_id'] in visible]

    single_node = store.graph_projection(limit=1, focal_id=ids[0])
    assert [node['id'] for node in single_node['nodes']] == [ids[0]]
    assert single_node['edges'] == []


def test_graph_projection_counts_are_real_and_sensitive_records_are_scoped(tmp_path: Path):
    store = MemoryStore(tmp_path / 'memory.sqlite3')
    store.remember(type='note', subject='Visible', content='Safe')
    store.remember(type='note', subject='Private', content='Sensitive', sensitivity='sensitive')
    projected = store.graph_projection(limit=10, include_sensitive=False)
    assert projected['total'] == 1
    assert projected['type_counts'] == [{'type': 'note', 'total': 1}]
    assert [row['subject'] for row in projected['nodes']] == ['Visible']


def test_tree_branch_is_lazy_and_parent_updates_cannot_create_cycles(tmp_path: Path):
    store = MemoryStore(tmp_path / 'memory.sqlite3')
    root = store.remember(type='project', subject='Root', content='Root')
    child = store.remember(type='note', subject='Child', content='Child')
    grandchild = store.remember(type='note', subject='Grandchild', content='Grandchild')
    store.update_memory(child, parent_id=root)
    store.update_memory(grandchild, parent_id=child)
    branch = store.tree_children(parent_id=root, limit=1)
    assert branch['total'] == 1
    assert branch['nodes'][0]['id'] == child
    assert branch['nodes'][0]['child_count'] == 1
    with pytest.raises(ValueError, match='cycle'):
        store.update_memory(root, parent_id=grandchild)


def test_conversation_history_is_durable_and_isolated_by_thread(tmp_path: Path):
    path = tmp_path / 'm.sqlite3'
    store = MemoryStore(path)
    store.add_message('user', 'alpha question', conversation_id='alpha', device_id='phone')
    store.add_message('assistant', 'alpha answer', conversation_id='alpha', device_id='desktop')
    store.add_message('user', 'beta question', conversation_id='beta', device_id='phone')

    reopened = MemoryStore(path)

    assert reopened.recent_messages(conversation_id='alpha') == [
        {'role': 'user', 'content': 'alpha question'},
        {'role': 'assistant', 'content': 'alpha answer'},
    ]
    assert reopened.recent_messages(conversation_id='beta') == [
        {'role': 'user', 'content': 'beta question'},
    ]

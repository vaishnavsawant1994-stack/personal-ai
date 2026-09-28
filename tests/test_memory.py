from pathlib import Path
from memory.store import MemoryStore

def test_memory_graph(tmp_path:Path):
    s=MemoryStore(tmp_path/"m.sqlite3"); a=s.remember(type="project",subject="Alpha",content="Project"); b=s.remember(type="person",subject="Sam",content="Contributor"); s.relate(b,"works_on",a); g=s.graph(); assert len(g["nodes"])==2 and len(g["edges"])==1


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

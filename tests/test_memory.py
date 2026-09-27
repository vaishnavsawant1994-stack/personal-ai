from pathlib import Path
from memory.store import MemoryStore

def test_memory_graph(tmp_path:Path):
    s=MemoryStore(tmp_path/"m.sqlite3"); a=s.remember(type="project",subject="Alpha",content="Project"); b=s.remember(type="person",subject="Sam",content="Contributor"); s.relate(b,"works_on",a); g=s.graph(); assert len(g["nodes"])==2 and len(g["edges"])==1

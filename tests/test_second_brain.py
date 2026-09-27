from memory.store import MemoryStore
from memory.second_brain import SecondBrain, MemoryCandidate

def test_second_brain_deduplicates(tmp_path):
    s=MemoryStore(tmp_path/"m.sqlite3")
    b=SecondBrain(s)
    c=MemoryCandidate(type="project",subject="Alpha",content="Alpha is active",confidence=.9)
    a=b.remember(c); z=b.remember(c)
    assert a==z

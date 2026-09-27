from memory.vector_store import VectorStore
def embed(s): s=s.lower(); return [float(s.count('cat')),float(s.count('dog')),1.0]
def test_vector_ranking(tmp_path):
    v=VectorStore(tmp_path/'v.db',embed); v.upsert('1','cat cat'); v.upsert('2','dog dog'); assert v.search('cat',1)[0]['memory_id']=='1'

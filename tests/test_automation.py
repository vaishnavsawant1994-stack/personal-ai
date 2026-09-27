from automation.engine import AutomationEngine

def test_create_and_list_automation(tmp_path):
    a=AutomationEngine(tmp_path/"a.sqlite3")
    i=a.create("One","hello","2999-01-01T00:00:00+00:00")
    rows=a.list()
    assert rows[0]["id"]==i and rows[0]["enabled"]==1

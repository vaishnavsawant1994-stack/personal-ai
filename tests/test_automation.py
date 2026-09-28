from automation.engine import AutomationEngine

def test_create_and_list_automation(tmp_path):
    a=AutomationEngine(tmp_path/"a.sqlite3")
    i=a.create("One","hello","2999-01-01T00:00:00+00:00")
    rows=a.list()
    assert rows[0]["id"]==i and rows[0]["enabled"]==1


class _SecretFailingExecutor:
    def chat(self, prompt, **kwargs):
        raise RuntimeError(
            "provider failed Authorization: Bearer automation-secret-123456 "
            "api_key=automation-api-secret-234567 "
            "https://provider.invalid/?access_token=automation-access-secret-345678"
        )


def test_automation_failure_persistence_redacts_provider_credentials(tmp_path):
    engine=AutomationEngine(tmp_path/"a.sqlite3",executor=_SecretFailingExecutor())
    automation_id=engine.create("Secret failure","hello","2999-01-01T00:00:00+00:00")
    row=engine.list()[0]
    engine._run_one(row)
    stored=engine.list()[0]
    rendered=str(stored)
    assert "automation-secret-123456" not in rendered
    assert "automation-api-secret-234567" not in rendered
    assert "automation-access-secret-345678" not in rendered


def test_automation_failure_persistence_preserves_nonsecret_error_text(tmp_path):
    class Executor:
        def chat(self, prompt, **kwargs):
            raise RuntimeError("public request 550e8400-e29b-41d4-a716-446655440000 failed")
    engine=AutomationEngine(tmp_path/"a.sqlite3",executor=Executor())
    engine.create("Failure","hello","2999-01-01T00:00:00+00:00")
    engine._run_one(engine.list()[0])
    assert "550e8400-e29b-41d4-a716-446655440000" in str(engine.list()[0])

from models.governed_router import GovernedModelRouter
from models.router import ModelError


def test_unknown_model_error_has_stable_safe_classification():
    assert GovernedModelRouter._error_class(ModelError('raw provider detail'))=='unknown_failure'

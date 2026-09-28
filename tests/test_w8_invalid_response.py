from models.governed_router import GovernedModelRouter
from models.router import InvalidModelResponse

def test_invalid_model_response_has_malformed_class():
    assert GovernedModelRouter._error_class(InvalidModelResponse())=='malformed_response'

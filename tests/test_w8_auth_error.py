from models.governed_router import GovernedModelRouter
from models.router import ModelAuthenticationError

def test_auth_error_has_authentication_class():
    assert GovernedModelRouter._error_class(ModelAuthenticationError())=='authentication_error'

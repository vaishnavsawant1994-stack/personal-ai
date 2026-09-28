from models.governed_router import GovernedModelRouter
from models.router import ModelUnavailable

def test_unavailable_error_maps_to_provider_unavailable():assert GovernedModelRouter._error_class(ModelUnavailable())=='provider_unavailable'

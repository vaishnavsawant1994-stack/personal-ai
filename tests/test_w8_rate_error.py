from models.governed_router import GovernedModelRouter
from models.router import ModelRateLimited

def test_rate_limit_maps_to_rate_limited():assert GovernedModelRouter._error_class(ModelRateLimited())=='rate_limited'

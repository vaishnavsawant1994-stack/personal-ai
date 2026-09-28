from models.governed_router import GovernedModelRouter
from models.router import ModelCreditsExhausted,ModelSpendLimitReached

def test_billing_configuration_failures_are_non_retryable():
    assert GovernedModelRouter._error_class(ModelCreditsExhausted())=='configuration_error'
    assert GovernedModelRouter._error_class(ModelSpendLimitReached())=='configuration_error'

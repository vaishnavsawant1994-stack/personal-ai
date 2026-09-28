from models.governed_router import GovernedModelRouter
from models.router import ModelError

def test_error_classification_does_not_copy_exception_message():
    exc=ModelError('SECRET PRIVATE ERROR DETAIL');assert GovernedModelRouter._error_class(exc)=='unknown_failure' and 'SECRET' not in GovernedModelRouter._error_class(exc)

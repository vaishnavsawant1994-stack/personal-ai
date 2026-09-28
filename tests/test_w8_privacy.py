from models.resilience import ModelObservability


def test_common_secret_fields_are_dropped_from_generation_records():
    obs=ModelObservability(['p'])
    payload={'generation_id':'gen','provider':'p','result':'failed','api_key':'K','access_token':'T','password':'P','cookie':'C','authorization':'A','messages':['secret'],'prompt':'secret','response':'secret','environment':'SECRET=1'}
    obs.add_generation(payload);text=repr(obs.snapshot())
    for value in ('K','T','P','C','A','SECRET=1'):assert value not in text


def test_safe_identity_and_classification_are_retained():
    obs=ModelObservability(['p']);obs.add_generation({'generation_id':'gen','provider':'p','model':'m','capability':'chat','sensitivity':'sensitive','error_code':'policy_denied','result':'failed'})
    row=obs.snapshot()['recent_generations'][-1]
    assert row['generation_id']=='gen' and row['sensitivity']=='sensitive' and row['error_code']=='policy_denied'

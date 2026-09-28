from models.resilience import ModelObservability

def test_health_report_has_configuration_transport_capability_dimensions():
    row=ModelObservability(['p']).snapshot()['providers']['p'];assert {'state','configuration','transport','capability','last_success_at','last_failure_at','consecutive_failures','circuit'}.issubset(row)

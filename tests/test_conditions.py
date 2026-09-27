from automation.conditions import evaluate_condition
def test_nested_conditions():
    c={'all':[{'path':'weather.temp','op':'lt','value':5},{'path':'home.occupied','op':'eq','value':True}]}; assert evaluate_condition(c,{'weather':{'temp':2},'home':{'occupied':True}}); assert not evaluate_condition(c,{'weather':{'temp':8},'home':{'occupied':True}})

from ..parser import parse

def test_parse (example_yaml):
    # test jina parsing
    for i in range(5):
        assert ('bias_lens%i'%i in example_yaml['generate']['parameters'])
    assert (example_yaml['generate']['parameters'] == example_yaml['analyze']['parameters'])
    

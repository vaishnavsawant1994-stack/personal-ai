from core.security import PairingManager

def test_pairing_consumes_once():
    p=PairingManager(60); o=p.create(); assert p.consume(o.token,o.code); assert not p.consume(o.token,o.code)

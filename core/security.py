from __future__ import annotations
import hashlib, hmac, secrets, time
from dataclasses import dataclass

@dataclass
class PairingOffer:
    code: str
    token: str
    expires_at: float

class PairingManager:
    def __init__(self, ttl_seconds: int = 300):
        self.ttl = ttl_seconds
        self._offers: dict[str, PairingOffer] = {}

    def create(self) -> PairingOffer:
        token = secrets.token_urlsafe(32)
        code = f"{secrets.randbelow(1_000_000):06d}"
        offer = PairingOffer(code, token, time.time()+self.ttl)
        self._offers[token] = offer
        return offer

    def consume(self, token: str, code: str) -> bool:
        offer = self._offers.pop(token, None)
        if not offer or time.time() > offer.expires_at:
            return False
        return hmac.compare_digest(offer.code, code)

def hash_secret(secret: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", secret.encode(), salt.encode(), 250_000).hex()

def verify_secret(secret: str, salt: str, expected: str) -> bool:
    return hmac.compare_digest(hash_secret(secret, salt), expected)

def new_bearer_secret() -> tuple[str,str,str]:
    token=secrets.token_urlsafe(48)
    salt=secrets.token_hex(16)
    return token,salt,hash_secret(token,salt)

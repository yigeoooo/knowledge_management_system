"""Token hashing primitives."""

import hashlib


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


__all__ = ["token_hash"]

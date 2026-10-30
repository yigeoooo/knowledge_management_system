"""Password hashing primitives shared by HTTP and CLI entry points."""

import secrets

from argon2 import PasswordHasher

password_hasher = PasswordHasher()
dummy_hash = password_hasher.hash(secrets.token_urlsafe(32))

__all__ = ["dummy_hash", "password_hasher"]

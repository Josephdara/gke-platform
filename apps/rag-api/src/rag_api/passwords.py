"""scrypt password hashes. Standard library only, so tools/make_users.py runs with any python3."""

import base64
import hashlib
import hmac
import secrets

# scrypt with N=2^15, r=8 uses 32 MiB per check; the sign-in throttle bounds how many run at once.
SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}
SCRYPT_MAXMEM = 64 * 1024 * 1024


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, maxmem=SCRYPT_MAXMEM, dklen=32, **SCRYPT)
    return f"scrypt${SCRYPT['n']}${SCRYPT['r']}${SCRYPT['p']}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=unb64(salt), n=int(n), r=int(r), p=int(p),
                                maxmem=SCRYPT_MAXMEM, dklen=len(unb64(digest)))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, unb64(digest))


# Checked when the username is unknown, so a wrong username takes as long as a wrong password.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))

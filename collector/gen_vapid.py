"""웹 푸시용 VAPID 키 쌍 생성.

  python -m collector.gen_vapid

출력된 PRIVATE 값은 GitHub Secret `VAPID_PRIVATE_KEY` 에, PUBLIC 값은 docs/config.js 의 VAPID_PUBLIC_KEY 에 넣는다.
"""
from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def generate() -> tuple[str, str]:
    v = Vapid()
    v.generate_keys()
    public = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    private_value = v.private_key.private_numbers().private_value.to_bytes(32, "big")
    return b64url(public), b64url(private_value)


if __name__ == "__main__":
    pub, priv = generate()
    print("VAPID_PUBLIC_KEY  (docs/config.js 에 공개):", pub)
    print("VAPID_PRIVATE_KEY (GitHub Secret, 비공개):", priv)

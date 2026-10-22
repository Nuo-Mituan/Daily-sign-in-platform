"""Versioned field encryption for module parameters and push credentials.

v2 (current):
    AES-256-GCM, 256-bit key derived from SECRET_KEY with HKDF-SHA256.
    Ciphertext format: ``v2:<urlsafe-base64(nonce || ciphertext || tag)>``.
    AAD binds the owner user id, module key and account index.

v1 (legacy):
    Fernet, derived exactly as the previous release.  Tokens have no version
    prefix (or an optional ``v1:`` prefix).  Reads transparently support v1 and
    the caller can re-encrypt with the same plaintext using :meth:`is_v2`.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass, replace
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .config import settings

V2_PREFIX = "v2:"
V1_PREFIX = "v1:"
_AAD_VERSION = "v2"
_HKDF_SALT = b"daily-checkin-field-encryption"
_HKDF_INFO = b"aes-256-gcm-v2"


class ParameterDecryptionError(RuntimeError):
    """Raised when stored parameters cannot be decrypted with the current secret."""


@dataclass(frozen=True)
class EncryptionContext:
    """Identity context bound into the AES-GCM AAD."""

    user_id: int
    module_key: str
    account_index: int = -1


def mask_secret(value: Any) -> str:
    """Return a stable display mask without leaking the secret value."""
    if value is None:
        return ""
    text = str(value)
    if not text:
        return ""
    if len(text) <= 8:
        return "****"
    return f"{text[:4]}****{text[-4:]}"


def _aad(context: EncryptionContext) -> bytes:
    return (
        f"{_AAD_VERSION}|{int(context.user_id)}|{context.module_key}|"
        f"{int(context.account_index)}"
    ).encode("utf-8")


class ParameterCipher:
    def __init__(self, secret: str) -> None:
        secret_bytes = (secret or "").encode("utf-8")
        self._key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_HKDF_SALT,
            info=_HKDF_INFO,
        ).derive(secret_bytes)
        legacy_key = base64.urlsafe_b64encode(hashlib.sha256(secret_bytes).digest())
        self._fernet = Fernet(legacy_key)

    @staticmethod
    def is_v2(token: str | None) -> bool:
        return bool(token and token.startswith(V2_PREFIX))

    def encrypt_any(self, data: Any, context: EncryptionContext) -> str:
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        nonce = os.urandom(12)
        sealed = AESGCM(self._key).encrypt(nonce, payload, _aad(context))
        return V2_PREFIX + base64.urlsafe_b64encode(nonce + sealed).decode("ascii")

    def decrypt_any(self, token: str | None, context: EncryptionContext) -> Any:
        if not token:
            return None
        if self.is_v2(token):
            try:
                raw = base64.urlsafe_b64decode(token[len(V2_PREFIX) :].encode("ascii"))
                if len(raw) < 12 + 16:
                    raise ValueError("ciphertext too short")
                nonce, sealed = raw[:12], raw[12:]
                payload = AESGCM(self._key).decrypt(nonce, sealed, _aad(context))
                return json.loads(payload.decode("utf-8"))
            except (
                InvalidTag,
                ValueError,
                UnicodeDecodeError,
                json.JSONDecodeError,
            ) as exc:
                raise ParameterDecryptionError(
                    "v2 加密数据解密失败：SECRET_KEY 不匹配、记录上下文不一致或密文已损坏。"
                ) from exc

        # Legacy Fernet tokens have no prefix in older databases.  Accept an
        # explicit v1: prefix too for forward readability of hand-migrated data.
        legacy_token = token[len(V1_PREFIX) :] if token.startswith(V1_PREFIX) else token
        try:
            raw = self._fernet.decrypt(legacy_token.encode("ascii"))
            return json.loads(raw.decode("utf-8"))
        except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
            raise ParameterDecryptionError(
                "旧版 v1 加密数据解密失败。SECRET_KEY 可能已变更，请在配置页重新填写并保存。"
            ) from exc

    def encrypt(self, data: dict[str, Any], context: EncryptionContext) -> str:
        return self.encrypt_any(data, context)

    def decrypt(self, token: str | None, context: EncryptionContext) -> dict[str, Any]:
        if not token:
            return {}
        value = self.decrypt_any(token, context)
        if not isinstance(value, dict):
            raise ParameterDecryptionError("参数格式异常，请在配置页重新保存。")
        return value

    def encrypt_accounts(
        self, accounts: list[dict[str, Any]], context: EncryptionContext
    ) -> str:
        """Encrypt each account's params separately, then encrypt the outer list.

        The outer envelope uses account_index=-1.  Every inner params token uses
        its real index, so moving a ciphertext between accounts invalidates the
        GCM tag.
        """
        outer = replace(context, account_index=-1)
        wrapped: list[dict[str, Any]] = []
        for index, account in enumerate(accounts):
            params = account.get("params")
            if not isinstance(params, dict):
                raise ParameterDecryptionError(f"第 {index + 1} 个账号参数格式异常")
            wrapped.append(
                {
                    "id": str(account.get("id") or ""),
                    "label": str(account.get("label") or ""),
                    "params": self.encrypt_any(
                        params, replace(context, account_index=index)
                    ),
                }
            )
        return self.encrypt_any(wrapped, outer)

    def decrypt_accounts(
        self, token: str | None, context: EncryptionContext
    ) -> tuple[list[dict[str, Any]], bool]:
        """Decrypt account params and report whether an upgrade is needed.

        Returns ``(accounts, upgraded)`` where each account is
        ``{"id", "label", "params"}``.  A v1 outer blob (or a v2 outer blob with
        legacy inner values) sets ``upgraded=True`` so the caller can persist a
        fresh v2 envelope.
        """
        if not token:
            return [], False
        outer_context = replace(context, account_index=-1)
        upgraded = not self.is_v2(token)
        raw = self.decrypt_any(token, outer_context)
        if not isinstance(raw, list):
            raise ParameterDecryptionError("账号密文格式异常，请在配置页重新保存。")
        accounts: list[dict[str, Any]] = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                raise ParameterDecryptionError(
                    f"第 {index + 1} 个账号密文格式异常，请在配置页重新保存。"
                )
            params_raw = item.get("params")
            if isinstance(params_raw, dict):
                upgraded = True
                params = params_raw
            elif isinstance(params_raw, str):
                if not self.is_v2(params_raw):
                    upgraded = True
                params = self.decrypt_any(
                    params_raw, replace(context, account_index=index)
                )
            else:
                raise ParameterDecryptionError(
                    f"第 {index + 1} 个账号缺少参数密文，请在配置页重新保存。"
                )
            if not isinstance(params, dict):
                raise ParameterDecryptionError(
                    f"第 {index + 1} 个账号参数格式异常，请在配置页重新保存。"
                )
            accounts.append(
                {
                    "id": str(item.get("id") or ""),
                    "label": str(item.get("label") or ""),
                    "params": params,
                }
            )
        return accounts, upgraded


parameter_cipher = ParameterCipher(settings.secret_key or "insecure-fallback-key")

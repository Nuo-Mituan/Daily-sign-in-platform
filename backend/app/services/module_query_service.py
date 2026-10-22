"""Module query/masking helpers moved out of the Router layer."""

from __future__ import annotations

from typing import Any

from ..crypto import (
    EncryptionContext,
    ParameterDecryptionError,
    mask_secret,
    parameter_cipher,
)
from ..models import Module


def _is_sensitive_spec(spec: dict[str, Any]) -> bool:
    if spec.get("sensitive"):
        return True
    key = str(spec.get("key") or "").lower()
    return spec.get("type") == "password" or key in {
        "password",
        "passwd",
        "pwd",
        "cookie",
        "token",
        "secret",
        "key",
        "api_key",
        "access_token",
        "refresh_token",
        "authorization",
    } or key.endswith(("_token", "_secret", "_key"))


def _mask_params(params: dict[str, Any], schema: list[dict[str, Any]]) -> dict[str, Any]:
    masked = dict(params)
    for spec in schema:
        key = spec.get("key")
        if key in masked and _is_sensitive_spec(spec):
            masked[key] = mask_secret(masked[key])
    return masked


def _mask_accounts(
    accounts: list[dict[str, Any]], schema: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return [
        {
            "id": account.get("id", ""),
            "label": account.get("label", ""),
            "params": _mask_params(account.get("params") or {}, schema),
        }
        for account in accounts
    ]


def _sensitive_only(
    params: dict[str, Any], schema: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        spec["key"]: params[spec["key"]]
        for spec in schema
        if spec.get("key") in params and _is_sensitive_spec(spec)
    }


def _merge_sensitive_params(
    incoming: dict[str, Any],
    stored: dict[str, Any],
    schema: list[dict[str, Any]],
) -> dict[str, Any]:
    merged = dict(incoming)
    for spec in schema:
        key = spec.get("key")
        if key not in merged or not _is_sensitive_spec(spec):
            continue
        previous = stored.get(key)
        if previous in (None, ""):
            continue
        # The API returns a mask.  Keeping the input untouched (or blanking it)
        # preserves the stored secret rather than writing the mask to the DB.
        if merged[key] in (None, "", mask_secret(previous)):
            merged[key] = previous
    return merged


def _merge_sensitive_accounts(
    incoming: list[dict[str, Any]],
    stored: list[dict[str, Any]],
    schema: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id = {str(item.get("id")): item for item in stored}
    merged: list[dict[str, Any]] = []
    for item in incoming:
        account = {
            "id": item.get("id"),
            "label": item.get("label") or "",
            "params": dict(item.get("params") or {}),
        }
        previous = by_id.get(str(account["id"]))
        if previous:
            account["params"] = _merge_sensitive_params(
                account["params"], previous.get("params") or {}, schema  # type: ignore[arg-type]  # TODO(v1.0.3): fix typing
            )
        merged.append(account)
    return merged


def _safe_account_count(module: Module, encryption_context: EncryptionContext) -> int:
    if not module.multi_account:
        return 1 if module.params_encrypted else 0
    if not module.accounts_encrypted:
        return 1 if module.params_encrypted else 0
    try:
        accounts, _ = parameter_cipher.decrypt_accounts(
            module.accounts_encrypted,
            EncryptionContext(
                user_id=encryption_context.user_id,
                module_key=module.key,
                account_index=-1,
            ),
        )
        return len(accounts)
    except ParameterDecryptionError:
        return 0



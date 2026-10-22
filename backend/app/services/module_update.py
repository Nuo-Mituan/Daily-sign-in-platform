"""Orchestration for module configuration updates.

The router owns HTTP translation and module-specific merge/validation hooks;
this service owns the multi-step business flow so the route remains a thin
request/response adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from ..crypto import EncryptionContext, parameter_cipher
from ..models import Module
from ..module_loader import ModuleConfig
from ..scheduling import ScheduleError, validate_schedule


class ModuleUpdatePayload(Protocol):
    start_time: str | None
    end_time: str | None
    repeat_cycle: str | None
    repeat_sub_value: str | None
    push_enabled: bool | None
    push_independent: bool | None
    push_unified: bool | None
    enabled: bool | None
    params: dict[str, object] | None
    accounts: list[object] | None


@dataclass
class ModuleUpdateHooks:
    schedule_fields: Callable[[Module], tuple[str, str, str, str]]
    stored_accounts: Callable[[Module, EncryptionContext], list[dict[str, object]]]
    merge_accounts: Callable[
        [list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]],
        list[dict[str, object]],
    ]
    validate_accounts: Callable[
        [Module, ModuleConfig, EncryptionContext, list[dict[str, object]] | None],
        list[dict[str, object]],
    ]
    stored_params: Callable[[Module, EncryptionContext], dict[str, object]]
    merge_params: Callable[
        [dict[str, object], dict[str, object], list[dict[str, object]]],
        dict[str, object],
    ]
    validate_params: Callable[[ModuleConfig, dict[str, object]], dict[str, object]]
    validate_stored_params: Callable[
        [Module, ModuleConfig, EncryptionContext], dict[str, object]
    ]


@dataclass
class ModuleUpdatePlan:
    start_time: str
    end_time: str
    repeat_cycle: str
    repeat_sub_value: str
    schedule_changed: bool
    target_enabled: bool
    params_encrypted: str | None = None
    accounts_encrypted: str | None = None
    validated_params: dict[str, object] | None = None
    validated_accounts: list[dict[str, object]] | None = None


class ModuleUpdateError(ValueError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _next_schedule(module: Module, payload: ModuleUpdatePayload, hooks: ModuleUpdateHooks) -> tuple[str, str, str, str, bool]:
    current = hooks.schedule_fields(module)
    start = payload.start_time if payload.start_time is not None else current[0]
    end = payload.end_time if payload.end_time is not None else current[1]
    cycle = payload.repeat_cycle if payload.repeat_cycle is not None else current[2]
    if payload.repeat_sub_value is not None:
        sub = payload.repeat_sub_value
    elif cycle != current[2]:
        sub = ""
    else:
        sub = current[3]
    try:
        next_values = validate_schedule(start, end, cycle, sub)
    except ScheduleError as exc:
        raise ModuleUpdateError(400, str(exc)) from exc
    return (*next_values, next_values != current)


def _apply_accounts(
    module: Module,
    payload: ModuleUpdatePayload,
    config: ModuleConfig,
    context: EncryptionContext,
    hooks: ModuleUpdateHooks,
) -> tuple[str | None, list[dict[str, object]] | None]:
    if payload.params is not None:
        raise ModuleUpdateError(400, "该模块启用了多账号模式，请使用 accounts 字段提交账号列表")
    if payload.accounts is None:
        return None, None
    incoming = [getattr(account, "model_dump")() for account in payload.accounts]
    stored = hooks.stored_accounts(module, context)
    merged = hooks.merge_accounts(incoming, stored, list(module.param_schema or []))
    validated = hooks.validate_accounts(module, config, context, merged)
    return parameter_cipher.encrypt_accounts(validated, context), validated


def _apply_params(
    module: Module,
    payload: ModuleUpdatePayload,
    config: ModuleConfig,
    context: EncryptionContext,
    hooks: ModuleUpdateHooks,
) -> tuple[str | None, dict[str, object] | None]:
    if payload.accounts is not None:
        raise ModuleUpdateError(400, "该模块未启用多账号模式，请使用 params 字段")
    if payload.params is None:
        return None, None
    stored = (
        hooks.stored_params(module, context) if module.params_encrypted else {}
    )
    merged = hooks.merge_params(payload.params, stored, list(module.param_schema or []))
    try:
        normalized = hooks.validate_params(config, merged)
    except Exception as exc:
        raise ModuleUpdateError(400, str(exc)) from exc
    return parameter_cipher.encrypt(normalized, context), normalized


def plan_module_update(
    module: Module,
    payload: ModuleUpdatePayload,
    config: ModuleConfig,
    context: EncryptionContext,
    hooks: ModuleUpdateHooks,
) -> ModuleUpdatePlan:
    start, end, cycle, sub, changed = _next_schedule(module, payload, hooks)
    target_enabled = module.enabled if payload.enabled is None else payload.enabled
    accounts_encrypted = None
    params_encrypted = None
    validated_params = None
    validated_accounts = None
    if config.multi_account:
        accounts_encrypted, validated_accounts = _apply_accounts(
            module, payload, config, context, hooks
        )
    else:
        params_encrypted, validated_params = _apply_params(
            module, payload, config, context, hooks
        )
    if target_enabled:
        if module.load_error:
            raise ModuleUpdateError(
                400, f"模块加载异常，暂时无法启用：{module.load_error}"
            )
        if config.multi_account:
            accounts = (
                validated_accounts
                if validated_accounts is not None
                else hooks.validate_accounts(module, config, context, None)
            )
            if not accounts:
                raise ModuleUpdateError(400, "请至少添加一个账号")
        elif validated_params is None:
            hooks.validate_stored_params(module, config, context)
    return ModuleUpdatePlan(
        start_time=start,
        end_time=end,
        repeat_cycle=cycle,
        repeat_sub_value=sub,
        schedule_changed=changed,
        target_enabled=target_enabled,
        params_encrypted=params_encrypted,
        accounts_encrypted=accounts_encrypted,
        validated_params=validated_params,
        validated_accounts=validated_accounts,
    )

"""Global push notification configuration and delivery.

Supported channels: Bark, ServerChan, PushPlus, DingTalk and Feishu.
Credentials are encrypted with the same SECRET_KEY-derived cipher used for
module parameters.  Notification failures never affect a check-in result.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..contracts import PushConfigData, PushSendResult
from .push_outbox import make_idempotency_key
from ..crypto import (
    EncryptionContext,
    ParameterDecryptionError,
    mask_secret,
    parameter_cipher,
)
from ..database import SessionLocal
from ..models import Module, PushConfig, PushRecord
from .ownership import owner_user_id
from .redaction import redact_text
from .ring_log import ring_log
from ..push_drivers.base import DriverLoadError, DriverValidationError
from ..push_drivers.builtin_specs import CHANNEL_SPECS
from ..push_drivers.registry import driver_registry

logger = logging.getLogger(__name__)

SUPPORTED_CHANNELS = ("none", "bark", "serverchan", "pushplus", "dingtalk", "feishu")

CHANNEL_LABELS = {
    "none": "不推送",
    "bark": "Bark",
    "serverchan": "Server 酱",
    "pushplus": "PushPlus",
    "dingtalk": "钉钉",
    "feishu": "飞书",
}


CHANNEL_FIELDS = {
    spec["channel"]: {field["key"]: field for field in spec["fields"]}
    for spec in CHANNEL_SPECS
}

PUSH_VARIABLES = [
    "{event}",
    "{module_name}",
    "{module_key}",
    "{account}",
    "{status}",
    "{result}",
    "{duration}",
    "{error}",
    "{time}",
    "{summary}",
    "{details}",
]

DEFAULT_TITLE_TEMPLATE = "{event}｜{module_name}"
DEFAULT_BODY_TEMPLATE = """### {event}
- 模块：{module_name}
- 账号：{account}
- 状态：{status}
- 耗时：{duration}
- 时间：{time}
- 结果：{result}
{details}"""

EVENT_LABELS = {
    "success": "签到成功",
    "failure": "签到失败",
    "partial_failure": "多账号部分失败",
    "schedule_failure": "随机时间生成失败",
    "test": "推送测试",
}


class PushConfigError(ValueError):
    pass


def _truncate(value: str, limit: int = 700) -> str:
    value = str(value or "")
    return value if len(value) <= limit else value[:limit] + "…"


def _normalize_webhook(value: str, allowed_hosts: set[str], label: str) -> str:
    text = str(value or "").strip()
    try:
        parsed = urlsplit(text)
    except ValueError as exc:
        raise PushConfigError(f"{label} URL 无效") from exc
    if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
        allowed = "、".join(sorted(allowed_hosts))
        raise PushConfigError(f"{label} 必须使用 HTTPS 且域名为：{allowed}")
    if not parsed.path or parsed.path == "/":
        raise PushConfigError(f"{label} URL 缺少路径")
    return text


def channel_specs() -> list[dict[str, object]]:
    specs = list(CHANNEL_SPECS)
    known = {item["channel"] for item in specs}
    for record in driver_registry.list_drivers():
        if record["builtin"] or record["key"] in known:
            continue
        specs.append(
            {
                "channel": record["key"],
                "label": record["name"],
                "fields": record["fields"],
                "builtin": False,
                "version": record["version"],
            }
        )
    return specs


def channel_fields(channel: str) -> dict[str, dict[str, object]]:
    if channel in CHANNEL_FIELDS:
        return CHANNEL_FIELDS[channel]
    return driver_registry.fields_for(channel)


def supported_channels() -> set[str]:
    return {"none"} | {spec["channel"] for spec in channel_specs()}


def normalize_push_config(channel: str, raw_config: dict[str, object] | None) -> dict[str, str]:
    channel = (channel or "none").strip().lower()
    if channel != "none" and channel not in supported_channels():
        raise PushConfigError("不支持的推送渠道")
    raw = raw_config or {}
    if not isinstance(raw, dict):
        raise PushConfigError("推送配置必须是对象")
    if channel == "none":
        return {}

    fields = channel_fields(channel)
    normalized: dict[str, str] = {}
    for key, spec in fields.items():
        value = str(raw.get(key) or "").strip()
        if spec["required"] and not value:
            raise PushConfigError(f"请填写「{spec['label']}」")
        if len(value) > 2000:
            raise PushConfigError(f"「{spec['label']}」过长")
        if value:
            normalized[key] = value

    return _normalize_webhook_fields(channel, normalized)


def _normalize_webhook_fields(
    channel: str, normalized: dict[str, str]
) -> dict[str, str]:
    if channel == "dingtalk" and normalized.get("webhook"):
        normalized["webhook"] = _normalize_webhook(
            normalized["webhook"], {"oapi.dingtalk.com"}, "钉钉 Webhook"
        )
    if channel == "feishu" and normalized.get("webhook"):
        normalized["webhook"] = _normalize_webhook(
            normalized["webhook"],
            {"open.feishu.cn", "open.larksuite.com"},
            "飞书 Webhook",
        )
    return normalized


def normalize_templates(title_template: str | None, body_template: str | None) -> tuple[str, str]:
    title = (title_template or "").strip() or DEFAULT_TITLE_TEMPLATE
    body = (body_template or "").strip() or DEFAULT_BODY_TEMPLATE
    if len(title) > 300:
        raise PushConfigError("推送标题模板不能超过 300 字符")
    if len(body) > 8000:
        raise PushConfigError("推送正文模板不能超过 8000 字符")
    return title, body


def render_template(template: str, variables: dict[str, object]) -> str:
    rendered = template
    for key, value in variables.items():
        rendered = rendered.replace("{" + key + "}", "" if value is None else str(value))
    return _truncate(rendered, 3500)


async def get_push_config_row(db: AsyncSession) -> PushConfig | None:
    return await db.get(PushConfig, 1)


async def load_push_config(db: AsyncSession) -> PushConfigData:
    row = await get_push_config_row(db)
    if row is None:
        return {
            "channel": "none",
            "config": {},
            "title_template": DEFAULT_TITLE_TEMPLATE,
            "body_template": DEFAULT_BODY_TEMPLATE,
            "updated_at": None,
        }
    context = EncryptionContext(
        user_id=await owner_user_id(db),
        module_key="__push_config__",
        account_index=-1,
    )
    try:
        config = parameter_cipher.decrypt(row.config_encrypted, context)
    except ParameterDecryptionError as exc:
        raise PushConfigError(str(exc)) from exc
    if row.config_encrypted and not parameter_cipher.is_v2(row.config_encrypted):
        row.config_encrypted = parameter_cipher.encrypt(config, context)
        await db.commit()
    return {
        "channel": row.channel or "none",
        "config": config,
        "title_template": row.title_template or DEFAULT_TITLE_TEMPLATE,
        "body_template": row.body_template or DEFAULT_BODY_TEMPLATE,
        "updated_at": row.updated_at,
    }


async def save_push_config(
    db: AsyncSession,
    channel: str,
    raw_config: dict[str, object] | None,
    title_template: str | None,
    body_template: str | None,
) -> dict[str, object]:
    channel = (channel or "none").strip().lower()
    raw = dict(raw_config or {})
    row = await get_push_config_row(db)
    context = EncryptionContext(
        user_id=await owner_user_id(db),
        module_key="__push_config__",
        account_index=-1,
    )
    # The API returns masked credentials.  An unchanged mask, blank value or
    # missing key keeps the previous secret instead of overwriting it with stars.
    if row is not None and row.channel == channel and row.config_encrypted:
        try:
            previous = parameter_cipher.decrypt(row.config_encrypted, context)
        except ParameterDecryptionError as exc:
            # Never overwrite a config that cannot be decrypted with a new
            # value that silently discards the old credentials.
            raise PushConfigError(
                "原推送配置无法解密，请先恢复 SECRET_KEY 或清空并重新填写配置"
            ) from exc
        for key, spec in channel_fields(channel).items():
            old_value = previous.get(key)
            if old_value in (None, ""):
                continue
            if raw.get(key) in (None, "", mask_secret(old_value)):
                raw[key] = old_value
    normalized_config = normalize_push_config(channel, raw)
    title, body = normalize_templates(title_template, body_template)
    if row is None:
        row = PushConfig(id=1)
        db.add(row)
    row.channel = channel
    row.config_encrypted = (
        parameter_cipher.encrypt(normalized_config, context)
        if normalized_config
        else None
    )
    row.title_template = title
    row.body_template = body
    await db.commit()
    await db.refresh(row)
    return {
        "channel": row.channel,
        "config": normalized_config,
        "title_template": row.title_template,
        "body_template": row.body_template,
        "updated_at": row.updated_at,
    }


def _safe_error(exc: BaseException, secrets: list[str]) -> str:
    detail = f"{type(exc).__name__}: {exc}"
    for secret in secrets:
        if secret:
            detail = detail.replace(secret, "***")
    return _truncate(detail)


def _append_query(url: str, params: dict[str, str]) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(params)
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def _dingtalk_signed_url(webhook: str, secret: str) -> str:
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(
        secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256
    ).digest()
    sign = quote(base64.b64encode(digest).decode("ascii"))
    return _append_query(webhook, {"timestamp": timestamp, "sign": sign})


def _feishu_sign(secret: str) -> tuple[str, str]:
    timestamp = str(int(time.time()))
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(
        string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
    ).digest()
    return timestamp, base64.b64encode(digest).decode("ascii")


def _raise_for_business_error(channel: str, data: dict[str, object]) -> None:
    if not isinstance(data, dict):
        return
    code = data.get("code", data.get("errcode", data.get("StatusCode")))
    if code in (None, 0, 200, "0", "200"):
        return
    message = (
        data.get("message")
        or data.get("msg")
        or data.get("errmsg")
        or data.get("StatusMessage")
        or f"业务错误码 {code}"
    )
    raise RouterPushError(f"{channel} 返回错误：{message}")


class RouterPushError(RuntimeError):
    pass


async def _deliver(
    channel: str,
    config: dict[str, object],
    title: str,
    body: str,
    idempotency_key: str | None = None,
) -> PushSendResult:
    timeout = httpx.Timeout(
        settings.push_http_timeout_seconds,
        connect=settings.push_connect_timeout_seconds,
    )
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        headers={
            "User-Agent": "DailyCheckin/1.0",
            **({"Idempotency-Key": idempotency_key} if idempotency_key else {}),
        },
    ) as client:
        if channel == "bark":
            url = "https://api.day.app/push"
            payload = {
                "device_key": config["key"],
                "title": title,
                "body": body,
                "group": "签到云台",
            }
            response = await client.post(url, json=payload)
        elif channel == "serverchan":
            url = f"https://sctapi.ftqq.com/{quote(config['send_key'], safe='')}.send"
            response = await client.post(url, data={"title": title, "desp": body})
        elif channel == "pushplus":
            url = "https://www.pushplus.plus/send"
            response = await client.post(
                url,
                json={
                    "token": config["token"],
                    "title": title,
                    "content": body,
                    "template": "markdown",
                },
            )
        elif channel == "dingtalk":
            url = config["webhook"]
            if config.get("secret"):
                url = _dingtalk_signed_url(url, config["secret"])
            response = await client.post(
                url,
                json={
                    "msgtype": "markdown",
                    "markdown": {"title": title, "text": f"### {title}\n\n{body}"},
                },
            )
        elif channel == "feishu":
            payload: dict[str, object] = {
                "msg_type": "text",
                "content": {"text": f"{title}\n\n{body}"},
            }
            if config.get("secret"):
                timestamp, sign = _feishu_sign(config["secret"])
                payload["timestamp"] = timestamp
                payload["sign"] = sign
            response = await client.post(config["webhook"], json=payload)
        else:
            raise RouterPushError("未配置推送渠道")

        response.raise_for_status()
        try:
            data = response.json()
        except ValueError:
            data = {}
        _raise_for_business_error(channel, data)
        return {
            "sent": True,
            "channel": channel,
            "http_status": response.status_code,
            "response": _truncate(json.dumps(data, ensure_ascii=False) if data else response.text),
        }


async def send_message(
    channel: str,
    config: dict[str, object],
    title: str,
    body: str,
    idempotency_key: str | None = None,
) -> PushSendResult:
    if channel == "none":
        return {"sent": False, "channel": channel, "reason": "未配置推送渠道"}
    if channel not in CHANNEL_FIELDS:
        secrets = [str(value) for value in (config or {}).values()]
        try:
            result = await driver_registry.send(channel, config, title, body)
        except (DriverLoadError, DriverValidationError) as exc:
            return {"sent": False, "channel": channel, "error": _safe_error(exc, secrets)}
        if not result.get("sent", False) and result.get("error"):
            result["error"] = _safe_error(
                RuntimeError(str(result["error"])), secrets
            )
        return result
    secrets = [str(value) for value in (config or {}).values()]
    last_error = ""
    for attempt in range(1, 3):
        try:
            return await _deliver(
                channel, config, title, body, idempotency_key
            )
        except (httpx.HTTPError, RouterPushError, KeyError, ValueError) as exc:
            last_error = _safe_error(exc, secrets)
            if attempt < 2:
                await asyncio.sleep(settings.push_request_retry_seconds)
        except Exception as exc:  # noqa: BLE001 - notifications must never crash jobs
            last_error = _safe_error(exc, secrets)
            break
    logger.warning("推送发送失败：channel=%s，原因=%s", channel, last_error)
    return {"sent": False, "channel": channel, "error": last_error}


async def notify_module(
    module_id: int,
    *,
    event: str,
    status_text: str,
    result: str,
    account: str = "—",
    duration: str = "—",
    error: str = "",
    summary: str = "",
    details: str = "",
    ignore_switch: bool = False,
) -> dict[str, object]:
    try:
        async with SessionLocal() as db:
            module = await db.get(Module, module_id)
            if module is None:
                return {"sent": False, "reason": "模块不存在"}
            if not ignore_switch and not module.push_enabled:
                return {"sent": False, "reason": "模块推送未启用"}
            config_data = await load_push_config(db)
            if config_data["channel"] == "none":
                return {"sent": False, "reason": "未配置全局推送渠道"}
            module_name = module.name
            module_key = module.key
    except PushConfigError as exc:
        logger.warning("读取推送配置失败：%s", exc)
        return {"sent": False, "reason": str(exc)}
    except Exception:
        logger.exception("读取推送配置发生异常")
        return {"sent": False, "reason": "读取推送配置失败"}

    event_label = EVENT_LABELS.get(event, event)
    variables = {
        "event": event_label,
        "module_name": module_name,
        "module_key": module_key,
        "account": account or "—",
        "status": status_text,
        "result": result,
        "duration": duration,
        "error": error,
        "time": datetime.now(settings.timezone_info).strftime("%Y-%m-%d %H:%M:%S"),
        "summary": summary,
        "details": details,
    }
    title = render_template(config_data["title_template"], variables)
    body = render_template(config_data["body_template"], variables)
    result_data = await send_message(
        config_data["channel"], config_data["config"], title, body
    )
    if result_data.get("sent"):
        logger.info("推送成功：module=%s，channel=%s", module_key, config_data["channel"])
    return result_data


async def send_test_notification() -> dict[str, object]:
    async with SessionLocal() as db:
        config_data = await load_push_config(db)
    if config_data["channel"] == "none":
        raise PushConfigError("请先配置并保存一个推送渠道")
    variables = {
        "event": EVENT_LABELS["test"],
        "module_name": "签到云台",
        "module_key": "system",
        "account": "—",
        "status": "测试",
        "result": "这是一条来自签到云台的测试消息。",
        "duration": "—",
        "error": "",
        "time": datetime.now(settings.timezone_info).strftime("%Y-%m-%d %H:%M:%S"),
        "summary": "推送配置正常",
        "details": "",
    }
    title = render_template(config_data["title_template"], variables)
    body = render_template(config_data["body_template"], variables)
    return await send_message(
        config_data["channel"], config_data["config"], title, body
    )


def public_push_config(data: dict[str, object]) -> dict[str, object]:
    channel = str(data.get("channel", "none"))
    raw_config = data.get("config", {}) or {}
    fields = channel_fields(channel)
    masked_config = {
        key: mask_secret(value) if fields.get(key, {}).get("secret") else value
        for key, value in raw_config.items()
    }
    return {
        "channel": channel,
        "config": masked_config,
        "title_template": data.get("title_template") or DEFAULT_TITLE_TEMPLATE,
        "body_template": data.get("body_template") or DEFAULT_BODY_TEMPLATE,
        "updated_at": data.get("updated_at"),
        "available_variables": PUSH_VARIABLES,
        "channels": channel_specs(),
        "default_title_template": DEFAULT_TITLE_TEMPLATE,
        "default_body_template": DEFAULT_BODY_TEMPLATE,
    }


def _independent_message(
    config_data: dict[str, object],
    module_name: str,
    module_key: str,
    *,
    event: str,
    status_text: str,
    result: str,
    account: str,
    duration: str,
    error: str,
    summary: str,
    details: str,
) -> tuple[str, str, PushSendResult | None]:
    channel = str(config_data["channel"])
    if channel == "none":
        return "", "", {
            "sent": False,
            "channel": channel,
            "reason": "未配置全局推送渠道",
        }
    variables = {
        "event": EVENT_LABELS.get(event, event),
        "module_name": module_name,
        "module_key": module_key,
        "account": account or "—",
        "status": status_text,
        "result": result,
        "duration": duration,
        "error": error,
        "time": datetime.now(settings.timezone_info).strftime("%Y-%m-%d %H:%M:%S"),
        "summary": summary,
        "details": details,
    }
    title = render_template(str(config_data["title_template"]), variables)
    body = render_template(str(config_data["body_template"]), variables)
    return title, body, None


async def _persist_independent_record(
    *,
    module_id: int,
    module_key: str,
    module_name: str,
    channel: str,
    title: str,
    body: str,
    result_data: PushSendResult,
) -> None:
    try:
        async with SessionLocal() as db:
            db.add(
                PushRecord(
                    kind="independent",
                    channel=channel,
                    module_id=module_id,
                    module_key=module_key,
                    module_name=module_name,
                    cycle_id=datetime.now(settings.timezone_info).date().isoformat(),
                    status="success" if result_data.get("sent") else "failed",
                    idempotency_key=make_idempotency_key(
                        "independent-audit",
                        module_id,
                        datetime.now(settings.timezone_info).date().isoformat(),
                        title,
                        time.time_ns(),
                    ),
                    title=title or None,
                    body=body or None,
                    response=redact_text(
                        json.dumps(result_data, ensure_ascii=False)[
                            : settings.push_response_max_chars
                        ]
                    ),
                    error=None
                    if result_data.get("sent")
                    else redact_text(
                        str(result_data.get("error") or result_data.get("reason") or "")
                    ),
                )
            )
            await db.commit()
    except Exception:
        logger.exception("写入独立推送记录失败")


async def send_independent_module(
    module_id: int,
    *,
    event: str,
    status_text: str,
    result: str,
    account: str = "—",
    duration: str = "—",
    error: str = "",
    summary: str = "",
    details: str = "",
    trigger: str = "schedule",
) -> PushSendResult:
    """Send one immediate independent notification and persist its audit row."""
    try:
        async with SessionLocal() as db:
            module = await db.get(Module, module_id)
            if module is None:
                return {"sent": False, "reason": "模块不存在"}
            config_data = await load_push_config(db)
            module_name, module_key = module.name, module.key
            raw_config = config_data["config"]
    except Exception as exc:
        logger.warning("读取独立推送配置失败：%s", exc)
        return {"sent": False, "reason": "读取推送配置失败"}

    title, body, empty_result = _independent_message(
        config_data,
        module_name,
        module_key,
        event=event,
        status_text=status_text,
        result=result,
        account=account,
        duration=duration,
        error=error,
        summary=summary,
        details=details,
    )
    channel = str(config_data["channel"])
    result_data = empty_result or await send_message(
        channel, raw_config, title, body
    )
    await _persist_independent_record(
        module_id=module_id,
        module_key=module_key,
        module_name=module_name,
        channel=channel,
        title=title,
        body=body,
        result_data=result_data,
    )
    await asyncio.to_thread(
        ring_log.append_push,
        (
            f"独立推送 module={module_key} trigger={trigger} "
            f"sent={bool(result_data.get('sent'))} channel={channel}"
        ),
        "INFO" if result_data.get("sent") else "WARNING",
    )
    return result_data

"""Acme 每日签到 —— 进阶多账号模块模板（平台标准用法）。

平台负责的部分（模块代码不需要重复实现）：

* 多账号列表、顺序串行执行、每个账号之间随机等待 2–5 分钟；
* 每个账号独立的生命周期与超时；
* 每日 / 每周 / 每月等周期，在起始日的时间窗内随机生成执行时间；
* 全局推送渠道、模块推送开关、模板渲染、失败重试与告警；
* 账号标识脱敏展示、参数加密、执行日志与结果汇总。

模块只需要实现一个账号的一次 ``run(params)``。本模板演示：

1. 优先复用已有 Cookie / Token；
2. 识别 HTTP 401/403 或业务响应中的「登录失效」，用账号密码重新登录；
3. 对网络错误、429、5xx 做带抖动的指数退避重试；
4. 统一超时控制与异常分类；
5. 日志中不出现密码、Cookie、Token 明文。

默认开启内置模拟模式（httpx.MockTransport），可以在不访问任何真实平台的情况下
完整跑通「Cookie 过期 → 自动登录刷新 → 再次签到」。
接入真实平台时，请修改文件顶部的 API 路径、登录 payload、成功码映射。
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)
# 避免 httpx 的 INFO 请求日志把带签名的 URL / Token 写进执行日志。
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# 按目标平台修改的适配常量
# ---------------------------------------------------------------------------
DEFAULT_API_BASE = "https://api.example.com"
CHECKIN_PATH = "/api/checkin"
LOGIN_PATH = "/api/login"

AUTH_ERROR_CODES = {
    401,
    403,
    "401",
    "403",
    "not_login",
    "unauthorized",
    "token_expired",
    "session_expired",
}
SUCCESS_CODES = {0, 200, "0", "200", None}


class ModuleError(RuntimeError):
    """可预期的业务失败。"""


class ModuleConfigError(ModuleError):
    """配置不完整或配置方式错误。"""


class AuthExpiredError(ModuleError):
    """需要重新登录。"""


class RetryableError(ModuleError):
    """重试耗尽后仍失败。"""


def _mask(value: str, prefix: int = 4, suffix: int = 2) -> str:
    value = (value or "").strip()
    if not value:
        return "(空)"
    if len(value) <= prefix + suffix + 3:
        return value[:2] + "***"
    return f"{value[:prefix]}***{value[-suffix:]}"


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default


class AcmeClient:
    """带重试与会话刷新的异步 HTTP 客户端骨架。"""

    def __init__(
        self,
        base_url: str,
        *,
        cookie: str,
        account: str,
        password: str,
        timeout: float,
        max_retries: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cookie = cookie
        self.account = account
        self.password = password
        self.max_retries = max(1, max_retries)
        self.total_requests = 0
        headers = {
            "Accept": "application/json",
            "User-Agent": "DailyCheckin/2.0 (+advanced-checkin-template)",
        }
        if cookie:
            headers["Cookie"] = cookie
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(max(5.0, timeout)),
            follow_redirects=True,
            headers=headers,
            transport=transport,
        )

    async def __aenter__(self) -> "AcmeClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    def _retry_delay(self, attempt: int, response: httpx.Response | None = None) -> float:
        retry_after = response.headers.get("Retry-After") if response is not None else None
        if retry_after:
            try:
                return min(15.0, max(0.5, float(retry_after)))
            except ValueError:
                pass
        base = min(8.0, 0.8 * (2 ** (attempt - 1)))
        return base + random.uniform(0, 0.35)

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """发送请求，对网络错误 / 429 / 5xx 进行重试。"""
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            self.total_requests += 1
            try:
                response = await self._client.request(method, path, **kwargs)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                delay = self._retry_delay(attempt)
                logger.warning(
                    "请求异常（%s），第 %s/%s 次尝试，%.1f 秒后重试",
                    type(exc).__name__,
                    attempt,
                    self.max_retries,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            if response.status_code in {401, 403}:
                raise AuthExpiredError(f"HTTP {response.status_code} 登录态失效")

            if response.status_code == 429 or response.status_code >= 500:
                last_error = ModuleError(f"HTTP {response.status_code}")
                if attempt >= self.max_retries:
                    break
                delay = self._retry_delay(attempt, response)
                logger.warning(
                    "服务端返回 %s，第 %s/%s 次尝试，%.1f 秒后重试",
                    response.status_code,
                    attempt,
                    self.max_retries,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            if response.status_code >= 400:
                body = response.text.replace("\n", " ")[:300]
                raise ModuleError(f"HTTP {response.status_code}：{body}")

            try:
                data = response.json()
            except ValueError as exc:
                raise ModuleError("接口返回了非 JSON 内容，请检查接口地址或风控页面") from exc

            if isinstance(data, dict) and data.get("code") in AUTH_ERROR_CODES:
                raise AuthExpiredError(
                    str(data.get("message") or data.get("msg") or "登录态失效")
                )
            if not isinstance(data, dict):
                return {"data": data}
            return data

        detail = str(last_error) if last_error else "未知网络错误"
        raise RetryableError(
            f"请求 {path} 在 {self.max_retries} 次尝试后仍失败：{detail}"
        )

    async def login(self) -> None:
        """使用账号密码刷新会话。

        真实接入时需要同步修改 LOGIN_PATH、登录 payload 字段名以及 token /
        Set-Cookie 的读取方式。
        """
        if not self.account or not self.password:
            raise AuthExpiredError("Cookie 已过期，但未配置账号或密码，无法自动刷新")

        logger.info("尝试使用账号 %s 重新登录 …", _mask(self.account))
        data = await self._request(
            "POST",
            LOGIN_PATH,
            json={"username": self.account, "password": self.password},
        )

        token = None
        if isinstance(data, dict):
            token = data.get("token") or data.get("access_token")
            payload = data.get("data")
            if not token and isinstance(payload, dict):
                token = payload.get("token") or payload.get("access_token")
        if token:
            self._client.headers["Authorization"] = f"Bearer {token}"

        cookies = {cookie.name: cookie.value for cookie in self._client.cookies.jar}
        if cookies:
            self.cookie = "; ".join(f"{name}={value}" for name, value in cookies.items())
            self._client.headers["Cookie"] = self.cookie

        if not token and not cookies:
            raise ModuleError("登录接口未返回 token 或 Cookie，请检查真实接口适配")
        logger.info("会话刷新成功（%s）", "Cookie" if cookies else "Bearer Token")

    async def checkin(self) -> dict[str, Any]:
        """执行签到并解析业务结果。"""
        data = await self._request("POST", CHECKIN_PATH)
        code = data.get("code")
        if code not in SUCCESS_CODES:
            message = str(data.get("message") or data.get("msg") or f"业务错误码 {code}")
            raise ModuleError(message)

        payload = data.get("data")
        if not isinstance(payload, dict):
            payload = {}
        points = payload.get("points", data.get("points"))
        message = str(
            payload.get("message")
            or data.get("message")
            or data.get("msg")
            or "签到成功"
        )
        return {"message": message, "points": points}


def _build_simulation_transport() -> httpx.MockTransport:
    """模拟一次完整的 Cookie 过期 → 登录 → 重试签到流程。"""
    state = {"checkin_calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith(CHECKIN_PATH):
            state["checkin_calls"] += 1
            if state["checkin_calls"] == 1:
                return httpx.Response(
                    401,
                    json={"code": 401, "message": "session expired"},
                    headers={"content-type": "application/json"},
                )
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "message": "模拟签到成功",
                    "data": {"points": 12, "days": 42},
                },
                headers={"content-type": "application/json"},
            )
        if path.endswith(LOGIN_PATH):
            return httpx.Response(
                200,
                json={"code": 0, "token": "simulated-bearer-token"},
                headers={
                    "content-type": "application/json",
                    "set-cookie": "simulated_session=refreshed; Path=/; HttpOnly",
                },
            )
        return httpx.Response(404, json={"code": 404, "message": "not found"})

    return httpx.MockTransport(handler)


async def _execute_checkin(
    *,
    simulate: bool,
    api_base: str,
    account: str,
    password: str,
    cookie: str,
    timeout: float,
    max_retries: int,
) -> tuple[str, dict[str, Any]]:
    if simulate:
        account = account or "simulated-user"
        password = password or "simulated-password"
        cookie = cookie or "simulated_session=expired"
        api_base = "https://simulation.invalid"
        transport: httpx.AsyncBaseTransport | None = _build_simulation_transport()
        logger.info("模拟模式：使用内置 MockTransport，不会发起真实网络请求")
    else:
        if not api_base.startswith(("http://", "https://")):
            raise ModuleConfigError("API 根地址必须以 http:// 或 https:// 开头")
        if not cookie and not (account and password):
            raise ModuleConfigError(
                "真实模式至少需要提供 Cookie，或同时提供账号与密码"
            )
        transport = None
        logger.info("真实模式：目标 API = %s", api_base)

    logger.info(
        "账号=%s，Cookie=%s，超时=%ss，最大尝试=%s",
        _mask(account),
        _mask(cookie),
        timeout,
        max_retries,
    )

    auth_refreshed = False
    client = AcmeClient(
        api_base,
        cookie=cookie,
        account=account,
        password=password,
        timeout=timeout,
        max_retries=max_retries,
        transport=transport,
    )
    async with client:
        try:
            result = await client.checkin()
        except AuthExpiredError:
            logger.warning("检测到登录态失效，准备自动刷新 Cookie …")
            await client.login()
            auth_refreshed = True
            result = await client.checkin()
            logger.info("刷新会话后重新签到成功")

    extras = {
        "auth_refreshed": auth_refreshed,
        "points": result.get("points"),
        "request_count": client.total_requests,
    }
    return result["message"], extras


async def run(params: dict[str, Any]) -> dict[str, Any]:
    """执行一个账号的一次签到。

    平台会在多账号模式下为每个账号分别调用本函数，并负责账号之间的随机等待。
    不要在模块里遍历账号列表，也不要自己发送平台级推送。
    """
    simulate = _as_bool(params.get("simulate"), True)
    api_base = str(params.get("api_base") or DEFAULT_API_BASE).strip()
    account = str(params.get("account") or "").strip()
    password = str(params.get("password") or "")
    cookie = str(params.get("cookie") or "").strip()
    max_retries = _as_int(params.get("max_retries"), 2, 1, 5)
    timeout = float(_as_int(params.get("request_timeout"), 20, 5, 60))

    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info("=" * 56)
    logger.info("Acme 签到模板开始运行（%s）", started_at)
    logger.info("=" * 56)

    success = False
    message = "未知错误"
    extras: dict[str, Any] = {"simulated": simulate}

    try:
        message, execution_extra = await _execute_checkin(
            simulate=simulate,
            api_base=api_base,
            account=account,
            password=password,
            cookie=cookie,
            timeout=timeout,
            max_retries=max_retries,
        )
        success = True
        extras.update(execution_extra)
    except ModuleConfigError as exc:
        message = f"配置错误：{exc}"
        logger.error(message)
    except AuthExpiredError as exc:
        message = f"登录态失效且自动刷新失败：{exc}"
        logger.error(message)
    except RetryableError as exc:
        message = f"网络请求失败：{exc}"
        logger.error(message)
    except ModuleError as exc:
        message = f"签到失败：{exc}"
        logger.error(message)
    except Exception as exc:  # noqa: BLE001 - 模块入口必须兜底
        message = f"未预期错误：{type(exc).__name__}: {exc}"
        logger.exception("签到模板发生未处理异常")

    if success:
        logger.info("签到成功：%s", message)
    else:
        logger.warning("签到未成功：%s", message)

    logger.info("=" * 56)
    logger.info("执行结束：%s", "成功" if success else "失败")
    logger.info("=" * 56)

    return {
        "success": success,
        "message": message,
        **extras,
    }

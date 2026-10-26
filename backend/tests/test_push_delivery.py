"""Push channel adapters, exercised with a fake httpx client (no network)."""

from __future__ import annotations

import pytest

from app.services import push as push_module


class FakeResponse:
    def __init__(self, data: dict | None = None, status_code: int = 200) -> None:
        self._data = data if data is not None else {"code": 0}
        self.status_code = status_code
        self.text = "{}"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._data


class FakeClient:
    calls: list[dict] = []
    response_data: dict = {"code": 0}

    def __init__(self, **_kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, **kwargs):
        self.__class__.calls.append({"url": url, **kwargs})
        return FakeResponse(self.__class__.response_data)


@pytest.fixture(autouse=True)
def fake_httpx(monkeypatch):
    FakeClient.calls = []
    FakeClient.response_data = {"code": 0}
    monkeypatch.setattr(push_module.httpx, "AsyncClient", FakeClient)
    return FakeClient


@pytest.mark.asyncio
async def test_all_push_channels_build_requests(fake_httpx) -> None:
    bark = await push_module.send_message(
        "bark", {"key": "device-key"}, "标题", "正文"
    )
    assert bark["sent"] is True
    assert fake_httpx.calls[-1]["url"] == "https://api.day.app/push"
    assert fake_httpx.calls[-1]["json"]["device_key"] == "device-key"

    serverchan = await push_module.send_message(
        "serverchan", {"send_key": "SCT123"}, "标题", "正文"
    )
    assert serverchan["sent"] is True
    assert "SCT123" in fake_httpx.calls[-1]["url"]

    pushplus = await push_module.send_message(
        "pushplus", {"token": "token123"}, "标题", "正文"
    )
    assert pushplus["sent"] is True
    assert fake_httpx.calls[-1]["json"]["token"] == "token123"

    dingtalk = await push_module.send_message(
        "dingtalk",
        {
            "webhook": "https://oapi.dingtalk.com/robot/send?access_token=abc",
            "secret": "SEC123",
        },
        "标题",
        "正文",
    )
    assert dingtalk["sent"] is True
    dingtalk_call = fake_httpx.calls[-1]
    assert "timestamp=" in dingtalk_call["url"] and "sign=" in dingtalk_call["url"]
    assert dingtalk_call["json"]["msgtype"] == "markdown"

    feishu = await push_module.send_message(
        "feishu",
        {
            "webhook": "https://open.feishu.cn/open-apis/bot/v2/hook/abc",
            "secret": "FEISHU123",
        },
        "标题",
        "正文",
    )
    assert feishu["sent"] is True
    feishu_call = fake_httpx.calls[-1]
    assert feishu_call["json"]["msg_type"] == "text"
    assert "timestamp" in feishu_call["json"] and "sign" in feishu_call["json"]


@pytest.mark.asyncio
async def test_business_error_is_returned_without_crashing(fake_httpx) -> None:
    fake_httpx.response_data = {"code": 400, "message": "bad token"}
    result = await push_module.send_message(
        "bark", {"key": "device-key"}, "标题", "正文"
    )
    assert result["sent"] is False
    assert "错误" in result["error"]
    # send_message retries once, then gives up.
    assert len(fake_httpx.calls) == 2

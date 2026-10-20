"""Built-in push channel metadata shared without importing the push service."""

from __future__ import annotations


CHANNEL_SPECS: list[dict[str, object]] = [
    {
        "channel": "none",
        "label": "不推送",
        "fields": [],
    },
    {
        "channel": "bark",
        "label": "Bark",
        "fields": [
            {
                "key": "key",
                "label": "Bark Device Key",
                "required": True,
                "secret": True,
                "placeholder": "例如 pGZxxxxxxx",
                "help": "通过 Bark App 获取的 device key，发送到官方 api.day.app。",
            }
        ],
    },
    {
        "channel": "serverchan",
        "label": "Server 酱",
        "fields": [
            {
                "key": "send_key",
                "label": "SendKey",
                "required": True,
                "secret": True,
                "placeholder": "SCTxxxxx",
                "help": "Server 酱 Turbo 版的 SendKey。",
            }
        ],
    },
    {
        "channel": "pushplus",
        "label": "PushPlus",
        "fields": [
            {
                "key": "token",
                "label": "Token",
                "required": True,
                "secret": True,
                "placeholder": "PushPlus token",
                "help": "PushPlus 个人 token，发送到 www.pushplus.plus。",
            }
        ],
    },
    {
        "channel": "dingtalk",
        "label": "钉钉机器人",
        "fields": [
            {
                "key": "webhook",
                "label": "Webhook",
                "required": True,
                "secret": True,
                "placeholder": "https://oapi.dingtalk.com/robot/send?access_token=...",
                "help": "仅允许钉钉官方域名，避免服务端请求任意地址。",
            },
            {
                "key": "secret",
                "label": "加签密钥（可选）",
                "required": False,
                "secret": True,
                "placeholder": "SECxxxxxxxx",
                "help": "机器人安全设置使用「加签」时填写，使用 HMAC-SHA256 签名。",
            },
        ],
    },
    {
        "channel": "feishu",
        "label": "飞书机器人",
        "fields": [
            {
                "key": "webhook",
                "label": "Webhook",
                "required": True,
                "secret": True,
                "placeholder": "https://open.feishu.cn/open-apis/bot/v2/hook/...",
                "help": "仅允许飞书 / Lark 官方域名。",
            },
            {
                "key": "secret",
                "label": "签名校验密钥（可选）",
                "required": False,
                "secret": True,
                "placeholder": "自定义机器人签名密钥",
                "help": "开启签名校验时填写，按飞书机器人签名规则计算。",
            },
        ],
    },
]


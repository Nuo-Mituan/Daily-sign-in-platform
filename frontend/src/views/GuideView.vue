<template>
  <div class="page-shell guide-page">
    <header class="page-header">
      <div>
        <span class="eyebrow">DEVELOPER DOCS</span>
        <h1 class="page-title">模块开发指南</h1>
        <p class="page-subtitle">用两个文件和一段 Python，把任意签到流程接入签到云台。</p>
      </div>
      <div class="header-actions">
        <a href="/docs" target="_blank" rel="noopener" class="docs-link">
          <el-icon><Document /></el-icon>
          打开 API 文档
        </a>
      </div>
    </header>

    <section class="guide-hero">
      <div class="guide-hero-copy">
        <span class="hero-tag"><i></i>PLUGIN SPEC · V1</span>
        <h2>把任意签到，<br /><span>装进一个模块。</span></h2>
        <p>
          模块就是一个普通目录：<code>config.json</code> 描述参数与默认随机时间窗，
          <code>main.py</code> 实现异步签到逻辑。平台负责参数表单渲染、加密存储、调度与日志。
        </p>
        <div class="hero-chips">
          <span>热插拔安装</span>
          <span>随机时间调度</span>
          <span>stdout 实时捕获</span>
          <span>异步 timeout 保护</span>
        </div>
      </div>
      <div class="hero-code">
        <div class="hero-code-bar">
          <span class="hero-code-dots"><i></i><i></i><i></i></span>
          <span>main.py</span>
          <span class="hero-code-live">ASYNC</span>
        </div>
        <pre><code>async def run(params: dict) -> dict:
    cookie = params.get("cookie", "")
    if not cookie:
        return {
            "success": False,
            "message": "Cookie 为空"
        }

    print("正在签到 …")
    await do_checkin(cookie)

    return {
        "success": True,
        "message": "签到成功"
    }</code></pre>
      </div>
    </section>

    <div class="guide-layout">
      <aside class="guide-nav">
        <span class="nav-title">目录</span>
        <a v-for="(item, index) in navItems" :key="item.id" :href="`#${item.id}`">
          <span>{{ String(index + 1).padStart(2, '0') }}</span>
          {{ item.label }}
        </a>
        <div class="nav-note">
          <el-icon><InfoFilled /></el-icon>
          示例模块位于仓库 <code>modules/</code> 目录，可直接参考。
        </div>
      </aside>

      <article class="guide-content">
        <section id="structure" class="doc-section panel">
          <div class="doc-heading">
            <span class="doc-index">01</span>
            <div>
              <h3>目录结构</h3>
              <p>每个子目录就是一个模块，目录名即模块标识（key）。</p>
            </div>
          </div>
          <pre class="code-block"><code>{{ structureExample }}</code></pre>
          <div class="doc-callout">
            <el-icon><InfoFilled /></el-icon>
            目录名建议只使用字母、数字、下划线和短横线。通过 ZIP 上传时，平台可以自动推断名称，
            也可以在表单里指定模块标识。
          </div>
        </section>

        <section id="config" class="doc-section panel">
          <div class="doc-heading">
            <span class="doc-index">02</span>
            <div>
              <h3>config.json</h3>
              <p>模块元信息、参数表单定义、随机时间默认值与多账号开关。</p>
            </div>
          </div>
          <div class="table-scroll">
            <table class="doc-table">
              <thead>
                <tr>
                  <th>字段</th>
                  <th>类型</th>
                  <th>必填</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="field in configFields" :key="field.name">
                  <td><code>{{ field.name }}</code></td>
                  <td>{{ field.type }}</td>
                  <td>
                    <span :class="field.required ? 'required-yes' : 'required-no'">
                      {{ field.required ? '是' : '否' }}
                    </span>
                  </td>
                  <td>{{ field.desc }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="doc-callout">
            <el-icon><InfoFilled /></el-icon>
            <code>directory_name</code> 表示模块在 <code>modules/</code> 下的真实物理目录名；
            不填时回退为 API key。修改目录名后重新扫描模块即可同步数据库，
            图标接口会按该字段读取 <code>modules/&lt;directory_name&gt;/</code>。
            该值只能包含字母、数字、下划线和短横线，禁止路径分隔符或 <code>..</code>。
            目录改名并需保留原 API key 时，必须同时声明 <code>legacy_key</code>；
            平台不会仅凭显示名称自动复用旧记录。
          </div>
          <pre class="code-block"><code>{{ configExample }}</code></pre>
          <div class="doc-callout">
            <el-icon><Timer /></el-icon>
            <code>default_start_time</code> / <code>default_end_time</code> 使用 24 小时制
            <code>HH:mm</code>，<code>default_repeat_cycle</code> 指定每日 / 每周 /
            每月15日 / 每月 / 每年；<code>default_repeat_sub_value</code> 设置子选项默认值：
            周几（1-7）、每月几号（1-28）或月-日（如 2-29）。新建模块会以它们作为初始值，
            用户可在网页端修改，平台会在执行日的时间窗内随机选择执行时间。
          </div>
        </section>

        <section id="params" class="doc-section panel">
          <div class="doc-heading">
            <span class="doc-index">03</span>
            <div>
              <h3>参数定义</h3>
              <p><code>params</code> 数组中的每一项都会在网页端渲染成对应的表单控件。</p>
            </div>
          </div>
          <div class="type-grid">
            <div v-for="type in paramTypes" :key="type.type" class="type-card">
              <div class="type-head">
                <code>{{ type.type }}</code>
                <span>{{ type.control }}</span>
              </div>
              <p>{{ type.desc }}</p>
            </div>
          </div>
          <div class="table-scroll">
            <table class="doc-table">
              <thead>
                <tr>
                  <th>参数字段</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="field in paramFields" :key="field.name">
                  <td><code>{{ field.name }}</code></td>
                  <td>{{ field.desc }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="doc-callout">
            <el-icon><Lock /></el-icon>
            用户保存的所有参数都会使用平台密钥加密后写入数据库；<code>main.py</code>
            通过 <code>params</code> 拿到的是解密后的值。不要在日志里打印密码或完整 Cookie。
          </div>
          <div class="doc-callout">
            <el-icon><Connection /></el-icon>
            多账号模式下，一个账号对应一次独立的 <code>run(params)</code> 调用；平台负责串行执行、
            2–5 分钟随机间隔、账号级超时、脱敏日志与结果汇总。模块无需自己循环账号列表。
          </div>
          <div class="doc-callout">
            <el-icon><Monitor /></el-icon>
            签到成功、失败、多账号部分失败与随机时间生成失败由平台统一推送。请在「用户设置」配置
            全局渠道，并在模块页打开推送开关；模块内不需要实现推送逻辑。
          </div>
        </section>

        <section id="entry" class="doc-section panel">
          <div class="doc-heading">
            <span class="doc-index">04</span>
            <div>
              <h3>main.py 入口规范</h3>
              <p>必须定义入口函数 <code>run</code>，接收参数 dict 并返回结果 dict。
                多账号模式下平台会按账号顺序逐个调用它。</p>
            </div>
          </div>
          <pre class="code-block"><code>{{ entryExample }}</code></pre>
          <div class="rule-grid">
            <div class="rule">
              <span class="rule-icon"><el-icon><Timer /></el-icon></span>
              <div>
                <strong>执行超时</strong>
                <p>默认 300 秒，超时会被中断并记录为失败，可在服务端环境变量中调整。</p>
              </div>
            </div>
            <div class="rule">
              <span class="rule-icon"><el-icon><Document /></el-icon></span>
              <div>
                <strong>返回结构</strong>
                <p>必须包含布尔型 <code>success</code>，以及可读的 <code>message</code>。</p>
              </div>
            </div>
            <div class="rule">
              <span class="rule-icon"><el-icon><Monitor /></el-icon></span>
              <div>
                <strong>输出捕获</strong>
                <p><code>print()</code> 与标准 <code>logging</code> 日志都会被实时推送到网页端。</p>
              </div>
            </div>
            <div class="rule">
              <span class="rule-icon"><el-icon><Connection /></el-icon></span>
              <div>
                <strong>多文件与相对导入</strong>
                <p>模块以包的形式加载，支持 <code>from .helpers import xxx</code>。</p>
              </div>
            </div>
          </div>
          <div class="doc-subheading">
            <h4>返回值示例</h4>
            <p>除 success / message 外的字段会作为附加数据打印在日志中。</p>
          </div>
          <pre class="code-block"><code>{{ returnExample }}</code></pre>
        </section>

        <section id="logging" class="doc-section panel">
          <div class="doc-heading">
            <span class="doc-index">05</span>
            <div>
              <h3>日志、异常与退出码</h3>
              <p>让失败信息足够清晰，是模块开发中最重要的部分之一。</p>
            </div>
          </div>
          <ul class="doc-list">
            <li>
              主动失败时返回 <code>success: False</code>，并把原因写进 <code>message</code>，
              例如「Cookie 已过期」。
            </li>
            <li>
              未捕获异常会被平台捕获，traceback 写入执行日志，模块状态记为失败。
            </li>
            <li>
              日志以流的方式实时显示，SSE 连接断开后会从内存缓冲区恢复；
              完整输出同时写入数据库与 <code>logs/executions/&lt;key&gt;/</code> 文件。
            </li>
            <li>
              建议在关键步骤打印进度，例如登录、领取、校验结果，方便日后排查。
            </li>
            <li>
              不要在模块加载阶段做网络请求。将耗时操作放在 <code>run()</code> 内，
              否则导入失败会直接导致模块不可用。
            </li>
          </ul>
          <pre class="code-block"><code>{{ errorExample }}</code></pre>
        </section>

        <section id="install" class="doc-section panel">
          <div class="doc-heading">
            <span class="doc-index">06</span>
            <div>
              <h3>安装、更新与调试</h3>
              <p>两种安装方式都支持热加载，不需要重启容器。</p>
            </div>
          </div>
          <div class="install-grid">
            <div class="install-card">
              <span class="install-num">A</span>
              <h4>ZIP 上传</h4>
              <ol>
                <li>将模块目录压缩为 ZIP，保留 config.json 与 main.py。</li>
                <li>在「签到模块」页点击「上传模块」。</li>
                <li>安装后模块默认禁用，填写参数并启用即可。</li>
              </ol>
            </div>
            <div class="install-card">
              <span class="install-num">B</span>
              <h4>挂载目录扫描</h4>
              <ol>
                <li>把模块目录放到宿主机 <code>./modules/</code> 下。</li>
                <li>在网页端点击「扫描目录」。</li>
                <li>平台会同步新增、更新或标记异常模块。</li>
              </ol>
            </div>
          </div>
          <div class="doc-callout">
            <el-icon><Warning /></el-icon>
            覆盖同名模块时，代码文件会被替换，但数据库中的账号与随机调度配置会保留。
            删除模块会同时删除模块目录和历史执行记录。
          </div>
        </section>

        <section id="security" class="doc-section panel">
          <div class="doc-heading">
            <span class="doc-index">07</span>
            <div>
              <h3>安全与最佳实践</h3>
              <p>平台执行的是你自己安装的 Python 代码，请像对待服务器脚本一样对待模块。</p>
            </div>
          </div>
          <div class="security-box">
            <div class="security-item">
              <el-icon><Lock /></el-icon>
              <div>
                <strong>只安装可信模块</strong>
                <p>模块代码以服务进程权限运行，可访问容器内文件与网络。不要上传来源不明的代码。</p>
              </div>
            </div>
            <div class="security-item">
              <el-icon><Key /></el-icon>
              <div>
                <strong>不要更换 SECRET_KEY</strong>
                <p>参数加密密钥由 SECRET_KEY 派生。更换后旧参数将无法解密，需要重新填写。</p>
              </div>
            </div>
            <div class="security-item">
              <el-icon><Hide /></el-icon>
              <div>
                <strong>避免泄露敏感信息</strong>
                <p>日志会被持久化保存并展示在网页上，切勿打印完整 Cookie、Token 或密码。</p>
              </div>
            </div>
          </div>
          <div class="closing-card">
            <div>
              <strong>准备好写第一个模块了吗？</strong>
              <p>从复制 <code>modules/demo_checkin</code> 开始，修改 config.json 和 main.py 即可。</p>
            </div>
            <router-link to="/modules" class="closing-link">
              前往模块库 <el-icon><ArrowRight /></el-icon>
            </router-link>
          </div>
        </section>
      </article>
    </div>
  </div>
</template>

<script setup>
import {
  ArrowRight,
  Connection,
  Document,
  Hide,
  InfoFilled,
  Key,
  Lock,
  Monitor,
  Timer,
  Warning,
} from '@element-plus/icons-vue'

const navItems = [
  { id: 'structure', label: '目录结构' },
  { id: 'config', label: 'config.json' },
  { id: 'params', label: '参数定义' },
  { id: 'entry', label: '入口规范' },
  { id: 'logging', label: '日志与异常' },
  { id: 'install', label: '安装与调试' },
  { id: 'security', label: '安全实践' },
]

const configFields = [
  { name: 'name', type: 'string', required: true, desc: '模块显示名称，例如「某平台签到」。' },
  { name: 'description', type: 'string', required: true, desc: '一句话说明模块用途，展示在模块卡片上。' },
  { name: 'author', type: 'string', required: false, desc: '作者或维护者名称。' },
  { name: 'version', type: 'string', required: false, desc: '模块版本号，默认 1.0.0。' },
  { name: 'icon', type: 'string', required: false, desc: '模块图标：Emoji、./favicon.png/.jpg/.jpeg/.webp/.ico/.svg、Base64 Data URI 或 HTTPS URL，默认 🧩。' },
  { name: 'directory_name', type: 'string', required: false, desc: '物理模块目录名，最多 80 字符；为空时回退使用模块 key。用于 API key 与目录名独立演进。' },
  { name: 'legacy_key', type: 'string', required: false, desc: '目录改名时显式指定要保留的旧 API key；仅当旧 key 对应目录已不存在时生效，避免同名模块串用配置。' },
  { name: 'default_start_time', type: 'string', required: true, desc: '默认开始时间 HH:mm，例如 08:00。' },
  { name: 'default_end_time', type: 'string', required: true, desc: '默认结束时间 HH:mm，例如 10:00。' },
  { name: 'default_repeat_cycle', type: 'string', required: false, desc: 'daily / weekly / monthly_15 / monthly / yearly。' },
  { name: 'default_repeat_sub_value', type: 'string', required: false, desc: '每周填 1-7；每月填 1-28；每年填 M-D（如 2-29）。' },
  { name: 'multi_account', type: 'boolean', required: false, desc: '为 true 时 params 会按账号重复渲染并串行执行。' },
  { name: 'params', type: 'array', required: false, desc: '参数定义数组；多账号模式下每个账号各填写一组。' },
]

const paramFields = [
  { name: 'key', desc: '参数键名，会作为 params 字典的 key，仅支持字母、数字、下划线。' },
  { name: 'label', desc: '网页表单上显示的中文标签。' },
  { name: 'type', desc: '控件类型：text / textarea / password / select / switch / number。' },
  { name: 'required', desc: '是否为必填项；启用模块和保存时都会校验。' },
  { name: 'default', desc: '默认值。select 参数应与某个 option 的 value 对应。' },
  { name: 'placeholder', desc: '输入框占位提示。' },
  { name: 'help', desc: '显示在控件下方的帮助文字，适合填写获取 Cookie 的说明。' },
  { name: 'options', desc: 'select 专用。支持 ["a","b"] 或 [{ "label":"国服","value":"cn" }]。' },
  { name: 'min / max / step', desc: 'number 专用，限制数值范围与步长。' },
  { name: 'rows', desc: 'textarea 专用，控制默认显示行数。' },
  { name: 'account_label', desc: '多账号模式可选：标记用于日志脱敏展示的账号标识字段。' },
]

const paramTypes = [
  { type: 'text', control: '单行输入框', desc: '适合账号、Token、推送 Key 等短文本。' },
  { type: 'textarea', control: '多行文本域', desc: '适合 Cookie、消息模板等长文本。' },
  { type: 'password', control: '密码输入框', desc: '输入默认隐藏，仍会加密存储。' },
  { type: 'select', control: '下拉选择器', desc: '需提供 options；保存时校验取值。' },
  { type: 'switch', control: '开关', desc: '布尔值，适合“是否推送”等开关项。' },
  { type: 'number', control: '数字输入框', desc: '支持 min / max / step 限制。' },
]

const structureExample = `modules/
├── demo_checkin/              # 物理目录；可由 config.json 的 directory_name 指向
│   ├── config.json            # 元信息、参数定义、随机时间默认值
│   ├── main.py                # 入口：async def run(params)
│   └── helpers.py             # 可选：模块内辅助文件
└── my_checkin/
    ├── config.json
    └── main.py`

const configExample = `{
  "name": "某平台签到",
  "description": "自动完成某平台每日签到",
  "author": "your-name",
  "version": "1.0.0",
  "icon": "🎯",
  "directory_name": "my_checkin",
  "default_start_time": "08:00",
  "default_end_time": "10:00",
  "default_repeat_cycle": "daily",
  "default_repeat_sub_value": "",
  "multi_account": true,
  "params": [
    {
      "key": "cookie",
      "label": "Cookie",
      "type": "textarea",
      "required": true,
      "rows": 4,
      "account_label": true,
      "placeholder": "请填入你的 Cookie"
    },
    {
      "key": "target_level",
      "label": "目标等级",
      "type": "number",
      "default": 3,
      "min": 1,
      "max": 10
    },
    {
      "key": "verbose",
      "label": "详细日志",
      "type": "switch",
      "default": true
    }
  ]
}`

const entryExample = `"""main.py — 最小的签到模块示例。"""

from __future__ import annotations

import asyncio
from typing import Any


async def run(params: dict[str, Any]) -> dict[str, Any]:
    """
    params: 网页端保存并由平台解密后的参数
    返回:   {"success": bool, "message": str}，可附加其他字段
    """
    cookie = str(params.get("cookie", "")).strip()
    if not cookie:
        return {"success": False, "message": "Cookie 为空，请先完成配置"}

    print("开始签到 …")
    await asyncio.sleep(0.2)

    # 在这里实现真实的登录 / 签到请求（例如使用 httpx）
    # async with httpx.AsyncClient() as client:
    #     response = await client.get(url, headers={"Cookie": cookie})
    #     response.raise_for_status()

    return {
        "success": True,
        "message": "签到成功",
        "points": 10,
    }`

const returnExample = `# 成功
{
    "success": True,
    "message": "签到成功，获得 10 积分",
    "points": 10
}

# 失败
{
    "success": False,
    "message": "Cookie 已过期，请重新获取"
}

# 也可使用 msg 作为 message 的别名
{
    "success": True,
    "msg": "签到完成"
}`

const errorExample = `import logging
import traceback

logger = logging.getLogger(__name__)


async def run(params: dict) -> dict:
    try:
        result = await do_checkin(params)
        logger.info("签到结果：%s", result)
        return {"success": True, "message": "签到成功"}

    except TimeoutError:
        return {"success": False, "message": "请求超时，请稍后重试"}

    except Exception as exc:
        logger.exception("签到发生异常")
        return {
            "success": False,
            "message": f"签到失败：{type(exc).__name__}: {exc}"
        }`
</script>

<style scoped>
.guide-page {
  padding-top: 30px;
}

.docs-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 34px;
  padding: 0 13px;
  color: #6e7890;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 9px;
  font-size: 11px;
  font-weight: 600;
  box-shadow: var(--shadow-sm);
}

.docs-link:hover {
  color: var(--brand);
  border-color: #d8daf5;
}

.guide-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(360px, 0.95fr);
  gap: 34px;
  align-items: center;
  padding: 36px 38px;
  overflow: hidden;
  color: #f4f6ff;
  background:
    radial-gradient(circle at 90% 0%, rgba(99, 102, 241, 0.36), transparent 38%),
    radial-gradient(circle at 4% 100%, rgba(34, 211, 238, 0.08), transparent 30%),
    linear-gradient(132deg, #0e1527, #0a1020 58%, #0f172b);
  border-radius: 24px;
  border: 1px solid rgba(255, 255, 255, 0.05);
  box-shadow: 0 24px 60px rgba(13, 20, 40, 0.2);
}

.hero-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: rgba(166, 180, 218, 0.5);
  font-family: var(--font-mono);
  font-size: 8.5px;
  font-weight: 700;
  letter-spacing: 0.15em;
}

.hero-tag i {
  width: 4px;
  height: 4px;
  background: #818cf8;
  border-radius: 50%;
}

.guide-hero h2 {
  margin-top: 13px;
  font-size: clamp(29px, 3vw, 40px);
  font-weight: 760;
  letter-spacing: -0.04em;
  line-height: 1.22;
}

.guide-hero h2 span {
  color: transparent;
  background: linear-gradient(96deg, #a5b4fc, #7dd3fc 55%, #6ee7b7);
  -webkit-background-clip: text;
  background-clip: text;
}

.guide-hero-copy > p {
  max-width: 520px;
  margin-top: 15px;
  color: rgba(190, 203, 237, 0.52);
  font-size: 12.5px;
  line-height: 1.85;
}

.guide-hero-copy code {
  padding: 1px 5px;
  color: #b2bdfb;
  background: rgba(129, 140, 248, 0.1);
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 10.5px;
}

.hero-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 20px;
}

.hero-chips span {
  padding: 4px 9px;
  color: rgba(204, 215, 245, 0.55);
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 999px;
  font-size: 9.5px;
}

.hero-code {
  overflow: hidden;
  background: rgba(5, 10, 20, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.09);
  border-radius: 15px;
  box-shadow: 0 20px 44px rgba(0, 0, 0, 0.24);
}

.hero-code-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 13px;
  color: rgba(185, 198, 231, 0.4);
  background: rgba(255, 255, 255, 0.035);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  font-family: var(--font-mono);
  font-size: 9px;
}

.hero-code-dots {
  display: flex;
  gap: 4px;
}

.hero-code-dots i {
  width: 6px;
  height: 6px;
  background: #33415c;
  border-radius: 50%;
}

.hero-code-dots i:first-child {
  background: #f87171;
}

.hero-code-dots i:nth-child(2) {
  background: #fbbf24;
}

.hero-code-dots i:last-child {
  background: #34d399;
}

.hero-code-live {
  margin-left: auto;
  color: rgba(94, 234, 212, 0.6);
  font-size: 8px;
  letter-spacing: 0.12em;
}

.hero-code pre {
  margin: 0;
  padding: 17px 18px;
  overflow-x: auto;
  color: #c9d6ec;
  font-family: var(--font-mono);
  font-size: 10.5px;
  line-height: 1.8;
}

.guide-layout {
  display: grid;
  grid-template-columns: 190px minmax(0, 1fr);
  gap: 26px;
  align-items: start;
  margin-top: 26px;
}

.guide-nav {
  position: sticky;
  top: 96px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 16px 12px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 15px;
  box-shadow: var(--shadow-sm);
}

.nav-title {
  padding: 0 10px 8px;
  color: #a4adbe;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.12em;
}

.guide-nav a {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  color: #7c869b;
  border-radius: 7px;
  font-size: 10.5px;
  font-weight: 550;
  transition: all 0.15s ease;
}

.guide-nav a span {
  color: #c1c7d4;
  font-family: var(--font-mono);
  font-size: 8px;
}

.guide-nav a:hover {
  color: var(--brand-strong);
  background: #f7f7fe;
}

.nav-note {
  display: flex;
  align-items: flex-start;
  gap: 5px;
  margin: 12px 4px 0;
  padding: 10px;
  color: #a1a9b9;
  background: #fafbfe;
  border: 1px dashed #eaedf4;
  border-radius: 8px;
  font-size: 9px;
  line-height: 1.6;
}

.nav-note code {
  color: #7d82bd;
  font-family: var(--font-mono);
  font-size: 8.5px;
}

.guide-content {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 18px;
}

.doc-section {
  padding: 24px 26px;
  scroll-margin-top: 96px;
}

.doc-heading {
  display: flex;
  align-items: flex-start;
  gap: 13px;
  margin-bottom: 17px;
}

.doc-index {
  display: grid;
  width: 30px;
  height: 30px;
  flex: none;
  place-items: center;
  color: #6b68d8;
  background: #f1f2ff;
  border-radius: 8px;
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
}

.doc-heading h3 {
  color: #263149;
  font-size: 17px;
  font-weight: 700;
  letter-spacing: -0.015em;
}

.doc-heading p {
  margin-top: 3px;
  color: #939db0;
  font-size: 11px;
  line-height: 1.65;
}

.doc-heading code,
.doc-callout code,
.doc-list code,
.doc-subheading code,
.rule p code {
  padding: 1px 5px;
  color: #5553c4;
  background: #f3f3fd;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 9.5px;
}

.doc-section > .code-block {
  margin-top: 14px;
}

.doc-section .code-block {
  font-size: 11px;
}

.table-scroll {
  margin-top: 14px;
  overflow-x: auto;
}

.doc-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 10.5px;
}

.doc-table th {
  padding: 8px 10px;
  color: #8b95a9;
  background: #f8f9fc;
  border-bottom: 1px solid #eef1f6;
  font-size: 9.5px;
  font-weight: 650;
  text-align: left;
  white-space: nowrap;
}

.doc-table th:first-child {
  border-radius: 7px 0 0 7px;
}

.doc-table th:last-child {
  border-radius: 0 7px 7px 0;
}

.doc-table td {
  padding: 8px 10px;
  color: #748096;
  border-bottom: 1px solid #f4f6f9;
  line-height: 1.6;
}

.doc-table tr:last-child td {
  border-bottom: 0;
}

.doc-table td code {
  color: #5553c4;
  font-family: var(--font-mono);
  font-size: 9.5px;
  white-space: nowrap;
}

.required-yes {
  padding: 1px 6px;
  color: #b07218;
  background: #fdf5e7;
  border-radius: 999px;
  font-size: 8.5px;
}

.required-no {
  padding: 1px 6px;
  color: #9aa3b4;
  background: #f4f6fa;
  border-radius: 999px;
  font-size: 8.5px;
}

.doc-callout {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  margin-top: 14px;
  padding: 11px 13px;
  color: #7b86a1;
  background: #f8f9fe;
  border: 1px solid #eef0fa;
  border-radius: 9px;
  font-size: 10px;
  line-height: 1.7;
}

.doc-callout > .el-icon {
  flex: none;
  margin-top: 2px;
  color: #8886dc;
}

.type-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.type-card {
  padding: 12px 13px;
  background: #fafbfe;
  border: 1px solid #f0f2f7;
  border-radius: 10px;
}

.type-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.type-head code {
  color: #5352c2;
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
}

.type-head span {
  color: #b0b8c7;
  font-size: 8.5px;
}

.type-card p {
  margin-top: 4px;
  color: #939caf;
  font-size: 9.5px;
  line-height: 1.6;
}

.rule-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 11px;
  margin-top: 16px;
}

.rule {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 12px 13px;
  background: #fafbfe;
  border: 1px solid #f1f3f8;
  border-radius: 10px;
}

.rule-icon {
  display: grid;
  width: 27px;
  height: 27px;
  flex: none;
  place-items: center;
  color: #7c83d4;
  background: #f1f2fe;
  border-radius: 7px;
  font-size: 12px;
}

.rule strong {
  color: #5b657d;
  font-size: 10.5px;
  font-weight: 650;
}

.rule p {
  margin-top: 2px;
  color: #9ba4b6;
  font-size: 9.5px;
  line-height: 1.65;
}

.doc-subheading {
  margin-top: 20px;
}

.doc-subheading h4 {
  color: #4f5a72;
  font-size: 12px;
  font-weight: 650;
}

.doc-subheading p {
  margin-top: 2px;
  color: #99a2b4;
  font-size: 10px;
}

.doc-list {
  display: flex;
  flex-direction: column;
  gap: 9px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.doc-list li {
  position: relative;
  padding-left: 16px;
  color: #778297;
  font-size: 11px;
  line-height: 1.75;
}

.doc-list li::before {
  position: absolute;
  top: 8px;
  left: 2px;
  width: 4px;
  height: 4px;
  background: #a8aaf0;
  border-radius: 50%;
  content: "";
}

.install-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 13px;
}

.install-card {
  padding: 15px 16px;
  background: #fafbff;
  border: 1px solid #eef1f7;
  border-radius: 11px;
}

.install-num {
  display: inline-grid;
  width: 21px;
  height: 21px;
  place-items: center;
  color: #6b68d8;
  background: #f0f1fe;
  border-radius: 6px;
  font-family: var(--font-mono);
  font-size: 9px;
  font-weight: 700;
}

.install-card h4 {
  display: inline;
  margin-left: 7px;
  color: #4e596f;
  font-size: 11.5px;
  font-weight: 650;
}

.install-card ol {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin: 10px 0 0;
  padding-left: 16px;
  color: #8e98ab;
  font-size: 10px;
  line-height: 1.7;
}

.install-card code {
  padding: 1px 4px;
  color: #5a58c7;
  background: #f2f2fc;
  border-radius: 3px;
  font-family: var(--font-mono);
  font-size: 9px;
}

.security-box {
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.security-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 13px;
  background: #fafbfe;
  border: 1px solid #f1f3f8;
  border-radius: 10px;
}

.security-item > .el-icon {
  flex: none;
  margin-top: 2px;
  color: #8a8fda;
  font-size: 15px;
}

.security-item strong {
  color: #5a657d;
  font-size: 10.5px;
  font-weight: 650;
}

.security-item p {
  margin-top: 2px;
  color: #98a1b3;
  font-size: 9.5px;
  line-height: 1.65;
}

.closing-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 17px;
  padding: 16px 18px;
  color: #eef3ff;
  background:
    radial-gradient(circle at 100% 0%, rgba(99, 102, 241, 0.35), transparent 40%),
    linear-gradient(120deg, #121a2e, #0c1322);
  border-radius: 12px;
}

.closing-card strong {
  font-size: 12px;
  font-weight: 650;
}

.closing-card p {
  margin-top: 3px;
  color: rgba(190, 203, 237, 0.45);
  font-size: 9.5px;
}

.closing-card code {
  color: #a5b4fc;
  background: rgba(129, 140, 248, 0.1);
  font-family: var(--font-mono);
}

.closing-link {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: 4px;
  height: 32px;
  padding: 0 12px;
  color: #dbe4ff;
  background: rgba(255, 255, 255, 0.07);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  font-size: 10px;
  font-weight: 600;
}

.closing-link:hover {
  background: rgba(255, 255, 255, 0.12);
}

@media (max-width: 1100px) {
  .guide-hero {
    grid-template-columns: 1fr;
  }

  .hero-code {
    display: none;
  }

  .guide-layout {
    grid-template-columns: 1fr;
  }

  .guide-nav {
    position: static;
    flex-direction: row;
    overflow-x: auto;
    gap: 3px;
    padding: 8px;
  }

  .nav-title,
  .nav-note {
    display: none;
  }

  .guide-nav a {
    flex: none;
    white-space: nowrap;
  }
}

@media (max-width: 720px) {
  .guide-page {
    padding-top: 20px;
  }

  .guide-hero {
    padding: 26px 22px;
    border-radius: 19px;
  }

  .doc-section {
    padding: 19px 18px;
  }

  .type-grid {
    grid-template-columns: 1fr 1fr;
  }

  .rule-grid,
  .install-grid {
    grid-template-columns: 1fr;
  }

  .closing-card {
    align-items: flex-start;
    flex-direction: column;
  }

  .doc-table {
    min-width: 500px;
  }
}
</style>

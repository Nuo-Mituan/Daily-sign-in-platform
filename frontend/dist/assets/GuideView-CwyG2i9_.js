import{i as v,Q as f,t as g,l as y,c as _,m as k,G as S,S as T,Y as F,y as P}from"./element-plus-Bc1tBYmV.js";import{_ as j}from"./index-B-w2AANw.js";import{L as u,M as r,P as e,a0 as s,W as n,_ as l,aD as m,F as c,ae as p,$ as d,aj as b,u as i,S as V}from"./vue-Bja1UfAU.js";const A={class:"page-shell guide-page"},I={class:"page-header"},H={class:"header-actions"},N={href:"/docs",target:"_blank",rel:"noopener",class:"docs-link"},D={class:"guide-layout"},L={class:"guide-nav"},B=["href"],G={class:"nav-note"},Y={class:"guide-content"},K={id:"structure",class:"doc-section panel"},R={class:"doc-callout"},Z={id:"config",class:"doc-section panel"},M={class:"table-scroll"},O={class:"doc-table"},$={class:"doc-callout"},z={id:"params",class:"doc-section panel"},Q={class:"type-grid"},U={class:"type-head"},W={class:"table-scroll"},J={class:"doc-table"},X={class:"doc-callout"},ee={class:"doc-callout"},ae={class:"doc-callout"},se={id:"entry",class:"doc-section panel"},le={class:"rule-grid"},te={class:"rule"},ne={class:"rule-icon"},oe={class:"rule"},de={class:"rule-icon"},ie={class:"rule"},ue={class:"rule-icon"},re={class:"rule"},ce={class:"rule-icon"},pe={id:"install",class:"doc-section panel"},me={class:"doc-callout"},ve={id:"security",class:"doc-section panel"},fe={class:"security-box"},ge={class:"security-item"},ye={class:"security-item"},_e={class:"security-item"},ke={class:"closing-card"},be=`modules/
├── demo_checkin/              # 模块目录名 = 模块标识 key
│   ├── config.json            # 元信息、参数定义、随机时间默认值
│   ├── main.py                # 入口：async def run(params)
│   └── helpers.py             # 可选：模块内辅助文件
└── my_checkin/
    ├── config.json
    └── main.py`,xe=`{
  "name": "某平台签到",
  "description": "自动完成某平台每日签到",
  "author": "your-name",
  "version": "1.0.0",
  "icon": "🎯",
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
}`,qe=`"""main.py — 最小的签到模块示例。"""

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
    }`,he=`# 成功
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
}`,Ce=`import logging
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
        }`,we={__name:"GuideView",setup(Ee){const x=[{id:"structure",label:"目录结构"},{id:"config",label:"config.json"},{id:"params",label:"参数定义"},{id:"entry",label:"入口规范"},{id:"logging",label:"日志与异常"},{id:"install",label:"安装与调试"},{id:"security",label:"安全实践"}],q=[{name:"name",type:"string",required:!0,desc:"模块显示名称，例如「某平台签到」。"},{name:"description",type:"string",required:!0,desc:"一句话说明模块用途，展示在模块卡片上。"},{name:"author",type:"string",required:!1,desc:"作者或维护者名称。"},{name:"version",type:"string",required:!1,desc:"模块版本号，默认 1.0.0。"},{name:"icon",type:"string",required:!1,desc:"模块图标 emoji，默认 🧩。"},{name:"default_start_time",type:"string",required:!0,desc:"默认开始时间 HH:mm，例如 08:00。"},{name:"default_end_time",type:"string",required:!0,desc:"默认结束时间 HH:mm，例如 10:00。"},{name:"default_repeat_cycle",type:"string",required:!1,desc:"daily / weekly / monthly_15 / monthly / yearly。"},{name:"default_repeat_sub_value",type:"string",required:!1,desc:"每周填 1-7；每月填 1-28；每年填 M-D（如 2-29）。"},{name:"multi_account",type:"boolean",required:!1,desc:"为 true 时 params 会按账号重复渲染并串行执行。"},{name:"params",type:"array",required:!1,desc:"参数定义数组；多账号模式下每个账号各填写一组。"}],h=[{name:"key",desc:"参数键名，会作为 params 字典的 key，仅支持字母、数字、下划线。"},{name:"label",desc:"网页表单上显示的中文标签。"},{name:"type",desc:"控件类型：text / textarea / password / select / switch / number。"},{name:"required",desc:"是否为必填项；启用模块和保存时都会校验。"},{name:"default",desc:"默认值。select 参数应与某个 option 的 value 对应。"},{name:"placeholder",desc:"输入框占位提示。"},{name:"help",desc:"显示在控件下方的帮助文字，适合填写获取 Cookie 的说明。"},{name:"options",desc:'select 专用。支持 ["a","b"] 或 [{ "label":"国服","value":"cn" }]。'},{name:"min / max / step",desc:"number 专用，限制数值范围与步长。"},{name:"rows",desc:"textarea 专用，控制默认显示行数。"},{name:"account_label",desc:"多账号模式可选：标记用于日志脱敏展示的账号标识字段。"}],C=[{type:"text",control:"单行输入框",desc:"适合账号、Token、推送 Key 等短文本。"},{type:"textarea",control:"多行文本域",desc:"适合 Cookie、消息模板等长文本。"},{type:"password",control:"密码输入框",desc:"输入默认隐藏，仍会加密存储。"},{type:"select",control:"下拉选择器",desc:"需提供 options；保存时校验取值。"},{type:"switch",control:"开关",desc:"布尔值，适合“是否推送”等开关项。"},{type:"number",control:"数字输入框",desc:"支持 min / max / step 限制。"}];return(Se,a)=>{const o=b("el-icon"),w=b("router-link");return u(),r("div",A,[e("header",I,[a[1]||(a[1]=e("div",null,[e("span",{class:"eyebrow"},"DEVELOPER DOCS"),e("h1",{class:"page-title"},"模块开发指南"),e("p",{class:"page-subtitle"},"用两个文件和一段 Python，把任意签到流程接入签到云台。")],-1)),e("div",H,[e("a",N,[s(o,null,{default:n(()=>[s(i(v))]),_:1}),a[0]||(a[0]=l(" 打开 API 文档 ",-1))])])]),a[46]||(a[46]=m(`<section class="guide-hero" data-v-1a33ef0a><div class="guide-hero-copy" data-v-1a33ef0a><span class="hero-tag" data-v-1a33ef0a><i data-v-1a33ef0a></i>PLUGIN SPEC · V1</span><h2 data-v-1a33ef0a>把任意签到，<br data-v-1a33ef0a><span data-v-1a33ef0a>装进一个模块。</span></h2><p data-v-1a33ef0a> 模块就是一个普通目录：<code data-v-1a33ef0a>config.json</code> 描述参数与默认随机时间窗， <code data-v-1a33ef0a>main.py</code> 实现异步签到逻辑。平台负责参数表单渲染、加密存储、调度与日志。 </p><div class="hero-chips" data-v-1a33ef0a><span data-v-1a33ef0a>热插拔安装</span><span data-v-1a33ef0a>随机时间调度</span><span data-v-1a33ef0a>stdout 实时捕获</span><span data-v-1a33ef0a>异步 timeout 保护</span></div></div><div class="hero-code" data-v-1a33ef0a><div class="hero-code-bar" data-v-1a33ef0a><span class="hero-code-dots" data-v-1a33ef0a><i data-v-1a33ef0a></i><i data-v-1a33ef0a></i><i data-v-1a33ef0a></i></span><span data-v-1a33ef0a>main.py</span><span class="hero-code-live" data-v-1a33ef0a>ASYNC</span></div><pre data-v-1a33ef0a><code data-v-1a33ef0a>async def run(params: dict) -&gt; dict:
    cookie = params.get(&quot;cookie&quot;, &quot;&quot;)
    if not cookie:
        return {
            &quot;success&quot;: False,
            &quot;message&quot;: &quot;Cookie 为空&quot;
        }

    print(&quot;正在签到 …&quot;)
    await do_checkin(cookie)

    return {
        &quot;success&quot;: True,
        &quot;message&quot;: &quot;签到成功&quot;
    }</code></pre></div></section>`,1)),e("div",D,[e("aside",L,[a[5]||(a[5]=e("span",{class:"nav-title"},"目录",-1)),(u(),r(c,null,p(x,(t,E)=>e("a",{key:t.id,href:`#${t.id}`},[e("span",null,d(String(E+1).padStart(2,"0")),1),l(" "+d(t.label),1)],8,B)),64)),e("div",G,[s(o,null,{default:n(()=>[s(i(f))]),_:1}),a[2]||(a[2]=l(" 示例模块位于仓库 ",-1)),a[3]||(a[3]=e("code",null,"modules/",-1)),a[4]||(a[4]=l(" 目录，可直接参考。 ",-1))])]),e("article",Y,[e("section",K,[a[7]||(a[7]=e("div",{class:"doc-heading"},[e("span",{class:"doc-index"},"01"),e("div",null,[e("h3",null,"目录结构"),e("p",null,"每个子目录就是一个模块，目录名即模块标识（key）。")])],-1)),e("pre",{class:"code-block"},[e("code",null,d(be))]),e("div",R,[s(o,null,{default:n(()=>[s(i(f))]),_:1}),a[6]||(a[6]=l(" 目录名建议只使用字母、数字、下划线和短横线。通过 ZIP 上传时，平台可以自动推断名称， 也可以在表单里指定模块标识。 ",-1))])]),e("section",Z,[a[19]||(a[19]=e("div",{class:"doc-heading"},[e("span",{class:"doc-index"},"02"),e("div",null,[e("h3",null,"config.json"),e("p",null,"模块元信息、参数表单定义、随机时间默认值与多账号开关。")])],-1)),e("div",M,[e("table",O,[a[8]||(a[8]=e("thead",null,[e("tr",null,[e("th",null,"字段"),e("th",null,"类型"),e("th",null,"必填"),e("th",null,"说明")])],-1)),e("tbody",null,[(u(),r(c,null,p(q,t=>e("tr",{key:t.name},[e("td",null,[e("code",null,d(t.name),1)]),e("td",null,d(t.type),1),e("td",null,[e("span",{class:V(t.required?"required-yes":"required-no")},d(t.required?"是":"否"),3)]),e("td",null,d(t.desc),1)])),64))])])]),e("pre",{class:"code-block"},[e("code",null,d(xe))]),e("div",$,[s(o,null,{default:n(()=>[s(i(g))]),_:1}),a[9]||(a[9]=e("code",null,"default_start_time",-1)),a[10]||(a[10]=l(" / ",-1)),a[11]||(a[11]=e("code",null,"default_end_time",-1)),a[12]||(a[12]=l(" 使用 24 小时制 ",-1)),a[13]||(a[13]=e("code",null,"HH:mm",-1)),a[14]||(a[14]=l("，",-1)),a[15]||(a[15]=e("code",null,"default_repeat_cycle",-1)),a[16]||(a[16]=l(" 指定每日 / 每周 / 每月15日 / 每月 / 每年；",-1)),a[17]||(a[17]=e("code",null,"default_repeat_sub_value",-1)),a[18]||(a[18]=l(" 设置子选项默认值： 周几（1-7）、每月几号（1-28）或月-日（如 2-29）。新建模块会以它们作为初始值， 用户可在网页端修改，平台会在执行日的时间窗内随机选择执行时间。 ",-1))])]),e("section",z,[a[30]||(a[30]=e("div",{class:"doc-heading"},[e("span",{class:"doc-index"},"03"),e("div",null,[e("h3",null,"参数定义"),e("p",null,[e("code",null,"params"),l(" 数组中的每一项都会在网页端渲染成对应的表单控件。")])])],-1)),e("div",Q,[(u(),r(c,null,p(C,t=>e("div",{key:t.type,class:"type-card"},[e("div",U,[e("code",null,d(t.type),1),e("span",null,d(t.control),1)]),e("p",null,d(t.desc),1)])),64))]),e("div",W,[e("table",J,[a[20]||(a[20]=e("thead",null,[e("tr",null,[e("th",null,"参数字段"),e("th",null,"说明")])],-1)),e("tbody",null,[(u(),r(c,null,p(h,t=>e("tr",{key:t.name},[e("td",null,[e("code",null,d(t.name),1)]),e("td",null,d(t.desc),1)])),64))])])]),e("div",X,[s(o,null,{default:n(()=>[s(i(y))]),_:1}),a[21]||(a[21]=l(" 用户保存的所有参数都会使用平台密钥加密后写入数据库；",-1)),a[22]||(a[22]=e("code",null,"main.py",-1)),a[23]||(a[23]=l(" 通过 ",-1)),a[24]||(a[24]=e("code",null,"params",-1)),a[25]||(a[25]=l(" 拿到的是解密后的值。不要在日志里打印密码或完整 Cookie。 ",-1))]),e("div",ee,[s(o,null,{default:n(()=>[s(i(_))]),_:1}),a[26]||(a[26]=l(" 多账号模式下，一个账号对应一次独立的 ",-1)),a[27]||(a[27]=e("code",null,"run(params)",-1)),a[28]||(a[28]=l(" 调用；平台负责串行执行、 2–5 分钟随机间隔、账号级超时、脱敏日志与结果汇总。模块无需自己循环账号列表。 ",-1))]),e("div",ae,[s(o,null,{default:n(()=>[s(i(k))]),_:1}),a[29]||(a[29]=l(" 签到成功、失败、多账号部分失败与随机时间生成失败由平台统一推送。请在「用户设置」配置 全局渠道，并在模块页打开推送开关；模块内不需要实现推送逻辑。 ",-1))])]),e("section",se,[a[35]||(a[35]=e("div",{class:"doc-heading"},[e("span",{class:"doc-index"},"04"),e("div",null,[e("h3",null,"main.py 入口规范"),e("p",null,[l("必须定义入口函数 "),e("code",null,"run"),l("，接收参数 dict 并返回结果 dict。 多账号模式下平台会按账号顺序逐个调用它。")])])],-1)),e("pre",{class:"code-block"},[e("code",null,d(qe))]),e("div",le,[e("div",te,[e("span",ne,[s(o,null,{default:n(()=>[s(i(g))]),_:1})]),a[31]||(a[31]=e("div",null,[e("strong",null,"执行超时"),e("p",null,"默认 300 秒，超时会被中断并记录为失败，可在服务端环境变量中调整。")],-1))]),e("div",oe,[e("span",de,[s(o,null,{default:n(()=>[s(i(v))]),_:1})]),a[32]||(a[32]=e("div",null,[e("strong",null,"返回结构"),e("p",null,[l("必须包含布尔型 "),e("code",null,"success"),l("，以及可读的 "),e("code",null,"message"),l("。")])],-1))]),e("div",ie,[e("span",ue,[s(o,null,{default:n(()=>[s(i(k))]),_:1})]),a[33]||(a[33]=e("div",null,[e("strong",null,"输出捕获"),e("p",null,[e("code",null,"print()"),l(" 与标准 "),e("code",null,"logging"),l(" 日志都会被实时推送到网页端。")])],-1))]),e("div",re,[e("span",ce,[s(o,null,{default:n(()=>[s(i(_))]),_:1})]),a[34]||(a[34]=e("div",null,[e("strong",null,"多文件与相对导入"),e("p",null,[l("模块以包的形式加载，支持 "),e("code",null,"from .helpers import xxx"),l("。")])],-1))])]),a[36]||(a[36]=e("div",{class:"doc-subheading"},[e("h4",null,"返回值示例"),e("p",null,"除 success / message 外的字段会作为附加数据打印在日志中。")],-1)),e("pre",{class:"code-block"},[e("code",null,d(he))])]),e("section",{id:"logging",class:"doc-section panel"},[a[37]||(a[37]=m('<div class="doc-heading" data-v-1a33ef0a><span class="doc-index" data-v-1a33ef0a>05</span><div data-v-1a33ef0a><h3 data-v-1a33ef0a>日志、异常与退出码</h3><p data-v-1a33ef0a>让失败信息足够清晰，是模块开发中最重要的部分之一。</p></div></div><ul class="doc-list" data-v-1a33ef0a><li data-v-1a33ef0a> 主动失败时返回 <code data-v-1a33ef0a>success: False</code>，并把原因写进 <code data-v-1a33ef0a>message</code>， 例如「Cookie 已过期」。 </li><li data-v-1a33ef0a> 未捕获异常会被平台捕获，traceback 写入执行日志，模块状态记为失败。 </li><li data-v-1a33ef0a> 日志以流的方式实时显示，SSE 连接断开后会从内存缓冲区恢复； 完整输出同时写入数据库与 <code data-v-1a33ef0a>logs/executions/&lt;key&gt;/</code> 文件。 </li><li data-v-1a33ef0a> 建议在关键步骤打印进度，例如登录、领取、校验结果，方便日后排查。 </li><li data-v-1a33ef0a> 不要在模块加载阶段做网络请求。将耗时操作放在 <code data-v-1a33ef0a>run()</code> 内， 否则导入失败会直接导致模块不可用。 </li></ul>',2)),e("pre",{class:"code-block"},[e("code",null,d(Ce))])]),e("section",pe,[a[39]||(a[39]=m('<div class="doc-heading" data-v-1a33ef0a><span class="doc-index" data-v-1a33ef0a>06</span><div data-v-1a33ef0a><h3 data-v-1a33ef0a>安装、更新与调试</h3><p data-v-1a33ef0a>两种安装方式都支持热加载，不需要重启容器。</p></div></div><div class="install-grid" data-v-1a33ef0a><div class="install-card" data-v-1a33ef0a><span class="install-num" data-v-1a33ef0a>A</span><h4 data-v-1a33ef0a>ZIP 上传</h4><ol data-v-1a33ef0a><li data-v-1a33ef0a>将模块目录压缩为 ZIP，保留 config.json 与 main.py。</li><li data-v-1a33ef0a>在「签到模块」页点击「上传模块」。</li><li data-v-1a33ef0a>安装后模块默认禁用，填写参数并启用即可。</li></ol></div><div class="install-card" data-v-1a33ef0a><span class="install-num" data-v-1a33ef0a>B</span><h4 data-v-1a33ef0a>挂载目录扫描</h4><ol data-v-1a33ef0a><li data-v-1a33ef0a>把模块目录放到宿主机 <code data-v-1a33ef0a>./modules/</code> 下。</li><li data-v-1a33ef0a>在网页端点击「扫描目录」。</li><li data-v-1a33ef0a>平台会同步新增、更新或标记异常模块。</li></ol></div></div>',2)),e("div",me,[s(o,null,{default:n(()=>[s(i(S))]),_:1}),a[38]||(a[38]=l(" 覆盖同名模块时，代码文件会被替换，但数据库中的账号与随机调度配置会保留。 删除模块会同时删除模块目录和历史执行记录。 ",-1))])]),e("section",ve,[a[45]||(a[45]=e("div",{class:"doc-heading"},[e("span",{class:"doc-index"},"07"),e("div",null,[e("h3",null,"安全与最佳实践"),e("p",null,"平台执行的是你自己安装的 Python 代码，请像对待服务器脚本一样对待模块。")])],-1)),e("div",fe,[e("div",ge,[s(o,null,{default:n(()=>[s(i(y))]),_:1}),a[40]||(a[40]=e("div",null,[e("strong",null,"只安装可信模块"),e("p",null,"模块代码以服务进程权限运行，可访问容器内文件与网络。不要上传来源不明的代码。")],-1))]),e("div",ye,[s(o,null,{default:n(()=>[s(i(T))]),_:1}),a[41]||(a[41]=e("div",null,[e("strong",null,"不要更换 SECRET_KEY"),e("p",null,"参数加密密钥由 SECRET_KEY 派生。更换后旧参数将无法解密，需要重新填写。")],-1))]),e("div",_e,[s(o,null,{default:n(()=>[s(i(F))]),_:1}),a[42]||(a[42]=e("div",null,[e("strong",null,"避免泄露敏感信息"),e("p",null,"日志会被持久化保存并展示在网页上，切勿打印完整 Cookie、Token 或密码。")],-1))])]),e("div",ke,[a[44]||(a[44]=e("div",null,[e("strong",null,"准备好写第一个模块了吗？"),e("p",null,[l("从复制 "),e("code",null,"modules/demo_checkin"),l(" 开始，修改 config.json 和 main.py 即可。")])],-1)),s(w,{to:"/modules",class:"closing-link"},{default:n(()=>[a[43]||(a[43]=l(" 前往模块库 ",-1)),s(o,null,{default:n(()=>[s(i(P))]),_:1})]),_:1})])])])])])}}},je=j(we,[["__scopeId","data-v-1a33ef0a"]]);export{je as default};

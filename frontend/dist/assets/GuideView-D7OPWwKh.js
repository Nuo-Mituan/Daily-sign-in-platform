import{i as f,Q as m,t as b,l as g,c as y,m as _,G as T,S as P,Y as h,y as j}from"./element-plus-Bc1tBYmV.js";import{_ as F}from"./index-myON0JJj.js";import{L as u,M as r,P as s,a0 as l,W as d,_ as a,aD as v,F as c,ae as p,$ as i,aj as k,u as o,S as I}from"./vue-Bja1UfAU.js";const A={class:"page-shell guide-page"},V={class:"page-header"},H={class:"header-actions"},D={href:"/docs",target:"_blank",rel:"noopener",class:"docs-link"},L={class:"guide-layout"},N={class:"guide-nav"},B=["href"],R={class:"nav-note"},G={class:"guide-content"},Y={id:"structure",class:"doc-section panel"},K={class:"doc-callout"},U={id:"config",class:"doc-section panel"},Z={class:"table-scroll"},M={class:"doc-table"},O={class:"doc-callout"},$={class:"doc-callout"},z={id:"params",class:"doc-section panel"},Q={class:"type-grid"},W={class:"type-head"},J={class:"table-scroll"},X={class:"doc-table"},ss={class:"doc-callout"},es={class:"doc-callout"},ls={class:"doc-callout"},as={id:"entry",class:"doc-section panel"},ts={class:"rule-grid"},ds={class:"rule"},ns={class:"rule-icon"},os={class:"rule"},is={class:"rule-icon"},us={class:"rule"},rs={class:"rule-icon"},cs={class:"rule"},ps={class:"rule-icon"},ms={id:"install",class:"doc-section panel"},vs={class:"doc-callout"},fs={id:"security",class:"doc-section panel"},bs={class:"security-box"},gs={class:"security-item"},ys={class:"security-item"},_s={class:"security-item"},ks={class:"closing-card"},xs=`modules/
├── demo_checkin/              # 物理目录；可由 config.json 的 directory_name 指向
│   ├── config.json            # 元信息、参数定义、随机时间默认值
│   ├── main.py                # 入口：async def run(params)
│   └── helpers.py             # 可选：模块内辅助文件
└── my_checkin/
    ├── config.json
    └── main.py`,qs=`{
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
}`,Cs=`"""main.py — 最小的签到模块示例。"""

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
    }`,Es=`# 成功
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
}`,ws=`import logging
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
        }`,Ss={__name:"GuideView",setup(Ts){const x=[{id:"structure",label:"目录结构"},{id:"config",label:"config.json"},{id:"params",label:"参数定义"},{id:"entry",label:"入口规范"},{id:"logging",label:"日志与异常"},{id:"install",label:"安装与调试"},{id:"security",label:"安全实践"}],q=[{name:"name",type:"string",required:!0,desc:"模块显示名称，例如「某平台签到」。"},{name:"description",type:"string",required:!0,desc:"一句话说明模块用途，展示在模块卡片上。"},{name:"author",type:"string",required:!1,desc:"作者或维护者名称。"},{name:"version",type:"string",required:!1,desc:"模块版本号，默认 1.0.0。"},{name:"icon",type:"string",required:!1,desc:"模块图标：Emoji、./favicon.ico、Base64 Data URI 或 HTTPS URL，默认 🧩。"},{name:"directory_name",type:"string",required:!1,desc:"物理模块目录名，最多 80 字符；为空时回退使用模块 key。用于 API key 与目录名独立演进。"},{name:"default_start_time",type:"string",required:!0,desc:"默认开始时间 HH:mm，例如 08:00。"},{name:"default_end_time",type:"string",required:!0,desc:"默认结束时间 HH:mm，例如 10:00。"},{name:"default_repeat_cycle",type:"string",required:!1,desc:"daily / weekly / monthly_15 / monthly / yearly。"},{name:"default_repeat_sub_value",type:"string",required:!1,desc:"每周填 1-7；每月填 1-28；每年填 M-D（如 2-29）。"},{name:"multi_account",type:"boolean",required:!1,desc:"为 true 时 params 会按账号重复渲染并串行执行。"},{name:"params",type:"array",required:!1,desc:"参数定义数组；多账号模式下每个账号各填写一组。"}],C=[{name:"key",desc:"参数键名，会作为 params 字典的 key，仅支持字母、数字、下划线。"},{name:"label",desc:"网页表单上显示的中文标签。"},{name:"type",desc:"控件类型：text / textarea / password / select / switch / number。"},{name:"required",desc:"是否为必填项；启用模块和保存时都会校验。"},{name:"default",desc:"默认值。select 参数应与某个 option 的 value 对应。"},{name:"placeholder",desc:"输入框占位提示。"},{name:"help",desc:"显示在控件下方的帮助文字，适合填写获取 Cookie 的说明。"},{name:"options",desc:'select 专用。支持 ["a","b"] 或 [{ "label":"国服","value":"cn" }]。'},{name:"min / max / step",desc:"number 专用，限制数值范围与步长。"},{name:"rows",desc:"textarea 专用，控制默认显示行数。"},{name:"account_label",desc:"多账号模式可选：标记用于日志脱敏展示的账号标识字段。"}],E=[{type:"text",control:"单行输入框",desc:"适合账号、Token、推送 Key 等短文本。"},{type:"textarea",control:"多行文本域",desc:"适合 Cookie、消息模板等长文本。"},{type:"password",control:"密码输入框",desc:"输入默认隐藏，仍会加密存储。"},{type:"select",control:"下拉选择器",desc:"需提供 options；保存时校验取值。"},{type:"switch",control:"开关",desc:"布尔值，适合“是否推送”等开关项。"},{type:"number",control:"数字输入框",desc:"支持 min / max / step 限制。"}];return(Ps,e)=>{const n=k("el-icon"),w=k("router-link");return u(),r("div",A,[s("header",V,[e[1]||(e[1]=s("div",null,[s("span",{class:"eyebrow"},"DEVELOPER DOCS"),s("h1",{class:"page-title"},"模块开发指南"),s("p",{class:"page-subtitle"},"用两个文件和一段 Python，把任意签到流程接入签到云台。")],-1)),s("div",H,[s("a",D,[l(n,null,{default:d(()=>[l(o(f))]),_:1}),e[0]||(e[0]=a(" 打开 API 文档 ",-1))])])]),e[54]||(e[54]=v(`<section class="guide-hero" data-v-af13cdb4><div class="guide-hero-copy" data-v-af13cdb4><span class="hero-tag" data-v-af13cdb4><i data-v-af13cdb4></i>PLUGIN SPEC · V1</span><h2 data-v-af13cdb4>把任意签到，<br data-v-af13cdb4><span data-v-af13cdb4>装进一个模块。</span></h2><p data-v-af13cdb4> 模块就是一个普通目录：<code data-v-af13cdb4>config.json</code> 描述参数与默认随机时间窗， <code data-v-af13cdb4>main.py</code> 实现异步签到逻辑。平台负责参数表单渲染、加密存储、调度与日志。 </p><div class="hero-chips" data-v-af13cdb4><span data-v-af13cdb4>热插拔安装</span><span data-v-af13cdb4>随机时间调度</span><span data-v-af13cdb4>stdout 实时捕获</span><span data-v-af13cdb4>异步 timeout 保护</span></div></div><div class="hero-code" data-v-af13cdb4><div class="hero-code-bar" data-v-af13cdb4><span class="hero-code-dots" data-v-af13cdb4><i data-v-af13cdb4></i><i data-v-af13cdb4></i><i data-v-af13cdb4></i></span><span data-v-af13cdb4>main.py</span><span class="hero-code-live" data-v-af13cdb4>ASYNC</span></div><pre data-v-af13cdb4><code data-v-af13cdb4>async def run(params: dict) -&gt; dict:
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
    }</code></pre></div></section>`,1)),s("div",L,[s("aside",N,[e[5]||(e[5]=s("span",{class:"nav-title"},"目录",-1)),(u(),r(c,null,p(x,(t,S)=>s("a",{key:t.id,href:`#${t.id}`},[s("span",null,i(String(S+1).padStart(2,"0")),1),a(" "+i(t.label),1)],8,B)),64)),s("div",R,[l(n,null,{default:d(()=>[l(o(m))]),_:1}),e[2]||(e[2]=a(" 示例模块位于仓库 ",-1)),e[3]||(e[3]=s("code",null,"modules/",-1)),e[4]||(e[4]=a(" 目录，可直接参考。 ",-1))])]),s("article",G,[s("section",Y,[e[7]||(e[7]=s("div",{class:"doc-heading"},[s("span",{class:"doc-index"},"01"),s("div",null,[s("h3",null,"目录结构"),s("p",null,"每个子目录就是一个模块，目录名即模块标识（key）。")])],-1)),s("pre",{class:"code-block"},[s("code",null,i(xs))]),s("div",K,[l(n,null,{default:d(()=>[l(o(m))]),_:1}),e[6]||(e[6]=a(" 目录名建议只使用字母、数字、下划线和短横线。通过 ZIP 上传时，平台可以自动推断名称， 也可以在表单里指定模块标识。 ",-1))])]),s("section",U,[e[27]||(e[27]=s("div",{class:"doc-heading"},[s("span",{class:"doc-index"},"02"),s("div",null,[s("h3",null,"config.json"),s("p",null,"模块元信息、参数表单定义、随机时间默认值与多账号开关。")])],-1)),s("div",Z,[s("table",M,[e[8]||(e[8]=s("thead",null,[s("tr",null,[s("th",null,"字段"),s("th",null,"类型"),s("th",null,"必填"),s("th",null,"说明")])],-1)),s("tbody",null,[(u(),r(c,null,p(q,t=>s("tr",{key:t.name},[s("td",null,[s("code",null,i(t.name),1)]),s("td",null,i(t.type),1),s("td",null,[s("span",{class:I(t.required?"required-yes":"required-no")},i(t.required?"是":"否"),3)]),s("td",null,i(t.desc),1)])),64))])])]),s("div",O,[l(n,null,{default:d(()=>[l(o(m))]),_:1}),e[9]||(e[9]=s("code",null,"directory_name",-1)),e[10]||(e[10]=a(" 表示模块在 ",-1)),e[11]||(e[11]=s("code",null,"modules/",-1)),e[12]||(e[12]=a(" 下的真实物理目录名； 不填时回退为 API key。修改目录名后重新扫描模块即可同步数据库， 图标接口会按该字段读取 ",-1)),e[13]||(e[13]=s("code",null,"modules/<directory_name>/",-1)),e[14]||(e[14]=a("。 该值只能包含字母、数字、下划线和短横线，禁止路径分隔符或 ",-1)),e[15]||(e[15]=s("code",null,"..",-1)),e[16]||(e[16]=a("。 ",-1))]),s("pre",{class:"code-block"},[s("code",null,i(qs))]),s("div",$,[l(n,null,{default:d(()=>[l(o(b))]),_:1}),e[17]||(e[17]=s("code",null,"default_start_time",-1)),e[18]||(e[18]=a(" / ",-1)),e[19]||(e[19]=s("code",null,"default_end_time",-1)),e[20]||(e[20]=a(" 使用 24 小时制 ",-1)),e[21]||(e[21]=s("code",null,"HH:mm",-1)),e[22]||(e[22]=a("，",-1)),e[23]||(e[23]=s("code",null,"default_repeat_cycle",-1)),e[24]||(e[24]=a(" 指定每日 / 每周 / 每月15日 / 每月 / 每年；",-1)),e[25]||(e[25]=s("code",null,"default_repeat_sub_value",-1)),e[26]||(e[26]=a(" 设置子选项默认值： 周几（1-7）、每月几号（1-28）或月-日（如 2-29）。新建模块会以它们作为初始值， 用户可在网页端修改，平台会在执行日的时间窗内随机选择执行时间。 ",-1))])]),s("section",z,[e[38]||(e[38]=s("div",{class:"doc-heading"},[s("span",{class:"doc-index"},"03"),s("div",null,[s("h3",null,"参数定义"),s("p",null,[s("code",null,"params"),a(" 数组中的每一项都会在网页端渲染成对应的表单控件。")])])],-1)),s("div",Q,[(u(),r(c,null,p(E,t=>s("div",{key:t.type,class:"type-card"},[s("div",W,[s("code",null,i(t.type),1),s("span",null,i(t.control),1)]),s("p",null,i(t.desc),1)])),64))]),s("div",J,[s("table",X,[e[28]||(e[28]=s("thead",null,[s("tr",null,[s("th",null,"参数字段"),s("th",null,"说明")])],-1)),s("tbody",null,[(u(),r(c,null,p(C,t=>s("tr",{key:t.name},[s("td",null,[s("code",null,i(t.name),1)]),s("td",null,i(t.desc),1)])),64))])])]),s("div",ss,[l(n,null,{default:d(()=>[l(o(g))]),_:1}),e[29]||(e[29]=a(" 用户保存的所有参数都会使用平台密钥加密后写入数据库；",-1)),e[30]||(e[30]=s("code",null,"main.py",-1)),e[31]||(e[31]=a(" 通过 ",-1)),e[32]||(e[32]=s("code",null,"params",-1)),e[33]||(e[33]=a(" 拿到的是解密后的值。不要在日志里打印密码或完整 Cookie。 ",-1))]),s("div",es,[l(n,null,{default:d(()=>[l(o(y))]),_:1}),e[34]||(e[34]=a(" 多账号模式下，一个账号对应一次独立的 ",-1)),e[35]||(e[35]=s("code",null,"run(params)",-1)),e[36]||(e[36]=a(" 调用；平台负责串行执行、 2–5 分钟随机间隔、账号级超时、脱敏日志与结果汇总。模块无需自己循环账号列表。 ",-1))]),s("div",ls,[l(n,null,{default:d(()=>[l(o(_))]),_:1}),e[37]||(e[37]=a(" 签到成功、失败、多账号部分失败与随机时间生成失败由平台统一推送。请在「用户设置」配置 全局渠道，并在模块页打开推送开关；模块内不需要实现推送逻辑。 ",-1))])]),s("section",as,[e[43]||(e[43]=s("div",{class:"doc-heading"},[s("span",{class:"doc-index"},"04"),s("div",null,[s("h3",null,"main.py 入口规范"),s("p",null,[a("必须定义入口函数 "),s("code",null,"run"),a("，接收参数 dict 并返回结果 dict。 多账号模式下平台会按账号顺序逐个调用它。")])])],-1)),s("pre",{class:"code-block"},[s("code",null,i(Cs))]),s("div",ts,[s("div",ds,[s("span",ns,[l(n,null,{default:d(()=>[l(o(b))]),_:1})]),e[39]||(e[39]=s("div",null,[s("strong",null,"执行超时"),s("p",null,"默认 300 秒，超时会被中断并记录为失败，可在服务端环境变量中调整。")],-1))]),s("div",os,[s("span",is,[l(n,null,{default:d(()=>[l(o(f))]),_:1})]),e[40]||(e[40]=s("div",null,[s("strong",null,"返回结构"),s("p",null,[a("必须包含布尔型 "),s("code",null,"success"),a("，以及可读的 "),s("code",null,"message"),a("。")])],-1))]),s("div",us,[s("span",rs,[l(n,null,{default:d(()=>[l(o(_))]),_:1})]),e[41]||(e[41]=s("div",null,[s("strong",null,"输出捕获"),s("p",null,[s("code",null,"print()"),a(" 与标准 "),s("code",null,"logging"),a(" 日志都会被实时推送到网页端。")])],-1))]),s("div",cs,[s("span",ps,[l(n,null,{default:d(()=>[l(o(y))]),_:1})]),e[42]||(e[42]=s("div",null,[s("strong",null,"多文件与相对导入"),s("p",null,[a("模块以包的形式加载，支持 "),s("code",null,"from .helpers import xxx"),a("。")])],-1))])]),e[44]||(e[44]=s("div",{class:"doc-subheading"},[s("h4",null,"返回值示例"),s("p",null,"除 success / message 外的字段会作为附加数据打印在日志中。")],-1)),s("pre",{class:"code-block"},[s("code",null,i(Es))])]),s("section",{id:"logging",class:"doc-section panel"},[e[45]||(e[45]=v('<div class="doc-heading" data-v-af13cdb4><span class="doc-index" data-v-af13cdb4>05</span><div data-v-af13cdb4><h3 data-v-af13cdb4>日志、异常与退出码</h3><p data-v-af13cdb4>让失败信息足够清晰，是模块开发中最重要的部分之一。</p></div></div><ul class="doc-list" data-v-af13cdb4><li data-v-af13cdb4> 主动失败时返回 <code data-v-af13cdb4>success: False</code>，并把原因写进 <code data-v-af13cdb4>message</code>， 例如「Cookie 已过期」。 </li><li data-v-af13cdb4> 未捕获异常会被平台捕获，traceback 写入执行日志，模块状态记为失败。 </li><li data-v-af13cdb4> 日志以流的方式实时显示，SSE 连接断开后会从内存缓冲区恢复； 完整输出同时写入数据库与 <code data-v-af13cdb4>logs/executions/&lt;key&gt;/</code> 文件。 </li><li data-v-af13cdb4> 建议在关键步骤打印进度，例如登录、领取、校验结果，方便日后排查。 </li><li data-v-af13cdb4> 不要在模块加载阶段做网络请求。将耗时操作放在 <code data-v-af13cdb4>run()</code> 内， 否则导入失败会直接导致模块不可用。 </li></ul>',2)),s("pre",{class:"code-block"},[s("code",null,i(ws))])]),s("section",ms,[e[47]||(e[47]=v('<div class="doc-heading" data-v-af13cdb4><span class="doc-index" data-v-af13cdb4>06</span><div data-v-af13cdb4><h3 data-v-af13cdb4>安装、更新与调试</h3><p data-v-af13cdb4>两种安装方式都支持热加载，不需要重启容器。</p></div></div><div class="install-grid" data-v-af13cdb4><div class="install-card" data-v-af13cdb4><span class="install-num" data-v-af13cdb4>A</span><h4 data-v-af13cdb4>ZIP 上传</h4><ol data-v-af13cdb4><li data-v-af13cdb4>将模块目录压缩为 ZIP，保留 config.json 与 main.py。</li><li data-v-af13cdb4>在「签到模块」页点击「上传模块」。</li><li data-v-af13cdb4>安装后模块默认禁用，填写参数并启用即可。</li></ol></div><div class="install-card" data-v-af13cdb4><span class="install-num" data-v-af13cdb4>B</span><h4 data-v-af13cdb4>挂载目录扫描</h4><ol data-v-af13cdb4><li data-v-af13cdb4>把模块目录放到宿主机 <code data-v-af13cdb4>./modules/</code> 下。</li><li data-v-af13cdb4>在网页端点击「扫描目录」。</li><li data-v-af13cdb4>平台会同步新增、更新或标记异常模块。</li></ol></div></div>',2)),s("div",vs,[l(n,null,{default:d(()=>[l(o(T))]),_:1}),e[46]||(e[46]=a(" 覆盖同名模块时，代码文件会被替换，但数据库中的账号与随机调度配置会保留。 删除模块会同时删除模块目录和历史执行记录。 ",-1))])]),s("section",fs,[e[53]||(e[53]=s("div",{class:"doc-heading"},[s("span",{class:"doc-index"},"07"),s("div",null,[s("h3",null,"安全与最佳实践"),s("p",null,"平台执行的是你自己安装的 Python 代码，请像对待服务器脚本一样对待模块。")])],-1)),s("div",bs,[s("div",gs,[l(n,null,{default:d(()=>[l(o(g))]),_:1}),e[48]||(e[48]=s("div",null,[s("strong",null,"只安装可信模块"),s("p",null,"模块代码以服务进程权限运行，可访问容器内文件与网络。不要上传来源不明的代码。")],-1))]),s("div",ys,[l(n,null,{default:d(()=>[l(o(P))]),_:1}),e[49]||(e[49]=s("div",null,[s("strong",null,"不要更换 SECRET_KEY"),s("p",null,"参数加密密钥由 SECRET_KEY 派生。更换后旧参数将无法解密，需要重新填写。")],-1))]),s("div",_s,[l(n,null,{default:d(()=>[l(o(h))]),_:1}),e[50]||(e[50]=s("div",null,[s("strong",null,"避免泄露敏感信息"),s("p",null,"日志会被持久化保存并展示在网页上，切勿打印完整 Cookie、Token 或密码。")],-1))])]),s("div",ks,[e[52]||(e[52]=s("div",null,[s("strong",null,"准备好写第一个模块了吗？"),s("p",null,[a("从复制 "),s("code",null,"modules/demo_checkin"),a(" 开始，修改 config.json 和 main.py 即可。")])],-1)),l(w,{to:"/modules",class:"closing-link"},{default:d(()=>[e[51]||(e[51]=a(" 前往模块库 ",-1)),l(n,null,{default:d(()=>[l(o(j))]),_:1})]),_:1})])])])])])}}},Is=F(Ss,[["__scopeId","data-v-af13cdb4"]]);export{Is as default};

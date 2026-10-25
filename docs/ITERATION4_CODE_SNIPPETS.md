# 第四次迭代 · 关键变更代码摘录（带行号）
本文档提供核心变更的上下文代码；完整源码以仓库文件为准。
删除登录页预览块后，`frontend/src/views/LoginView.vue` 中不再存在 `schedule-preview` 标记；下面展示替代的隐私说明卡片与相关 CSS。
## `backend/app/scheduling.py`
五周期、子选项校验、执行日/闰年计算
```text
// backend/app/scheduling.py:1-300
  1 | """Pure helpers for per-cycle random execution windows.
  2 | 
  3 | Canonical repeat cycles (iteration 4):
  4 | 
  5 | * daily      -> every day
  6 | * weekly     -> a selected weekday (1=Monday ... 7=Sunday)
  7 | * monthly_15 -> the 15th of every month
  8 | * monthly    -> a selected day 1..28 of every month
  9 | * yearly     -> a selected month-day (February 29 is allowed; non-leap years
 10 |                 simply have no occurrence and the next leap year is used)
 11 | 
 12 | The execution happens on the occurrence day, at a random time inside the
 13 | same-day [start_time, end_time] window.  A window never spans midnight.
 14 | """
 15 | 
 16 | from __future__ import annotations
 17 | 
 18 | import calendar
 19 | import random
 20 | import re
 21 | from datetime import date, datetime, time, timedelta, timezone
 22 | from zoneinfo import ZoneInfo
 23 | 
 24 | REPEAT_CYCLES = (
 25 |     "daily",
 26 |     "weekly",
 27 |     "monthly_15",
 28 |     "monthly",
 29 |     "yearly",
 30 | )
 31 | 
 32 | CYCLE_LABELS = {
 33 |     "daily": "每日",
 34 |     "weekly": "每周",
 35 |     "monthly_15": "每月15日",
 36 |     "monthly": "每月",
 37 |     "yearly": "每年",
 38 | }
 39 | 
 40 | WEEKDAY_LABELS = {
 41 |     1: "周一",
 42 |     2: "周二",
 43 |     3: "周三",
 44 |     4: "周四",
 45 |     5: "周五",
 46 |     6: "周六",
 47 |     7: "周日",
 48 | }
 49 | 
 50 | LEGACY_CYCLE_MAP = {
 51 |     "half_month": "monthly",
 52 |     "quarterly": "monthly",
 53 | }
 54 | 
 55 | DEFAULT_SUB_VALUES = {
 56 |     "daily": "",
 57 |     "weekly": "1",
 58 |     "monthly_15": "",
 59 |     "monthly": "1",
 60 |     "yearly": "1-1",
 61 | }
 62 | 
 63 | _TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
 64 | _YEAR_SUB_RE = re.compile(r"^(\d{1,2})-(\d{1,2})$")
 65 | 
 66 | 
 67 | class ScheduleError(ValueError):
 68 |     """Invalid schedule configuration."""
 69 | 
 70 | 
 71 | def parse_hhmm(value: str | None, field_label: str = "时间") -> tuple[int, int]:
 72 |     text = (value or "").strip()
 73 |     if not _TIME_RE.fullmatch(text):
 74 |         raise ScheduleError(f"{field_label}必须使用 24 小时制 HH:mm 格式，例如 09:30")
 75 |     hour, minute = text.split(":", 1)
 76 |     return int(hour), int(minute)
 77 | 
 78 | 
 79 | def validate_time_value(value: str | None, field_label: str = "时间") -> str:
 80 |     hour, minute = parse_hhmm(value, field_label)
 81 |     return f"{hour:02d}:{minute:02d}"
 82 | 
 83 | 
 84 | def validate_repeat_cycle(value: str | None) -> str:
 85 |     cycle = (value or "").strip().lower()
 86 |     if cycle in LEGACY_CYCLE_MAP:
 87 |         cycle = LEGACY_CYCLE_MAP[cycle]
 88 |     if cycle not in REPEAT_CYCLES:
 89 |         raise ScheduleError("重复周期无效，可选值：" + "、".join(REPEAT_CYCLES))
 90 |     return cycle
 91 | 
 92 | 
 93 | def normalize_repeat_sub_value(cycle: str, value: object = None) -> str:
 94 |     """Normalize a sub-option for a canonical cycle.
 95 | 
 96 |     Storage format:
 97 |       weekly      -> "1".."7" (ISO: Monday=1)
 98 |       monthly     -> "1".."28"
 99 |       yearly      -> "M-D" (no leading zeros; February 29 is valid)
100 |       daily / monthly_15 -> ""
101 |     """
102 |     cycle = validate_repeat_cycle(cycle)
103 |     text = str(value or "").strip()
104 |     if cycle in {"daily", "monthly_15"}:
105 |         return ""
106 |     if cycle == "weekly":
107 |         try:
108 |             number = int(text or DEFAULT_SUB_VALUES[cycle])
109 |         except ValueError as exc:
110 |             raise ScheduleError("每周子选项必须是 1-7（周一至周日）") from exc
111 |         if not 1 <= number <= 7:
112 |             raise ScheduleError("每周子选项必须是 1-7（周一至周日）")
113 |         return str(number)
114 |     if cycle == "monthly":
115 |         try:
116 |             number = int(text or DEFAULT_SUB_VALUES[cycle])
117 |         except ValueError as exc:
118 |             raise ScheduleError("每月日期必须是 1-28") from exc
119 |         if not 1 <= number <= 28:
120 |             raise ScheduleError("每月日期必须是 1-28（固定上限 28）")
121 |         return str(number)
122 |     # yearly
123 |     if not text:
124 |         return DEFAULT_SUB_VALUES["yearly"]
125 |     match = _YEAR_SUB_RE.fullmatch(text)
126 |     if not match:
127 |         raise ScheduleError("每年子选项必须使用 M-D 格式，例如 1-1 或 12-31")
128 |     month, day = int(match.group(1)), int(match.group(2))
129 |     if not 1 <= month <= 12:
130 |         raise ScheduleError("月份必须在 1-12 之间")
131 |     max_day = calendar.monthrange(2000, month)[1]  # 2000 is a leap year
132 |     if not 1 <= day <= max_day:
133 |         raise ScheduleError(f"{month} 月日期必须在 1-{max_day} 之间")
134 |     return f"{month}-{day}"
135 | 
136 | 
137 | def normalize_legacy_cycle(
138 |     cycle: str | None, sub_value: object = None
139 | ) -> tuple[str, str]:
140 |     """Map removed cycles to the new monthly + default-1st representation."""
141 |     raw = (cycle or "").strip().lower()
142 |     mapped = LEGACY_CYCLE_MAP.get(raw, raw)
143 |     if mapped not in REPEAT_CYCLES:
144 |         raise ScheduleError("重复周期无效")
145 |     if raw in LEGACY_CYCLE_MAP:
146 |         return "monthly", "1"
147 |     return mapped, normalize_repeat_sub_value(mapped, sub_value)
148 | 
149 | 
150 | def repeat_sub_label(cycle: str, sub_value: object = None) -> str:
151 |     normalized_cycle = validate_repeat_cycle(cycle)
152 |     sub = normalize_repeat_sub_value(normalized_cycle, sub_value)
153 |     if normalized_cycle == "daily":
154 |         return "每天"
155 |     if normalized_cycle == "weekly":
156 |         return f"每{WEEKDAY_LABELS[int(sub)]}"
157 |     if normalized_cycle == "monthly_15":
158 |         return "每月15日"
159 |     if normalized_cycle == "monthly":
160 |         return f"每月{sub}日"
161 |     month, day = sub.split("-", 1)
162 |     return f"每年{int(month)}月{int(day)}日"
163 | 
164 | 
165 | def validate_schedule(
166 |     start_time: str | None,
167 |     end_time: str | None,
168 |     repeat_cycle: str | None,
169 |     repeat_sub_value: object = None,
170 | ) -> tuple[str, str, str, str]:
171 |     start = validate_time_value(start_time, "开始时间")
172 |     end = validate_time_value(end_time, "结束时间")
173 |     cycle, sub = normalize_legacy_cycle(repeat_cycle, repeat_sub_value)
174 |     if start >= end:
175 |         raise ScheduleError("开始时间必须早于结束时间（时间窗不能跨天）")
176 |     return start, end, cycle, sub
177 | 
178 | 
179 | def _add_months(day: date, months: int) -> date:
180 |     month_index = day.month - 1 + months
181 |     year = day.year + month_index // 12
182 |     month = month_index % 12 + 1
183 |     day_number = min(day.day, calendar.monthrange(year, month)[1])
184 |     return date(year, month, day_number)
185 | 
186 | 
187 | def _yearly_parts(sub: str) -> tuple[int, int]:
188 |     month, day = sub.split("-", 1)
189 |     return int(month), int(day)
190 | 
191 | 
192 | def _valid_date(year: int, month: int, day: int) -> date | None:
193 |     try:
194 |         return date(year, month, day)
195 |     except ValueError:
196 |         return None
197 | 
198 | 
199 | def period_start_for(
200 |     cycle: str, day: date, repeat_sub_value: object = None
201 | ) -> date:
202 |     """Return the most recent occurrence date on or before ``day``.
203 | 
204 |     For daily this is the day itself.  For a weekly/monthly/yearly selection it
205 |     is the latest selected occurrence (which may be in a previous week/month/
206 |     year).  Schedulers use ``period_start_for(...) == day`` to decide whether an
207 |     execution should happen today.
208 |     """
209 |     cycle = validate_repeat_cycle(cycle)
210 |     sub = normalize_repeat_sub_value(cycle, repeat_sub_value)
211 |     if cycle == "daily":
212 |         return day
213 |     if cycle == "weekly":
214 |         delta = (day.weekday() + 1 - int(sub)) % 7
215 |         return day - timedelta(days=delta)
216 |     if cycle == "monthly_15":
217 |         if day.day >= 15:
218 |             return day.replace(day=15)
219 |         return _add_months(day.replace(day=1), -1).replace(day=15)
220 |     if cycle == "monthly":
221 |         day_number = int(sub)
222 |         if day.day >= day_number:
223 |             return day.replace(day=day_number)
224 |         return _add_months(day.replace(day=1), -1).replace(day=day_number)
225 |     # yearly
226 |     month, day_number = _yearly_parts(sub)
227 |     for year in range(day.year, day.year - 16, -1):
228 |         candidate = _valid_date(year, month, day_number)
229 |         if candidate is not None and candidate <= day:
230 |             return candidate
231 |     raise ScheduleError("无法计算年度周期")
232 | 
233 | 
234 | def next_period_start(
235 |     cycle: str, period_start: date, repeat_sub_value: object = None
236 | ) -> date:
237 |     """Return the next occurrence strictly after ``period_start``."""
238 |     cycle = validate_repeat_cycle(cycle)
239 |     sub = normalize_repeat_sub_value(cycle, repeat_sub_value)
240 |     if cycle == "daily":
241 |         return period_start + timedelta(days=1)
242 |     if cycle == "weekly":
243 |         return period_start + timedelta(days=7)
244 |     if cycle == "monthly_15":
245 |         return _add_months(period_start.replace(day=1), 1).replace(day=15)
246 |     if cycle == "monthly":
247 |         return _add_months(period_start.replace(day=1), 1).replace(
248 |             day=int(sub)
249 |         )
250 |     # yearly: skip invalid dates such as February 29 in non-leap years.
251 |     month, day_number = _yearly_parts(sub)
252 |     year = period_start.year + 1
253 |     for _ in range(16):
254 |         candidate = _valid_date(year, month, day_number)
255 |         if candidate is not None:
256 |             return candidate
257 |         year += 1
258 |     raise ScheduleError("无法计算下一个年度周期")
259 | 
260 | 
261 | def is_cycle_start(
262 |     cycle: str, day: date, repeat_sub_value: object = None
263 | ) -> bool:
264 |     return period_start_for(cycle, day, repeat_sub_value) == day
265 | 
266 | 
267 | def next_occurrence(
268 |     cycle: str, start_day: date, repeat_sub_value: object = None
269 | ) -> date:
270 |     """Return the first occurrence on or after ``start_day``."""
271 |     candidate = period_start_for(cycle, start_day, repeat_sub_value)
272 |     if candidate < start_day:
273 |         candidate = next_period_start(cycle, candidate, repeat_sub_value)
274 |     return candidate
275 | 
276 | 
277 | def current_period_start(
278 |     cycle: str,
279 |     tz: ZoneInfo,
280 |     now: datetime | None = None,
281 |     repeat_sub_value: object = None,
282 | ) -> date:
283 |     local_now = (now or datetime.now(timezone.utc)).astimezone(tz)
284 |     return period_start_for(cycle, local_now.date(), repeat_sub_value)
285 | 
286 | 
287 | def _at_local(day: date, hhmm: str, tz: ZoneInfo) -> datetime:
288 |     hour, minute = parse_hhmm(hhmm)
289 |     return datetime.combine(day, time(hour, minute), tzinfo=tz)
290 | 
291 | 
292 | def schedule_window(
293 |     period_start: date,
294 |     start_time: str,
295 |     end_time: str,
296 |     tz: ZoneInfo,
297 | ) -> tuple[datetime, datetime]:
298 |     start = _at_local(period_start, start_time, tz)
299 |     end = _at_local(period_start, end_time, tz)
300 |     if start >= end:
```
```text
// backend/app/scheduling.py:355-384
355 |     chosen = lower + timedelta(
356 |         seconds=random.SystemRandom().randint(0, span_seconds)
357 |     )
358 |     return chosen.astimezone(timezone.utc)
359 | 
360 | 
361 | def next_plan_at(
362 |     cycle: str,
363 |     tz: ZoneInfo,
364 |     now: datetime | None = None,
365 |     repeat_sub_value: object = None,
366 | ) -> datetime:
367 |     """The next local 00:00 occurrence after today."""
368 |     local_now = (now or datetime.now(timezone.utc)).astimezone(tz)
369 |     occurrence = next_occurrence(
370 |         cycle, local_now.date() + timedelta(days=1), repeat_sub_value
371 |     )
372 |     return datetime.combine(occurrence, time.min, tzinfo=tz)
373 | 
374 | 
375 | def readable_window(
376 |     start_time: str,
377 |     end_time: str,
378 |     cycle: str,
379 |     repeat_sub_value: object = None,
380 | ) -> str:
381 |     return (
382 |         f"{repeat_sub_label(cycle, repeat_sub_value)} "
383 |         f"{start_time}–{end_time} 随机执行"
384 |     )
```
## `backend/app/models.py`
新增子选项数据库字段
```text
// backend/app/models.py:72-90
72 |     icon: Mapped[str] = mapped_column(String(16), default="🧩")
73 | 
74 |     # Legacy Cron columns kept for database/backward compatibility. New scheduling
75 |     # uses start_time / end_time / repeat_cycle below.
76 |     default_cron: Mapped[str] = mapped_column(String(100), default="0 8 * * *")
77 |     cron: Mapped[str] = mapped_column(String(100), default="0 8 * * *")
78 | 
79 |     default_start_time: Mapped[str] = mapped_column(String(5), default="08:00")
80 |     default_end_time: Mapped[str] = mapped_column(String(5), default="10:00")
81 |     default_repeat_cycle: Mapped[str] = mapped_column(String(20), default="daily")
82 |     default_repeat_sub_value: Mapped[str] = mapped_column(String(10), default="")
83 |     start_time: Mapped[str] = mapped_column(String(5), default="08:00")
84 |     end_time: Mapped[str] = mapped_column(String(5), default="10:00")
85 |     repeat_cycle: Mapped[str] = mapped_column(String(20), default="daily")
86 |     repeat_sub_value: Mapped[str] = mapped_column(String(10), default="")
87 | 
88 |     multi_account: Mapped[bool] = mapped_column(Boolean, default=False)
89 |     push_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
90 |     enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
```
## `backend/app/migrations.py`
新列与旧周期降级迁移
```text
// backend/app/migrations.py:15-148
 15 | from .models import Module
 16 | from .scheduling import ScheduleError, normalize_legacy_cycle
 17 | 
 18 | logger = logging.getLogger(__name__)
 19 | 
 20 | _LEGACY_COLUMNS: dict[str, str] = {
 21 |     "default_start_time": "VARCHAR(5)",
 22 |     "default_end_time": "VARCHAR(5)",
 23 |     "default_repeat_cycle": "VARCHAR(20)",
 24 |     "default_repeat_sub_value": "VARCHAR(10)",
 25 |     "start_time": "VARCHAR(5)",
 26 |     "end_time": "VARCHAR(5)",
 27 |     "repeat_cycle": "VARCHAR(20)",
 28 |     "repeat_sub_value": "VARCHAR(10)",
 29 |     "multi_account": "BOOLEAN",
 30 |     "push_enabled": "BOOLEAN",
 31 |     "accounts_encrypted": "TEXT",
 32 | }
 33 | 
 34 | 
 35 | def _legacy_window(cron: str | None) -> tuple[str, str]:
 36 |     parts = (cron or "").split()
 37 |     if len(parts) == 5 and parts[0].isdigit() and parts[1].isdigit():
 38 |         minute = int(parts[0])
 39 |         hour = int(parts[1])
 40 |         if 0 <= minute <= 59 and 0 <= hour <= 23:
 41 |             start = hour * 60 + minute
 42 |             end = min(23 * 60 + 59, start + 60)
 43 |             if end <= start:
 44 |                 start = max(0, end - 1)
 45 |             return (
 46 |                 f"{start // 60:02d}:{start % 60:02d}",
 47 |                 f"{end // 60:02d}:{end % 60:02d}",
 48 |             )
 49 |     return "08:00", "10:00"
 50 | 
 51 | 
 52 | async def migrate_schema() -> None:
 53 |     """Add random-schedule / multi-account columns to an existing SQLite DB."""
 54 |     if engine.dialect.name != "sqlite":
 55 |         return
 56 | 
 57 |     async with engine.begin() as connection:
 58 |         result = await connection.exec_driver_sql("PRAGMA table_info(modules)")
 59 |         columns = {row[1] for row in result.fetchall()}
 60 |         added: list[str] = []
 61 |         for name, ddl_type in _LEGACY_COLUMNS.items():
 62 |             if name in columns:
 63 |                 continue
 64 |             await connection.exec_driver_sql(
 65 |                 f'ALTER TABLE modules ADD COLUMN "{name}" {ddl_type}'
 66 |             )
 67 |             added.append(name)
 68 |         if added:
 69 |             logger.info("数据库迁移：为 modules 添加字段 %s", ", ".join(added))
 70 | 
 71 |     async with SessionLocal() as db:
 72 |         rows = (await db.execute(select(Module))).scalars().all()
 73 |         changed = 0
 74 |         migrated_cycles: list[str] = []
 75 |         for row in rows:
 76 |             legacy_start, legacy_end = _legacy_window(row.cron)
 77 |             row_changed = False
 78 |             if not row.start_time:
 79 |                 row.start_time = legacy_start
 80 |                 row_changed = True
 81 |             if not row.end_time:
 82 |                 row.end_time = legacy_end
 83 |                 row_changed = True
 84 |             if not row.repeat_cycle:
 85 |                 row.repeat_cycle = "daily"
 86 |                 row_changed = True
 87 |             if not row.default_start_time:
 88 |                 row.default_start_time = row.start_time
 89 |                 row_changed = True
 90 |             if not row.default_end_time:
 91 |                 row.default_end_time = row.end_time
 92 |                 row_changed = True
 93 |             if not row.default_repeat_cycle:
 94 |                 row.default_repeat_cycle = row.repeat_cycle
 95 |                 row_changed = True
 96 |             if row.multi_account is None:
 97 |                 row.multi_account = False
 98 |                 row_changed = True
 99 |             if row.push_enabled is None:
100 |                 row.push_enabled = False
101 |                 row_changed = True
102 | 
103 |             old_cycle = row.repeat_cycle or "daily"
104 |             old_sub = row.repeat_sub_value
105 |             try:
106 |                 new_cycle, new_sub = normalize_legacy_cycle(old_cycle, old_sub)
107 |             except ScheduleError:
108 |                 logger.warning(
109 |                     "旧周期迁移失败：模块 %s 的周期 %s 无效，降级为每月 1 日",
110 |                     row.key,
111 |                     old_cycle,
112 |                 )
113 |                 new_cycle, new_sub = "monthly", "1"
114 |             if new_cycle != old_cycle or row.repeat_sub_value != new_sub:
115 |                 if old_cycle in {"half_month", "quarterly"}:
116 |                     migrated_cycles.append(f"{row.key}: {old_cycle} -> {new_cycle}/{new_sub}")
117 |                 row.repeat_cycle = new_cycle
118 |                 row.repeat_sub_value = new_sub
119 |                 row_changed = True
120 | 
121 |             old_default_cycle = row.default_repeat_cycle or "daily"
122 |             old_default_sub = row.default_repeat_sub_value
123 |             try:
124 |                 new_default_cycle, new_default_sub = normalize_legacy_cycle(
125 |                     old_default_cycle, old_default_sub
126 |                 )
127 |             except ScheduleError:
128 |                 new_default_cycle, new_default_sub = "monthly", "1"
129 |             if (
130 |                 new_default_cycle != old_default_cycle
131 |                 or row.default_repeat_sub_value != new_default_sub
132 |             ):
133 |                 if old_default_cycle in {"half_month", "quarterly"}:
134 |                     migrated_cycles.append(
135 |                         f"{row.key} default: {old_default_cycle} -> "
136 |                         f"{new_default_cycle}/{new_default_sub}"
137 |                     )
138 |                 row.default_repeat_cycle = new_default_cycle
139 |                 row.default_repeat_sub_value = new_default_sub
140 |                 row_changed = True
141 | 
142 |             if row_changed:
143 |                 changed += 1
144 |         if migrated_cycles:
145 |             logger.warning("旧周期迁移：%s", "；".join(migrated_cycles))
146 |         if changed:
147 |             await db.commit()
148 |             logger.info("数据库迁移：已补齐 %s 个模块的随机调度字段", changed)
```
## `backend/app/module_loader.py`
config 子选项与同步逻辑
```text
// backend/app/module_loader.py:98-165
 98 | 
 99 | class ModuleConfig(BaseModel):
100 |     model_config = ConfigDict(extra="allow")
101 | 
102 |     name: str = Field(min_length=1, max_length=120)
103 |     description: str = Field(default="", max_length=2000)
104 |     author: str = Field(default="", max_length=120)
105 |     version: str = Field(default="1.0.0", max_length=40)
106 |     icon: str = Field(default="🧩", max_length=16)
107 |     # Legacy field accepted for old modules; new modules should use the fields below.
108 |     default_cron: str | None = Field(default=None, max_length=100)
109 |     default_start_time: str = Field(default="08:00", max_length=5)
110 |     default_end_time: str = Field(default="10:00", max_length=5)
111 |     default_repeat_cycle: str = Field(default="daily", max_length=20)
112 |     default_repeat_sub_value: str = Field(default="", max_length=10)
113 |     multi_account: bool = False
114 |     params: list[ModuleParam] = Field(default_factory=list)
115 | 
116 |     @model_validator(mode="after")
117 |     def validate_config(self) -> "ModuleConfig":
118 |         if len(self.params) > MAX_PARAMS:
119 |             raise ValueError(f"参数数量不能超过 {MAX_PARAMS} 个")
120 |         seen: set[str] = set()
121 |         for param in self.params:
122 |             if param.key in seen:
123 |                 raise ValueError(f"参数 key 重复：{param.key}")
124 |             seen.add(param.key)
125 | 
126 |         # Backward compatibility: derive a reasonable daily window from a simple
127 |         # legacy cron expression when the new fields were not supplied.
128 |         fields_set = self.model_fields_set
129 |         if self.default_cron and (
130 |             "default_start_time" not in fields_set
131 |             or "default_end_time" not in fields_set
132 |         ):
133 |             derived = _derive_window_from_cron(self.default_cron)
134 |             if derived:
135 |                 if "default_start_time" not in fields_set:
136 |                     self.default_start_time = derived[0]
137 |                 if "default_end_time" not in fields_set:
138 |                     self.default_end_time = derived[1]
139 | 
140 |         legacy_cycle = self.default_repeat_cycle.strip().lower()
141 |         if legacy_cycle in LEGACY_CYCLE_MAP:
142 |             logger.warning(
143 |                 "模块 %s 使用了已移除的周期 %s，已自动降级为每月 1 日",
144 |                 self.name,
145 |                 legacy_cycle,
146 |             )
147 |         try:
148 |             (
149 |                 self.default_start_time,
150 |                 self.default_end_time,
151 |                 self.default_repeat_cycle,
152 |                 self.default_repeat_sub_value,
153 |             ) = validate_schedule(
154 |                 self.default_start_time,
155 |                 self.default_end_time,
156 |                 self.default_repeat_cycle,
157 |                 self.default_repeat_sub_value,
158 |             )
159 |         except ScheduleError as exc:
160 |             raise ValueError(str(exc)) from exc
161 | 
162 |         self.name = self.name.strip() or "未命名模块"
163 |         self.description = self.description.strip()
164 |         return self
165 | 
```
```text
// backend/app/module_loader.py:285-355
285 |                 key=item.key,
286 |                 name=config.name,
287 |                 description=config.description,
288 |                 author=config.author,
289 |                 version=config.version,
290 |                 icon=config.icon or "🧩",
291 |                 default_cron=config.default_cron or "0 8 * * *",
292 |                 cron=config.default_cron or "0 8 * * *",
293 |                 default_start_time=config.default_start_time,
294 |                 default_end_time=config.default_end_time,
295 |                 default_repeat_cycle=config.default_repeat_cycle,
296 |                 default_repeat_sub_value=config.default_repeat_sub_value,
297 |                 start_time=config.default_start_time,
298 |                 end_time=config.default_end_time,
299 |                 repeat_cycle=config.default_repeat_cycle,
300 |                 repeat_sub_value=config.default_repeat_sub_value,
301 |                 multi_account=config.multi_account,
302 |                 push_enabled=False,
303 |                 enabled=False,
304 |                 param_schema=schema,
305 |                 load_error=None,
306 |             )
307 |             db.add(row)
308 |             result.added += 1
309 |         else:
310 |             row.name = config.name
311 |             row.description = config.description
312 |             row.author = config.author
313 |             row.version = config.version
314 |             row.icon = config.icon or "🧩"
315 |             row.default_cron = config.default_cron or row.default_cron or "0 8 * * *"
316 |             row.default_start_time = config.default_start_time
317 |             row.default_end_time = config.default_end_time
318 |             row.default_repeat_cycle = config.default_repeat_cycle
319 |             row.default_repeat_sub_value = config.default_repeat_sub_value
320 |             row.multi_account = bool(config.multi_account)
321 |             # Existing user settings win. Fill only for databases created before
322 |             # the random-schedule migration.
323 |             if not row.start_time:
324 |                 row.start_time = config.default_start_time
325 |             if not row.end_time:
326 |                 row.end_time = config.default_end_time
327 |             if not row.repeat_cycle:
328 |                 row.repeat_cycle = config.default_repeat_cycle
329 |             try:
330 |                 normalized_cycle, normalized_sub = normalize_legacy_cycle(
331 |                     row.repeat_cycle, row.repeat_sub_value
332 |                 )
333 |             except ScheduleError as exc:
334 |                 row.load_error = f"重复周期无效：{exc}"
335 |                 result.invalid.append((item.key, row.load_error))
336 |                 continue
337 |             if normalized_cycle != row.repeat_cycle:
338 |                 logger.info(
339 |                     "模块 %s 的旧周期 %s 已迁移为 %s（子选项 %s）",
340 |                     item.key,
341 |                     row.repeat_cycle,
342 |                     normalized_cycle,
343 |                     normalized_sub,
344 |                 )
345 |             row.repeat_cycle = normalized_cycle
346 |             if not row.repeat_sub_value:
347 |                 row.repeat_sub_value = normalized_sub
348 |             row.param_schema = schema
349 |             row.load_error = None
350 |             result.updated += 1
351 |         result.modules.append(row)
352 | 
353 |     for key, row in existing.items():
354 |         if key in seen:
355 |             continue
```
## `backend/app/schemas.py`
API 字段与周期预览模型
```text
// backend/app/schemas.py:60-135
 60 |     name: str
 61 |     description: str
 62 |     author: str
 63 |     version: str
 64 |     icon: str
 65 | 
 66 |     start_time: str
 67 |     end_time: str
 68 |     repeat_cycle: str
 69 |     repeat_sub_value: str = ""
 70 |     default_start_time: str
 71 |     default_end_time: str
 72 |     default_repeat_cycle: str
 73 |     default_repeat_sub_value: str = ""
 74 | 
 75 |     enabled: bool
 76 |     push_enabled: bool = False
 77 |     multi_account: bool = False
 78 |     load_error: str | None = None
 79 | 
 80 |     last_run_at: datetime | None = None
 81 |     last_status: str | None = None
 82 |     last_message: str | None = None
 83 | 
 84 |     current_schedule_at: datetime | None = None
 85 |     schedule_period_start: date | None = None
 86 |     schedule_status: str | None = None
 87 |     schedule_source: str | None = None
 88 |     schedule_fallback_used: bool = False
 89 |     schedule_note: str | None = None
 90 | 
 91 |     has_params: bool = False
 92 |     param_count: int = 0
 93 |     account_count: int = 0
 94 | 
 95 |     created_at: datetime
 96 |     updated_at: datetime
 97 | 
 98 | 
 99 | class ModuleDetail(ModuleOut):
100 |     param_schema: list[dict[str, Any]] = Field(default_factory=list)
101 |     params: dict[str, Any] = Field(default_factory=dict)
102 |     accounts: list[AccountOut] = Field(default_factory=list)
103 | 
104 | 
105 | class ModuleUpdateRequest(BaseModel):
106 |     start_time: str | None = Field(default=None, max_length=5)
107 |     end_time: str | None = Field(default=None, max_length=5)
108 |     repeat_cycle: str | None = Field(default=None, max_length=20)
109 |     repeat_sub_value: str | None = Field(default=None, max_length=10)
110 |     push_enabled: bool | None = None
111 |     enabled: bool | None = None
112 |     params: dict[str, Any] | None = None
113 |     accounts: list[AccountInput] | None = None
114 | 
115 | 
116 | class ToggleRequest(BaseModel):
117 |     enabled: bool
118 | 
119 | 
120 | class SchedulePreviewRequest(BaseModel):
121 |     start_time: str = Field(max_length=5)
122 |     end_time: str = Field(max_length=5)
123 |     repeat_cycle: str = Field(max_length=20)
124 |     repeat_sub_value: str | None = Field(default=None, max_length=10)
125 | 
126 | 
127 | class SchedulePreviewResponse(BaseModel):
128 |     start_time: str
129 |     end_time: str
130 |     repeat_cycle: str
131 |     repeat_sub_value: str
132 |     label: str
133 |     next_occurrence: date | None = None
134 | 
135 | 
```
## `backend/app/routers/modules.py`
序列化、预览接口、更新校验
```text
// backend/app/routers/modules.py:65-125
 65 |     prefix="/modules",
 66 |     tags=["签到模块"],
 67 |     dependencies=[Depends(get_current_user)],
 68 | )
 69 | 
 70 | 
 71 | # --------------------------------------------------------------- serializers
 72 | def _schedule_fields(module: Module) -> tuple[str, str, str, str]:
 73 |     start = module.start_time or module.default_start_time or "08:00"
 74 |     end = module.end_time or module.default_end_time or "10:00"
 75 |     cycle = module.repeat_cycle or module.default_repeat_cycle or "daily"
 76 |     sub = module.repeat_sub_value
 77 |     if cycle in {"weekly", "monthly", "yearly"} and not sub:
 78 |         sub = module.default_repeat_sub_value or ""
 79 |     if cycle in {"daily", "monthly_15"}:
 80 |         sub = ""
 81 |     return start, end, cycle, sub or ""
 82 | 
 83 | 
 84 | def _safe_account_count(module: Module) -> int:
 85 |     if not module.multi_account:
 86 |         return 1 if module.params_encrypted else 0
 87 |     if not module.accounts_encrypted:
 88 |         return 1 if module.params_encrypted else 0
 89 |     try:
 90 |         value = parameter_cipher.decrypt_any(module.accounts_encrypted)
 91 |         return len(value) if isinstance(value, list) else 0
 92 |     except ParameterDecryptionError:
 93 |         return 0
 94 | 
 95 | 
 96 | def _module_out(module: Module, schedule: ModuleSchedule | None = None) -> ModuleOut:
 97 |     start, end, cycle, sub_value = _schedule_fields(module)
 98 |     account_count = _safe_account_count(module)
 99 |     has_params = account_count > 0 if module.multi_account else bool(module.params_encrypted)
100 |     return ModuleOut(
101 |         id=module.id,
102 |         key=module.key,
103 |         name=module.name,
104 |         description=module.description,
105 |         author=module.author,
106 |         version=module.version,
107 |         icon=module.icon,
108 |         start_time=start,
109 |         end_time=end,
110 |         repeat_cycle=cycle,
111 |         repeat_sub_value=sub_value,
112 |         default_start_time=module.default_start_time or "08:00",
113 |         default_end_time=module.default_end_time or "10:00",
114 |         default_repeat_cycle=module.default_repeat_cycle or "daily",
115 |         default_repeat_sub_value=module.default_repeat_sub_value or "",
116 |         enabled=module.enabled,
117 |         push_enabled=bool(module.push_enabled),
118 |         multi_account=bool(module.multi_account),
119 |         load_error=module.load_error,
120 |         last_run_at=module.last_run_at,
121 |         last_status=module.last_status,
122 |         last_message=module.last_message,
123 |         current_schedule_at=schedule.scheduled_at if schedule else None,
124 |         schedule_period_start=schedule.period_start if schedule else None,
125 |         schedule_status=schedule.status if schedule else "none",
```
```text
// backend/app/routers/modules.py:315-460
315 |             "（默认禁用，请配置账号与随机时间后启用）"
316 |         ),
317 |         module=_module_out(module, await _get_schedule(db, module)),
318 |     )
319 | 
320 | 
321 | @router.post(
322 |     "/schedule-preview",
323 |     response_model=SchedulePreviewResponse,
324 |     include_in_schema=False,
325 | )
326 | @router.post(
327 |     "/schedule/preview",
328 |     response_model=SchedulePreviewResponse,
329 |     summary="预览周期子选项与下一次执行日期",
330 | )
331 | async def preview_schedule(payload: SchedulePreviewRequest) -> SchedulePreviewResponse:
332 |     try:
333 |         start, end, cycle, sub_value = validate_schedule(
334 |             payload.start_time,
335 |             payload.end_time,
336 |             payload.repeat_cycle,
337 |             payload.repeat_sub_value,
338 |         )
339 |     except ScheduleError as exc:
340 |         raise HTTPException(status_code=400, detail=str(exc)) from exc
341 |     today = datetime.now(settings.timezone_info).date()
342 |     try:
343 |         occurrence = next_occurrence(cycle, today, sub_value)
344 |     except ScheduleError as exc:
345 |         raise HTTPException(status_code=400, detail=str(exc)) from exc
346 |     return SchedulePreviewResponse(
347 |         start_time=start,
348 |         end_time=end,
349 |         repeat_cycle=cycle,
350 |         repeat_sub_value=sub_value,
351 |         label=repeat_sub_label(cycle, sub_value),
352 |         next_occurrence=occurrence,
353 |     )
354 | 
355 | 
356 | @router.get("/{module_id}", response_model=ModuleDetail, summary="模块详情、账号与执行时间")
357 | async def get_module(module_id: int, db: AsyncSession = Depends(get_db)) -> ModuleDetail:
358 |     module = await _get_module_or_404(db, module_id)
359 |     return await _module_detail(db, module)
360 | 
361 | 
362 | @router.put("/{module_id}", response_model=ModuleDetail, summary="保存账号、随机时间与推送开关")
363 | async def update_module(
364 |     module_id: int,
365 |     payload: ModuleUpdateRequest,
366 |     db: AsyncSession = Depends(get_db),
367 | ) -> ModuleDetail:
368 |     module = await _get_module_or_404(db, module_id)
369 |     config = _live_config(module)
370 | 
371 |     # Validate/persist schedule window.
372 |     current_start, current_end, current_cycle, current_sub = _schedule_fields(module)
373 |     next_start = payload.start_time if payload.start_time is not None else current_start
374 |     next_end = payload.end_time if payload.end_time is not None else current_end
375 |     next_cycle = (
376 |         payload.repeat_cycle if payload.repeat_cycle is not None else current_cycle
377 |     )
378 |     if payload.repeat_sub_value is not None:
379 |         next_sub = payload.repeat_sub_value
380 |     elif next_cycle != current_cycle:
381 |         next_sub = ""
382 |     else:
383 |         next_sub = current_sub
384 |     try:
385 |         next_start, next_end, next_cycle, next_sub = validate_schedule(
386 |             next_start, next_end, next_cycle, next_sub
387 |         )
388 |     except ScheduleError as exc:
389 |         raise HTTPException(status_code=400, detail=str(exc)) from exc
390 |     schedule_changed = (next_start, next_end, next_cycle, next_sub) != (
391 |         current_start,
392 |         current_end,
393 |         current_cycle,
394 |         current_sub,
395 |     )
396 | 
397 |     # Validate/persist account data according to the live config's mode.
398 |     validated_accounts: list[dict[str, Any]] | None = None
399 |     params_for_check: dict[str, Any] | None = None
400 |     if config.multi_account:
401 |         if payload.params is not None:
402 |             raise HTTPException(
403 |                 status_code=400,
404 |                 detail="该模块启用了多账号模式，请使用 accounts 字段提交账号列表",
405 |             )
406 |         if payload.accounts is not None:
407 |             validated_accounts = _validated_accounts(
408 |                 module, config, [account.model_dump() for account in payload.accounts]
409 |             )
410 |             module.accounts_encrypted = parameter_cipher.encrypt_any(
411 |                 validated_accounts
412 |             )
413 |     else:
414 |         if payload.accounts is not None:
415 |             raise HTTPException(
416 |                 status_code=400, detail="该模块未启用多账号模式，请使用 params 字段"
417 |             )
418 |         if payload.params is not None:
419 |             try:
420 |                 normalized = validate_and_normalize_params(config, payload.params)
421 |             except ModuleConfigError as exc:
422 |                 raise HTTPException(status_code=400, detail=str(exc)) from exc
423 |             module.params_encrypted = parameter_cipher.encrypt(normalized)
424 |             params_for_check = normalized
425 | 
426 |     target_enabled = module.enabled if payload.enabled is None else payload.enabled
427 |     if target_enabled:
428 |         if module.load_error:
429 |             raise HTTPException(
430 |                 status_code=400,
431 |                 detail=f"模块加载异常，暂时无法启用：{module.load_error}",
432 |             )
433 |         if config.multi_account:
434 |             accounts_for_check = (
435 |                 validated_accounts
436 |                 if validated_accounts is not None
437 |                 else _validated_accounts(module, config)
438 |             )
439 |             if not accounts_for_check:
440 |                 raise HTTPException(status_code=400, detail="请至少添加一个账号")
441 |         else:
442 |             params = (
443 |                 params_for_check
444 |                 if params_for_check is not None
445 |                 else _validated_stored_params(module, config)
446 |             )
447 |             # validate_and_normalize_params already enforces required fields.
448 |             _ = params
449 | 
450 |     module.start_time = next_start
451 |     module.end_time = next_end
452 |     module.repeat_cycle = next_cycle
453 |     module.repeat_sub_value = next_sub
454 |     module.multi_account = bool(config.multi_account)
455 |     if payload.push_enabled is not None:
456 |         module.push_enabled = payload.push_enabled
457 |     module.enabled = target_enabled
458 | 
459 |     await db.commit()
460 |     await db.refresh(module)
```
## `backend/app/services/schedules.py`
生成/兜底/重生成传递子选项
```text
// backend/app/services/schedules.py:50-90
50 |         _schedule_locks[module_id] = lock
51 |     return lock
52 | 
53 | 
54 | def _validate_module_schedule(module: Module) -> tuple[str, str, str, str]:
55 |     return validate_schedule(
56 |         module.start_time,
57 |         module.end_time,
58 |         module.repeat_cycle,
59 |         module.repeat_sub_value,
60 |     )
61 | 
62 | 
63 | def _local_now(now: datetime | None = None) -> datetime:
64 |     return (now or datetime.now(timezone.utc)).astimezone(settings.timezone_info)
65 | 
66 | 
67 | async def get_schedule_for_period(
68 |     db: AsyncSession, module_id: int, period_start: date
69 | ) -> ModuleSchedule | None:
70 |     return await db.scalar(
71 |         select(ModuleSchedule).where(
72 |             ModuleSchedule.module_id == module_id,
73 |             ModuleSchedule.period_start == period_start,
74 |         )
75 |     )
76 | 
77 | 
78 | async def current_schedule(
79 |     db: AsyncSession, module: Module, now: datetime | None = None
80 | ) -> ModuleSchedule | None:
81 |     try:
82 |         start, _end, cycle, sub_value = _validate_module_schedule(module)
83 |     except ScheduleError:
84 |         return None
85 |     _ = start
86 |     period = period_start_for(cycle, _local_now(now).date(), sub_value)
87 |     return await get_schedule_for_period(db, module.id, period)
88 | 
89 | 
90 | def _new_schedule(
```
```text
// backend/app/services/schedules.py:120-165
120 |         module = await db.get(Module, module_id)
121 |         if module is None:
122 |             return None
123 |         if only_if_enabled and (not module.enabled or module.load_error):
124 |             return None
125 |         try:
126 |             start_time, end_time, cycle, sub_value = _validate_module_schedule(module)
127 |         except ScheduleError as exc:
128 |             logger.warning("模块 %s 的随机时间配置无效：%s", module.key, exc)
129 |             return None
130 | 
131 |         period = period_start_for(cycle, current_local.date(), sub_value)
132 |         row = await get_schedule_for_period(db, module_id, period)
133 | 
134 |         if row is not None:
135 |             if row.status in {SCHEDULE_EXECUTED, SCHEDULE_RUNNING, SCHEDULE_MISSED}:
136 |                 return row
137 |             if row.status == SCHEDULE_CANCELLED:
138 |                 if current_local.date() != period or current_local >= schedule_window(
139 |                     period, start_time, end_time, settings.timezone_info
140 |                 )[1]:
141 |                     return row
142 |                 scheduled_at = random_scheduled_at(
143 |                     period,
144 |                     start_time,
145 |                     end_time,
146 |                     settings.timezone_info,
147 |                     now=current_local,
148 |                     min_lead_seconds=settings.schedule_min_lead_seconds,
149 |                 )
150 |                 if scheduled_at is None:
151 |                     return row
152 |                 row.scheduled_at = scheduled_at
153 |                 row.status = SCHEDULE_PENDING
154 |                 row.source = "auto"
155 |                 row.fallback_used = False
156 |                 row.generated_at = utcnow()
157 |                 row.executed_at = None
158 |                 row.note = "配置变更后重新生成"
159 |                 await db.commit()
160 |                 await db.refresh(row)
161 |                 return row
162 |             if row.status in {SCHEDULE_PENDING, SCHEDULE_FALLBACK}:
163 |                 now_utc = datetime.now(timezone.utc)
164 |                 if row.scheduled_at > now_utc:
165 |                     return row
```
```text
// backend/app/services/schedules.py:235-325
235 |         async with SessionLocal() as db:
236 |             module = await db.get(Module, module_id)
237 |             if module is None:
238 |                 raise ScheduleError("模块不存在")
239 |             if not module.enabled or module.load_error:
240 |                 raise ScheduleError("请先启用模块并确保模块加载正常")
241 |             try:
242 |                 start_time, end_time, cycle, sub_value = _validate_module_schedule(module)
243 |             except ScheduleError as exc:
244 |                 raise ScheduleError(f"随机时间配置无效：{exc}") from exc
245 | 
246 |             period = period_start_for(cycle, current_local.date(), sub_value)
247 |             if current_local.date() != period:
248 |                 raise ScheduleError("当前不是本周期执行日，无法重新生成")
249 |             _start_dt, end_dt = schedule_window(
250 |                 period, start_time, end_time, settings.timezone_info
251 |             )
252 |             if current_local >= end_dt:
253 |                 raise ScheduleError("本期随机时间窗口已结束，无法重新生成")
254 | 
255 |             row = await get_schedule_for_period(db, module.id, period)
256 |             if row is not None and row.status in {
257 |                 SCHEDULE_RUNNING,
258 |                 SCHEDULE_EXECUTED,
259 |             }:
260 |                 raise ScheduleError("本期任务已执行或正在执行，不能重新生成")
261 | 
262 |             scheduled_at = random_scheduled_at(
263 |                 period,
264 |                 start_time,
265 |                 end_time,
266 |                 settings.timezone_info,
267 |                 now=current_local,
268 |                 min_lead_seconds=settings.schedule_min_lead_seconds,
269 |             )
270 |             if scheduled_at is None:
271 |                 raise ScheduleError("无法在剩余时间窗内生成新的执行时间")
272 | 
273 |             if row is None:
274 |                 row = _new_schedule(
275 |                     module,
276 |                     period,
277 |                     scheduled_at,
278 |                     status=SCHEDULE_PENDING,
279 |                     source="manual",
280 |                     note="手动重新生成",
281 |                 )
282 |                 db.add(row)
283 |             else:
284 |                 row.scheduled_at = scheduled_at
285 |                 row.status = SCHEDULE_PENDING
286 |                 row.source = "manual"
287 |                 row.fallback_used = False
288 |                 row.generated_at = utcnow()
289 |                 row.executed_at = None
290 |                 row.note = "手动重新生成"
291 |             await db.commit()
292 |             await db.refresh(row)
293 |             return row
294 | 
295 | 
296 | async def apply_fallback(
297 |     module_id: int, *, now: datetime | None = None
298 | ) -> tuple[ModuleSchedule | None, bool]:
299 |     """Create a midpoint schedule if no schedule exists for the current period.
300 | 
301 |     Returns (schedule, created).  The caller is responsible for sending the
302 |     "random schedule generation failed" notification when created is True.
303 |     """
304 |     lock = _lock_for(module_id)
305 |     async with lock:
306 |         current_local = _local_now(now)
307 |         async with SessionLocal() as db:
308 |             module = await db.get(Module, module_id)
309 |             if module is None or not module.enabled or module.load_error:
310 |                 return None, False
311 |             try:
312 |                 start_time, end_time, cycle, sub_value = _validate_module_schedule(module)
313 |             except ScheduleError:
314 |                 return None, False
315 | 
316 |             period = period_start_for(cycle, current_local.date(), sub_value)
317 |             if current_local.date() != period:
318 |                 return None, False
319 |             fallback_at = midpoint_scheduled_at(
320 |                 period, start_time, end_time, settings.timezone_info
321 |             )
322 |             existing = await get_schedule_for_period(db, module.id, period)
323 |             if existing is not None and existing.status not in {
324 |                 SCHEDULE_CANCELLED,
325 |                 SCHEDULE_MISSED,
```
```text
// backend/app/services/schedules.py:405-425
405 |     lock = _lock_for(module_id)
406 |     async with lock:
407 |         async with SessionLocal() as db:
408 |             module = await db.get(Module, module_id)
409 |             if module is None:
410 |                 return
411 |             try:
412 |                 _start, _end, cycle, sub_value = _validate_module_schedule(module)
413 |             except ScheduleError:
414 |                 return
415 |             period = period_start_for(cycle, _local_now().date(), sub_value)
416 |             row = await get_schedule_for_period(db, module_id, period)
417 |             if row is not None and row.status in {
418 |                 SCHEDULE_PENDING,
419 |                 SCHEDULE_FALLBACK,
420 |             }:
421 |                 row.status = SCHEDULE_CANCELLED
422 |                 row.note = note[:1000]
423 |                 await db.commit()
424 | 
425 | 
```
## `backend/app/services/scheduler.py`
执行日与下一计划日
```text
// backend/app/services/scheduler.py:155-240
155 |         """Recompute jobs for one module. Safe to call after any config change."""
156 |         self.unschedule_module(module_id)
157 |         module = await self._load_module(module_id)
158 |         if module is None or not module.enabled or module.load_error:
159 |             return False
160 |         try:
161 |             start_time, end_time, cycle, sub_value = validate_schedule(
162 |                 module.start_time,
163 |                 module.end_time,
164 |                 module.repeat_cycle,
165 |                 module.repeat_sub_value,
166 |             )
167 |         except ScheduleError as exc:
168 |             logger.warning("模块 %s 随机时间配置无效：%s", module.key, exc)
169 |             return False
170 | 
171 |         if self._scheduler is None:
172 |             # Unit tests and maintenance scripts may call the service without a
173 |             # running APScheduler; still keep the persisted schedule consistent.
174 |             try:
175 |                 await ensure_current_schedule(module_id)
176 |             except Exception:
177 |                 logger.exception("模块 %s 生成本期随机时间失败", module.key)
178 |                 return False
179 |             return True
180 | 
181 |         # Generate the current period if we're on its start day. Failures are
182 |         # retried by the hourly safety job.
183 |         try:
184 |             schedule = await ensure_current_schedule(module_id)
185 |         except Exception:
186 |             logger.exception("模块 %s 生成本期随机时间失败", module.key)
187 |             schedule = None
188 | 
189 |         now = datetime.now(timezone.utc)
190 |         local_now = now.astimezone(settings.timezone_info)
191 |         today = local_now.date()
192 |         period = period_start_for(cycle, today, sub_value)
193 | 
194 |         # Next occurrence job (local midnight).
195 |         plan_at = next_plan_at(
196 |             cycle, settings.timezone_info, now, sub_value
197 |         )
198 |         try:
199 |             self._add_job(
200 |                 self._make_plan_job(module_id),
201 |                 DateTrigger(run_date=plan_at),
202 |                 self._plan_id(module_id),
203 |                 f"{module.name} 执行日生成随机时间",
204 |             )
205 |         except Exception:
206 |             logger.exception("模块 %s 注册周期计划任务失败", module.key)
207 | 
208 |         # Execution job for the current pending schedule.
209 |         if (
210 |             schedule is not None
211 |             and schedule.status in {SCHEDULE_PENDING, SCHEDULE_FALLBACK}
212 |             and schedule.scheduled_at
213 |             > now - timedelta(seconds=SCHEDULE_MISFIRE_GRACE_SECONDS)
214 |         ):
215 |             try:
216 |                 run_at = schedule.scheduled_at
217 |                 if run_at <= now:
218 |                     # Late recovery within APScheduler's grace window.
219 |                     run_at = now + timedelta(seconds=1)
220 |                 self._add_job(
221 |                     self._make_execution_job(module_id, schedule.id),
222 |                     DateTrigger(run_date=run_at),
223 |                     self._exec_id(module_id),
224 |                     f"{module.name} 随机执行",
225 |                 )
226 |                 logger.info(
227 |                     "模块 %s 已安排本次执行：%s（%s，%s-%s）",
228 |                     module.key,
229 |                     schedule.scheduled_at.astimezone(settings.timezone_info).strftime(
230 |                         "%Y-%m-%d %H:%M:%S"
231 |                     ),
232 |                     repeat_sub_label(cycle, sub_value),
233 |                     start_time,
234 |                     end_time,
235 |                 )
236 |             except Exception:
237 |                 logger.exception("模块 %s 注册执行任务失败", module.key)
238 | 
239 |         # Midpoint watchdog: it only creates a fallback if no schedule exists at
240 |         # midnight/through the retries.  If the midpoint has already passed and no
```
## `backend/tests/test_core.py`
周期/子选项/闰年测试
```text
// backend/tests/test_core.py:68-200
 68 | def test_schedule_validation_and_five_cycles() -> None:
 69 |     assert validate_schedule("08:00", "10:00", "daily") == (
 70 |         "08:00",
 71 |         "10:00",
 72 |         "daily",
 73 |         "",
 74 |     )
 75 |     assert validate_schedule("08:00", "10:00", "weekly", "5") == (
 76 |         "08:00",
 77 |         "10:00",
 78 |         "weekly",
 79 |         "5",
 80 |     )
 81 |     assert validate_schedule("08:00", "10:00", "monthly_15") == (
 82 |         "08:00",
 83 |         "10:00",
 84 |         "monthly_15",
 85 |         "",
 86 |     )
 87 |     assert validate_schedule("08:00", "10:00", "monthly", "28")[3] == "28"
 88 |     assert validate_schedule("08:00", "10:00", "yearly", "2-29")[3] == "2-29"
 89 | 
 90 |     # Legacy cycles are accepted only for migration/config compatibility and
 91 |     # normalized to the new monthly-1st representation.
 92 |     assert normalize_legacy_cycle("half_month", "") == ("monthly", "1")
 93 |     assert normalize_legacy_cycle("quarterly", "") == ("monthly", "1")
 94 |     assert validate_schedule("08:00", "10:00", "half_month")[2:] == ("monthly", "1")
 95 | 
 96 |     with pytest.raises(ScheduleError):
 97 |         validate_schedule("9:00", "10:00", "daily")
 98 |     with pytest.raises(ScheduleError):
 99 |         validate_schedule("10:00", "10:00", "daily")
100 |     with pytest.raises(ScheduleError):
101 |         validate_schedule("11:00", "10:00", "daily")
102 |     with pytest.raises(ScheduleError):
103 |         validate_schedule("08:00", "10:00", "fortnightly")
104 |     with pytest.raises(ScheduleError):
105 |         validate_schedule("25:00", "26:00", "daily")
106 |     for cycle, sub in [
107 |         ("weekly", "0"),
108 |         ("weekly", "8"),
109 |         ("monthly", "0"),
110 |         ("monthly", "29"),
111 |         ("yearly", "2-30"),
112 |         ("yearly", "13-1"),
113 |         ("yearly", "bad"),
114 |     ]:
115 |         with pytest.raises(ScheduleError):
116 |             validate_schedule("08:00", "10:00", cycle, sub)
117 | 
118 |     day = date(2026, 10, 18)  # Sunday
119 |     assert period_start_for("daily", day) == day
120 |     assert period_start_for("weekly", day, "7") == day
121 |     assert period_start_for("weekly", day, "1") == date(2026, 10, 12)
122 |     assert period_start_for("monthly_15", day) == date(2026, 10, 15)
123 |     assert period_start_for("monthly_15", date(2026, 10, 10)) == date(
124 |         2026, 9, 15
125 |     )
126 |     assert period_start_for("monthly", day, "1") == date(2026, 10, 1)
127 |     assert period_start_for("monthly", day, "28") == date(2026, 9, 28)
128 |     assert period_start_for("yearly", day, "10-1") == date(2026, 10, 1)
129 |     assert period_start_for("yearly", day, "12-31") == date(2025, 12, 31)
130 |     assert period_start_for("yearly", date(2026, 3, 1), "2-29") == date(
131 |         2024, 2, 29
132 |     )
133 | 
134 |     assert next_period_start("daily", date(2026, 10, 18)) == date(2026, 10, 19)
135 |     assert next_period_start("weekly", date(2026, 10, 12), "1") == date(
136 |         2026, 10, 19
137 |     )
138 |     assert next_period_start("monthly_15", date(2026, 10, 15)) == date(
139 |         2026, 11, 15
140 |     )
141 |     assert next_period_start("monthly", date(2026, 10, 28), "28") == date(
142 |         2026, 11, 28
143 |     )
144 |     assert next_period_start("yearly", date(2026, 1, 1), "1-1") == date(
145 |         2027, 1, 1
146 |     )
147 |     assert next_period_start("yearly", date(2024, 2, 29), "2-29") == date(
148 |         2028, 2, 29
149 |     )
150 |     assert next_occurrence("weekly", date(2026, 10, 18), "5") == date(
151 |         2026, 10, 23
152 |     )
153 |     assert next_occurrence("yearly", date(2026, 1, 1), "2-29") == date(
154 |         2028, 2, 29
155 |     )
156 | 
157 | 
158 | def test_schedule_windows_and_random_generation() -> None:
159 |     start, end = schedule_window(date(2026, 10, 18), "09:00", "10:00", TZ)
160 |     assert start.hour == 9 and end.hour == 10
161 |     midpoint = midpoint_scheduled_at(date(2026, 10, 18), "09:00", "10:00", TZ)
162 |     assert midpoint == datetime(2026, 10, 18, 1, 30, tzinfo=timezone.utc)
163 | 
164 |     generated = random_scheduled_at(
165 |         date(2026, 10, 18),
166 |         "09:00",
167 |         "10:00",
168 |         TZ,
169 |         now=datetime(2026, 10, 18, 0, 0, tzinfo=timezone.utc),
170 |     )
171 |     assert generated is not None
172 |     local = generated.astimezone(TZ)
173 |     assert local.date() == date(2026, 10, 18)
174 |     assert (local.hour, local.minute) >= (9, 0)
175 |     assert (local.hour, local.minute) <= (10, 0)
176 | 
177 |     after_end = random_scheduled_at(
178 |         date(2026, 10, 18),
179 |         "09:00",
180 |         "10:00",
181 |         TZ,
182 |         now=datetime(2026, 10, 18, 3, 0, tzinfo=timezone.utc),
183 |     )
184 |     assert after_end is None
185 | 
186 |     plan = next_plan_at(
187 |         "daily",
188 |         TZ,
189 |         now=datetime(2026, 10, 18, 0, 0, tzinfo=timezone.utc),
190 |     )
191 |     assert plan == datetime(2026, 10, 19, 0, 0, tzinfo=TZ)
192 |     weekly_plan = next_plan_at(
193 |         "weekly",
194 |         TZ,
195 |         now=datetime(2026, 10, 18, 0, 0, tzinfo=timezone.utc),
196 |         repeat_sub_value="7",
197 |     )
198 |     assert weekly_plan == datetime(2026, 10, 25, 0, 0, tzinfo=TZ)
199 |     monthly_plan = next_plan_at(
200 |         "monthly",
```
## `backend/tests/test_api.py`
API 5 组合与预览 401
```text
// backend/tests/test_api.py:88-155
 88 |             "mode": "success",
 89 |             "retries": 1,
 90 |             "verbose": False,
 91 |         }
 92 | 
 93 |         # All five cycles and their sub-options persist; invalid values are rejected.
 94 |         cycle_cases = [
 95 |             ("daily", ""),
 96 |             ("weekly", "5"),
 97 |             ("monthly_15", ""),
 98 |             ("monthly", "28"),
 99 |             ("yearly", "2-29"),
100 |         ]
101 |         for cycle, sub_value in cycle_cases:
102 |             response = await client.put(
103 |                 f"/api/modules/{module_id}",
104 |                 headers=headers,
105 |                 json={
106 |                     **FULL_DAY,
107 |                     "repeat_cycle": cycle,
108 |                     "repeat_sub_value": sub_value,
109 |                     "params": params,
110 |                     "enabled": False,
111 |                 },
112 |             )
113 |             assert response.status_code == 200, response.text
114 |             payload = response.json()
115 |             assert payload["repeat_cycle"] == cycle
116 |             assert payload["repeat_sub_value"] == sub_value
117 |         for payload in [
118 |             {**FULL_DAY, "repeat_cycle": "fortnightly", "params": params},
119 |             {**FULL_DAY, "start_time": "23:00", "end_time": "01:00", "params": params},
120 |             {**FULL_DAY, "repeat_cycle": "weekly", "repeat_sub_value": "8", "params": params},
121 |             {**FULL_DAY, "repeat_cycle": "monthly", "repeat_sub_value": "29", "params": params},
122 |             {**FULL_DAY, "repeat_cycle": "yearly", "repeat_sub_value": "2-30", "params": params},
123 |         ]:
124 |             response = await client.put(
125 |                 f"/api/modules/{module_id}", headers=headers, json=payload
126 |             )
127 |             assert response.status_code == 400, response.text
128 | 
129 |         preview = await client.post(
130 |             "/api/modules/schedule/preview",
131 |             headers=headers,
132 |             json={
133 |                 "start_time": "09:00",
134 |                 "end_time": "11:00",
135 |                 "repeat_cycle": "weekly",
136 |                 "repeat_sub_value": "5",
137 |             },
138 |         )
139 |         assert preview.status_code == 200, preview.text
140 |         assert preview.json()["repeat_cycle"] == "weekly"
141 |         assert preview.json()["repeat_sub_value"] == "5"
142 |         assert preview.json()["next_occurrence"]
143 |         preview_body = {
144 |             "start_time": "09:00",
145 |             "end_time": "11:00",
146 |             "repeat_cycle": "daily",
147 |             "repeat_sub_value": "",
148 |         }
149 |         assert (
150 |             await client.post("/api/modules/schedule-preview", json=preview_body)
151 |         ).status_code == 401
152 |         assert (
153 |             await client.post("/api/modules/schedule/preview", json=preview_body)
154 |         ).status_code == 401
155 | 
```
## `frontend/src/utils/schedule.js`
前端周期/子选项工具（完整）
```text
// frontend/src/utils/schedule.js:1-192
  1 | export const REPEAT_CYCLES = [
  2 |   {
  3 |     value: 'daily',
  4 |     label: '每日',
  5 |     description: '每天在时间窗内随机执行一次',
  6 |   },
  7 |   {
  8 |     value: 'weekly',
  9 |     label: '每周',
 10 |     description: '在选定的星期几，于时间窗内随机执行一次',
 11 |   },
 12 |   {
 13 |     value: 'monthly_15',
 14 |     label: '每月15日',
 15 |     description: '每月 15 日在时间窗内随机执行一次（大小月统一）',
 16 |   },
 17 |   {
 18 |     value: 'monthly',
 19 |     label: '每月',
 20 |     description: '在选定的日期（1–28 日），于时间窗内随机执行一次',
 21 |   },
 22 |   {
 23 |     value: 'yearly',
 24 |     label: '每年',
 25 |     description: '在选定的月-日，于时间窗内随机执行一次',
 26 |   },
 27 | ]
 28 | 
 29 | export const WEEKDAY_OPTIONS = [
 30 |   { value: '1', label: '周一' },
 31 |   { value: '2', label: '周二' },
 32 |   { value: '3', label: '周三' },
 33 |   { value: '4', label: '周四' },
 34 |   { value: '5', label: '周五' },
 35 |   { value: '6', label: '周六' },
 36 |   { value: '7', label: '周日' },
 37 | ]
 38 | 
 39 | export const MONTH_OPTIONS = Array.from({ length: 12 }, (_, index) => ({
 40 |   value: String(index + 1),
 41 |   label: `${index + 1} 月`,
 42 | }))
 43 | 
 44 | export const MONTHLY_DAY_OPTIONS = Array.from({ length: 28 }, (_, index) => ({
 45 |   value: String(index + 1),
 46 |   label: `${index + 1} 日`,
 47 | }))
 48 | 
 49 | export const TIME_PATTERN = /^(?:[01]\d|2[0-3]):[0-5]\d$/
 50 | 
 51 | export function isValidTime(value) {
 52 |   return TIME_PATTERN.test(String(value || '').trim())
 53 | }
 54 | 
 55 | export function validateSchedule(startTime, endTime) {
 56 |   if (!isValidTime(startTime)) {
 57 |     return '开始时间必须是 24 小时制 HH:mm，例如 09:00'
 58 |   }
 59 |   if (!isValidTime(endTime)) {
 60 |     return '结束时间必须是 24 小时制 HH:mm，例如 11:30'
 61 |   }
 62 |   if (String(startTime).trim() >= String(endTime).trim()) {
 63 |     return '开始时间必须早于结束时间（时间窗不能跨天）'
 64 |   }
 65 |   return ''
 66 | }
 67 | 
 68 | export function cycleMeta(value) {
 69 |   return REPEAT_CYCLES.find((item) => item.value === value) || REPEAT_CYCLES[0]
 70 | }
 71 | 
 72 | export function cycleLabel(value) {
 73 |   return cycleMeta(value).label
 74 | }
 75 | 
 76 | export function daysInYearMonth(month) {
 77 |   const monthNumber = Number(month)
 78 |   if (!Number.isInteger(monthNumber) || monthNumber < 1 || monthNumber > 12) {
 79 |     return 0
 80 |   }
 81 |   // Use a leap year so February offers 29; the backend skips non-leap years.
 82 |   return new Date(2024, monthNumber, 0).getDate()
 83 | }
 84 | 
 85 | export function yearlyParts(value) {
 86 |   const match = String(value || '').match(/^(\d{1,2})-(\d{1,2})$/)
 87 |   if (!match) return { month: '1', day: '1' }
 88 |   return { month: match[1], day: match[2] }
 89 | }
 90 | 
 91 | export function formatYearSub(month, day) {
 92 |   return `${Number(month)}-${Number(day)}`
 93 | }
 94 | 
 95 | export function normalizeRepeatSubValue(cycle, value) {
 96 |   const text = String(value ?? '').trim()
 97 |   if (cycle === 'daily' || cycle === 'monthly_15') return ''
 98 |   if (cycle === 'weekly') {
 99 |     const number = Number(text || 1)
100 |     return Number.isInteger(number) && number >= 1 && number <= 7
101 |       ? String(number)
102 |       : '1'
103 |   }
104 |   if (cycle === 'monthly') {
105 |     const number = Number(text || 1)
106 |     return Number.isInteger(number) && number >= 1 && number <= 28
107 |       ? String(number)
108 |       : '1'
109 |   }
110 |   if (cycle === 'yearly') {
111 |     const { month, day } = yearlyParts(text)
112 |     const monthNumber = Number(month)
113 |     const dayNumber = Number(day)
114 |     if (
115 |       Number.isInteger(monthNumber) &&
116 |       monthNumber >= 1 &&
117 |       monthNumber <= 12 &&
118 |       Number.isInteger(dayNumber) &&
119 |       dayNumber >= 1 &&
120 |       dayNumber <= daysInYearMonth(monthNumber)
121 |     ) {
122 |       return formatYearSub(monthNumber, dayNumber)
123 |     }
124 |     return '1-1'
125 |   }
126 |   return ''
127 | }
128 | 
129 | export function validateRepeatSubValue(cycle, value) {
130 |   if (cycle === 'daily' || cycle === 'monthly_15') return ''
131 |   if (cycle === 'weekly') {
132 |     const number = Number(value)
133 |     return Number.isInteger(number) && number >= 1 && number <= 7
134 |       ? ''
135 |       : '请选择星期几'
136 |   }
137 |   if (cycle === 'monthly') {
138 |     const number = Number(value)
139 |     return Number.isInteger(number) && number >= 1 && number <= 28
140 |       ? ''
141 |       : '请选择 1–28 日之间的日期'
142 |   }
143 |   if (cycle === 'yearly') {
144 |     const { month, day } = yearlyParts(value)
145 |     const monthNumber = Number(month)
146 |     const dayNumber = Number(day)
147 |     return Number.isInteger(monthNumber) &&
148 |       monthNumber >= 1 &&
149 |       monthNumber <= 12 &&
150 |       Number.isInteger(dayNumber) &&
151 |       dayNumber >= 1 &&
152 |       dayNumber <= daysInYearMonth(monthNumber)
153 |       ? ''
154 |       : '请选择有效的月-日'
155 |   }
156 |   return '重复周期无效'
157 | }
158 | 
159 | export function cycleDayLabel(value, subValue = '') {
160 |   const cycle = value || 'daily'
161 |   const sub = normalizeRepeatSubValue(cycle, subValue)
162 |   if (cycle === 'daily') return '每天'
163 |   if (cycle === 'weekly') {
164 |     const weekday = WEEKDAY_OPTIONS.find((item) => item.value === sub)
165 |     return `每周${weekday ? weekday.label.replace('周', '') : '一'}`
166 |   }
167 |   if (cycle === 'monthly_15') return '每月15日'
168 |   if (cycle === 'monthly') return `每月${sub}日`
169 |   const { month, day } = yearlyParts(sub)
170 |   return `每年${Number(month)}月${Number(day)}日`
171 | }
172 | 
173 | export function describeSchedule(startTime, endTime, repeatCycle, repeatSubValue = '') {
174 |   if (!isValidTime(startTime) || !isValidTime(endTime)) {
175 |     return '尚未设置有效的时间窗'
176 |   }
177 |   return `${cycleDayLabel(repeatCycle, repeatSubValue)} ${startTime}–${endTime} 之间随机执行`
178 | }
179 | 
180 | export const SCHEDULE_STATUS_META = {
181 |   none: { label: '未生成', className: 'is-idle' },
182 |   pending: { label: '待执行', className: 'is-pending' },
183 |   fallback: { label: '兜底时间', className: 'is-fallback' },
184 |   running: { label: '执行中', className: 'is-running' },
185 |   executed: { label: '已执行', className: 'is-success' },
186 |   missed: { label: '已错过', className: 'is-failed' },
187 |   cancelled: { label: '已取消', className: 'is-idle' },
188 | }
189 | 
190 | export function scheduleStatusMeta(status) {
191 |   return SCHEDULE_STATUS_META[status] || SCHEDULE_STATUS_META.none
192 | }
```
## `frontend/src/components/RandomScheduleField.vue`
条件子控件模板与逻辑
```text
// frontend/src/components/RandomScheduleField.vue:1-222
  1 | <template>
  2 |   <div class="random-schedule-field">
  3 |     <div class="time-row">
  4 |       <div class="time-control">
  5 |         <label class="field-label">开始时间</label>
  6 |         <el-input
  7 |           :model-value="startTime"
  8 |           maxlength="5"
  9 |           placeholder="HH:mm"
 10 |           clearable
 11 |           spellcheck="false"
 12 |           class="time-input"
 13 |           @update:model-value="(value) => emit('update:start-time', value)"
 14 |           @blur="normalizeTime('start')"
 15 |         >
 16 |           <template #prefix><el-icon><Clock /></el-icon></template>
 17 |         </el-input>
 18 |       </div>
 19 |       <span class="time-separator">—</span>
 20 |       <div class="time-control">
 21 |         <label class="field-label">结束时间</label>
 22 |         <el-input
 23 |           :model-value="endTime"
 24 |           maxlength="5"
 25 |           placeholder="HH:mm"
 26 |           clearable
 27 |           spellcheck="false"
 28 |           class="time-input"
 29 |           @update:model-value="(value) => emit('update:end-time', value)"
 30 |           @blur="normalizeTime('end')"
 31 |         >
 32 |           <template #prefix><el-icon><Clock /></el-icon></template>
 33 |         </el-input>
 34 |       </div>
 35 |     </div>
 36 | 
 37 |     <div class="cycle-control">
 38 |       <label class="field-label">重复周期</label>
 39 |       <el-select
 40 |         :model-value="repeatCycle"
 41 |         class="full-width"
 42 |         @update:model-value="handleCycleChange"
 43 |       >
 44 |         <el-option
 45 |           v-for="item in REPEAT_CYCLES"
 46 |           :key="item.value"
 47 |           :label="item.label"
 48 |           :value="item.value"
 49 |         />
 50 |       </el-select>
 51 |     </div>
 52 | 
 53 |     <div v-if="repeatCycle === 'weekly'" class="cycle-control sub-control">
 54 |       <label class="field-label">星期几</label>
 55 |       <el-select
 56 |         :model-value="normalizedSub"
 57 |         class="full-width"
 58 |         @update:model-value="updateSubValue"
 59 |       >
 60 |         <el-option
 61 |           v-for="item in WEEKDAY_OPTIONS"
 62 |           :key="item.value"
 63 |           :label="item.label"
 64 |           :value="item.value"
 65 |         />
 66 |       </el-select>
 67 |     </div>
 68 | 
 69 |     <div v-else-if="repeatCycle === 'monthly'" class="cycle-control sub-control">
 70 |       <label class="field-label">日期（上限 28）</label>
 71 |       <el-select
 72 |         :model-value="normalizedSub"
 73 |         class="full-width"
 74 |         @update:model-value="updateSubValue"
 75 |       >
 76 |         <el-option
 77 |           v-for="item in MONTHLY_DAY_OPTIONS"
 78 |           :key="item.value"
 79 |           :label="item.label"
 80 |           :value="item.value"
 81 |         />
 82 |       </el-select>
 83 |     </div>
 84 | 
 85 |     <div v-else-if="repeatCycle === 'yearly'" class="cycle-control sub-control">
 86 |       <label class="field-label">月-日</label>
 87 |       <div class="year-row">
 88 |         <el-select
 89 |           :model-value="yearParts.month"
 90 |           class="year-part"
 91 |           @update:model-value="handleYearMonthChange"
 92 |         >
 93 |           <el-option
 94 |             v-for="item in MONTH_OPTIONS"
 95 |             :key="item.value"
 96 |             :label="item.label"
 97 |             :value="item.value"
 98 |           />
 99 |         </el-select>
100 |         <el-select
101 |           :model-value="yearParts.day"
102 |           class="year-part"
103 |           @update:model-value="handleYearDayChange"
104 |         >
105 |           <el-option
106 |             v-for="item in yearDayOptions"
107 |             :key="item.value"
108 |             :label="item.label"
109 |             :value="item.value"
110 |           />
111 |         </el-select>
112 |       </div>
113 |     </div>
114 | 
115 |     <div class="schedule-description" :class="{ invalid: Boolean(error) }">
116 |       <el-icon v-if="error"><WarningFilled /></el-icon>
117 |       <el-icon v-else><Calendar /></el-icon>
118 |       <span>{{ error || description }}</span>
119 |     </div>
120 |     <p class="schedule-hint">
121 |       在每个周期的执行日，于上述时间窗内均匀随机选择一个执行时间。时间窗不能跨天；
122 |       每年 2 月 29 日仅在闰年执行。
123 |     </p>
124 |   </div>
125 | </template>
126 | 
127 | <script setup>
128 | import { computed } from 'vue'
129 | import {
130 |   MONTHLY_DAY_OPTIONS,
131 |   MONTH_OPTIONS,
132 |   REPEAT_CYCLES,
133 |   WEEKDAY_OPTIONS,
134 |   daysInYearMonth,
135 |   describeSchedule,
136 |   formatYearSub,
137 |   isValidTime,
138 |   normalizeRepeatSubValue,
139 |   validateRepeatSubValue,
140 |   validateSchedule,
141 |   yearlyParts,
142 | } from '@/utils/schedule'
143 | 
144 | const props = defineProps({
145 |   startTime: { type: String, default: '08:00' },
146 |   endTime: { type: String, default: '10:00' },
147 |   repeatCycle: { type: String, default: 'daily' },
148 |   repeatSubValue: { type: String, default: '' },
149 | })
150 | 
151 | const emit = defineEmits([
152 |   'update:start-time',
153 |   'update:end-time',
154 |   'update:repeat-cycle',
155 |   'update:repeat-sub-value',
156 | ])
157 | 
158 | const normalizedSub = computed(() =>
159 |   normalizeRepeatSubValue(props.repeatCycle, props.repeatSubValue),
160 | )
161 | const yearParts = computed(() => yearlyParts(normalizedSub.value))
162 | const yearDayOptions = computed(() =>
163 |   Array.from({ length: daysInYearMonth(yearParts.value.month) }, (_, index) => ({
164 |     value: String(index + 1),
165 |     label: `${index + 1} 日`,
166 |   })),
167 | )
168 | const timeError = computed(() => validateSchedule(props.startTime, props.endTime))
169 | const subError = computed(() =>
170 |   validateRepeatSubValue(props.repeatCycle, normalizedSub.value),
171 | )
172 | const error = computed(() => timeError.value || subError.value)
173 | const description = computed(() =>
174 |   describeSchedule(
175 |     props.startTime,
176 |     props.endTime,
177 |     props.repeatCycle,
178 |     normalizedSub.value,
179 |   ),
180 | )
181 | 
182 | function updateSubValue(value) {
183 |   emit(
184 |     'update:repeat-sub-value',
185 |     normalizeRepeatSubValue(props.repeatCycle, value),
186 |   )
187 | }
188 | 
189 | function handleCycleChange(value) {
190 |   emit('update:repeat-cycle', value)
191 |   emit(
192 |     'update:repeat-sub-value',
193 |     normalizeRepeatSubValue(value, props.repeatSubValue),
194 |   )
195 | }
196 | 
197 | function handleYearMonthChange(month) {
198 |   const maxDay = daysInYearMonth(month)
199 |   const day = Math.min(Number(yearParts.value.day) || 1, maxDay)
200 |   emit('update:repeat-sub-value', formatYearSub(month, day))
201 | }
202 | 
203 | function handleYearDayChange(day) {
204 |   emit(
205 |     'update:repeat-sub-value',
206 |     formatYearSub(yearParts.value.month, day),
207 |   )
208 | }
209 | 
210 | function normalizeTime(which) {
211 |   const raw = String(which === 'start' ? props.startTime : props.endTime || '').trim()
212 |   if (!isValidTime(raw)) return
213 |   const [hour, minute] = raw.split(':')
214 |   const normalized = `${hour.padStart(2, '0')}:${minute}`
215 |   if (which === 'start' && normalized !== props.startTime) {
216 |     emit('update:start-time', normalized)
217 |   }
218 |   if (which === 'end' && normalized !== props.endTime) {
219 |     emit('update:end-time', normalized)
220 |   }
221 | }
222 | </script>
```
## `frontend/src/views/ModuleDetailView.vue`
模块配置页子选项接线
```text
// frontend/src/views/ModuleDetailView.vue:190-215
190 |                     <div class="panel-title">随机执行时间</div>
191 |                     <div class="panel-desc">执行日 00:00 生成随机时间，保存后立即重新安排</div>
192 |                   </div>
193 |                   <span class="cron-icon"><el-icon><Timer /></el-icon></span>
194 |                 </div>
195 |                 <div class="panel-body">
196 |                   <RandomScheduleField
197 |                     :start-time="startTime"
198 |                     :end-time="endTime"
199 |                     :repeat-cycle="repeatCycle"
200 |                     :repeat-sub-value="repeatSubValue"
201 |                     @update:start-time="(value) => (startTime = value)"
202 |                     @update:end-time="(value) => (endTime = value)"
203 |                     @update:repeat-cycle="(value) => (repeatCycle = value)"
204 |                     @update:repeat-sub-value="(value) => (repeatSubValue = value)"
205 |                   />
206 | 
207 |                   <div class="schedule-summary">
208 |                     <div class="summary-row">
209 |                       <span>当前已保存</span>
210 |                       <code>{{ module.start_time }}–{{ module.end_time }} · {{ cycleDayLabel(module.repeat_cycle, module.repeat_sub_value) }}</code>
211 |                     </div>
212 |                     <div class="summary-row">
213 |                       <span>本次执行时间</span>
214 |                       <strong>{{ currentScheduleLabel }}</strong>
215 |                     </div>
```
```text
// frontend/src/views/ModuleDetailView.vue:468-482
468 | 
469 | const loading = ref(true)
470 | const notFound = ref(false)
471 | const module = ref(null)
472 | const params = reactive({})
473 | const accounts = ref([])
474 | const paramsFormRef = ref(null)
475 | const startTime = ref('08:00')
476 | const endTime = ref('10:00')
477 | const repeatCycle = ref('daily')
478 | const repeatSubValue = ref('')
479 | const pushEnabled = ref(false)
480 | const activeTab = ref(route.query.tab === 'logs' ? 'logs' : 'config')
481 | const saving = ref(false)
482 | const toggleLoading = ref(false)
```
```text
// frontend/src/views/ModuleDetailView.vue:565-580
565 |     list = [createAccount(schema)]
566 |   }
567 |   accounts.value = list
568 | }
569 | 
570 | function applyModule(detail) {
571 |   module.value = detail
572 |   startTime.value = detail.start_time || '08:00'
573 |   endTime.value = detail.end_time || '10:00'
574 |   repeatCycle.value = detail.repeat_cycle || 'daily'
575 |   repeatSubValue.value =
576 |     detail.repeat_sub_value || detail.default_repeat_sub_value || ''
577 |   pushEnabled.value = Boolean(detail.push_enabled)
578 |   if (detail.multi_account) {
579 |     Object.keys(params).forEach((key) => delete params[key])
580 |     hydrateAccounts(detail)
```
```text
// frontend/src/views/ModuleDetailView.vue:650-718
650 |     }
651 |   } else if (paramsFormRef.value) {
652 |     try {
653 |       await paramsFormRef.value.validate()
654 |     } catch {
655 |       ElMessage.warning('请先完善必填参数')
656 |       return
657 |     }
658 |   }
659 | 
660 |   saving.value = true
661 |   try {
662 |     repeatSubValue.value = normalizeRepeatSubValue(
663 |       repeatCycle.value,
664 |       repeatSubValue.value,
665 |     )
666 |     const payload = {
667 |       start_time: String(startTime.value).trim(),
668 |       end_time: String(endTime.value).trim(),
669 |       repeat_cycle: repeatCycle.value,
670 |       repeat_sub_value: repeatSubValue.value,
671 |       push_enabled: pushEnabled.value,
672 |     }
673 |     if (module.value.multi_account) {
674 |       payload.accounts = accounts.value.map((account) => ({
675 |         id: account.id,
676 |         label: account.label || '',
677 |         params: { ...account.params },
678 |       }))
679 |     } else {
680 |       payload.params = { ...params }
681 |     }
682 |     const detail = await modulesApi.update(module.value.id, payload)
683 |     applyModule(detail)
684 |     ElMessage.success('配置已保存，随机执行时间已按最新设置安排')
685 |   } catch {
686 |     // Error shown by the HTTP layer.
687 |   } finally {
688 |     saving.value = false
689 |   }
690 | }
691 | 
692 | async function regenerateSchedule() {
693 |   if (!module.value?.enabled) {
694 |     ElMessage.warning('请先启用模块后再重新生成')
695 |     return
696 |   }
697 |   regenerating.value = true
698 |   try {
699 |     const result = await modulesApi.regenerateSchedule(module.value.id)
700 |     mergeSummary(result.module)
701 |     ElMessage.success(result.message || '本期随机执行时间已重新生成')
702 |   } catch {
703 |     // Error shown by the HTTP layer.
704 |   } finally {
705 |     regenerating.value = false
706 |   }
707 | }
708 | 
709 | function resetDefaultSchedule() {
710 |   startTime.value = module.value.default_start_time
711 |   endTime.value = module.value.default_end_time
712 |   repeatCycle.value = module.value.default_repeat_cycle
713 |   repeatSubValue.value = module.value.default_repeat_sub_value || ''
714 | }
715 | 
716 | async function toggleEnabled() {
717 |   if (toggleLoading.value || module.value.load_error) return false
718 |   toggleLoading.value = true
```
## `frontend/src/views/ModulesView.vue`
列表执行日展示
```text
// frontend/src/views/ModulesView.vue:145-152
145 |         <div class="card-meta">
146 |           <div class="meta-row">
147 |             <span class="meta-label"><el-icon><Timer /></el-icon>时间窗</span>
148 |             <span class="meta-value cron-value">
149 |               <code>{{ module.start_time }}–{{ module.end_time }}</code>
150 |               <em>{{ cycleDayLabel(module.repeat_cycle, module.repeat_sub_value) }}</em>
151 |             </span>
152 |           </div>
```
```text
// frontend/src/views/ModulesView.vue:350-356
350 | import ModuleIcon from '@/components/ModuleIcon.vue'
351 | import StatusTag from '@/components/StatusTag.vue'
352 | import RunLogDrawer from '@/components/RunLogDrawer.vue'
353 | import { modulesApi } from '@/api'
354 | import { cycleDayLabel, scheduleStatusMeta } from '@/utils/schedule'
355 | import { formatDateTime, timeFromNow } from '@/utils/format'
356 | 
```
## `frontend/src/views/DashboardView.vue`
仪表盘执行日展示
```text
// frontend/src/views/DashboardView.vue:42-54
42 |               <span class="next-eyebrow"><i></i> NEXT RUN</span>
43 |               <span class="next-cron mono">{{ nextModule.start_time }}–{{ nextModule.end_time }}</span>
44 |             </div>
45 |             <div class="next-main">
46 |               <ModuleIcon :icon="nextModule.icon" :size="46" :tone="nextModule.id" />
47 |               <div class="next-info">
48 |                 <strong>{{ nextModule.name }}</strong>
49 |                 <span>{{ describeSchedule(nextModule.start_time, nextModule.end_time, nextModule.repeat_cycle, nextModule.repeat_sub_value) }}</span>
50 |               </div>
51 |             </div>
52 |             <div class="next-time-row">
53 |               <span class="next-date">{{ nextDateLabel }}</span>
54 |               <strong class="next-clock">{{ nextClockLabel }}</strong>
```
```text
// frontend/src/views/DashboardView.vue:218-229
218 |                 class="upcoming-item"
219 |                 @click="router.push(`/modules/${item.id}`)"
220 |               >
221 |                 <ModuleIcon :icon="item.icon" :size="36" :tone="index + item.id" />
222 |                 <div class="upcoming-copy">
223 |                   <strong>{{ item.name }}</strong>
224 |                   <span>{{ describeSchedule(item.start_time, item.end_time, item.repeat_cycle, item.repeat_sub_value) }}</span>
225 |                 </div>
226 |                 <div class="upcoming-time">
227 |                   <strong>{{ formatShortDateTime(item.current_schedule_at) }}</strong>
228 |                   <span>{{ timeFromNow(item.current_schedule_at) }}</span>
229 |                 </div>
```
## `frontend/src/views/LoginView.vue`
删除预览后的隐私说明卡片
```text
// frontend/src/views/LoginView.vue:40-75
40 |         <div class="feature-grid">
41 |           <div v-for="feature in features" :key="feature.title" class="feature">
42 |             <span class="feature-icon">
43 |               <el-icon><component :is="feature.icon" /></el-icon>
44 |             </span>
45 |             <div>
46 |               <strong>{{ feature.title }}</strong>
47 |               <p>{{ feature.desc }}</p>
48 |             </div>
49 |           </div>
50 |         </div>
51 | 
52 |         <div class="privacy-panel">
53 |           <div class="privacy-panel-head">
54 |             <span class="privacy-live"><i></i> PRIVATE BY DEFAULT</span>
55 |             <span class="privacy-lock"><el-icon><Lock /></el-icon></span>
56 |           </div>
57 |           <strong>登录后才加载工作区</strong>
58 |           <p>
59 |             模块名称、账号信息、时间窗与执行计划仅对已认证会话可见。
60 |             本页不会请求或预渲染任何模块数据。
61 |           </p>
62 |           <div class="privacy-chips">
63 |             <span>JWT 鉴权</span>
64 |             <span>401 保护</span>
65 |             <span>加密存储</span>
66 |           </div>
67 |         </div>
68 | 
69 |         <div class="brand-foot">
70 |           <span><el-icon><Lock /></el-icon> 参数加密存储</span>
71 |           <span><el-icon><Monitor /></el-icon> 数据留存于你的服务器</span>
72 |         </div>
73 |       </div>
74 |     </section>
75 | 
```
```text
// frontend/src/views/LoginView.vue:489-570
489 | .privacy-panel {
490 |   width: min(100%, 470px);
491 |   margin-top: clamp(26px, 4.5vh, 44px);
492 |   padding: 15px 18px 13px;
493 |   background: rgba(255, 255, 255, 0.035);
494 |   border: 1px solid rgba(255, 255, 255, 0.07);
495 |   border-radius: 14px;
496 |   box-shadow: 0 24px 50px rgba(0, 0, 0, 0.15);
497 |   backdrop-filter: blur(10px);
498 | }
499 | 
500 | .privacy-panel-head {
501 |   display: flex;
502 |   align-items: center;
503 |   justify-content: space-between;
504 |   padding-bottom: 9px;
505 |   border-bottom: 1px solid rgba(255, 255, 255, 0.06);
506 | }
507 | 
508 | .privacy-live {
509 |   display: inline-flex;
510 |   align-items: center;
511 |   gap: 6px;
512 |   color: #9fe8d6;
513 |   font-family: var(--font-mono);
514 |   font-size: 8.5px;
515 |   font-weight: 700;
516 |   letter-spacing: 0.11em;
517 | }
518 | 
519 | .privacy-live i {
520 |   width: 5px;
521 |   height: 5px;
522 |   background: #34d399;
523 |   border-radius: 50%;
524 |   box-shadow: 0 0 8px rgba(52, 211, 153, 0.8);
525 | }
526 | 
527 | .privacy-lock {
528 |   display: grid;
529 |   width: 22px;
530 |   height: 22px;
531 |   place-items: center;
532 |   color: rgba(191, 203, 236, 0.45);
533 |   background: rgba(255, 255, 255, 0.04);
534 |   border-radius: 6px;
535 |   font-size: 10px;
536 | }
537 | 
538 | .privacy-panel strong {
539 |   display: block;
540 |   margin-top: 10px;
541 |   color: rgba(240, 244, 255, 0.84);
542 |   font-size: 11.5px;
543 |   font-weight: 600;
544 | }
545 | 
546 | .privacy-panel p {
547 |   margin-top: 4px;
548 |   color: rgba(184, 196, 229, 0.4);
549 |   font-size: 9.5px;
550 |   line-height: 1.7;
551 | }
552 | 
553 | .privacy-chips {
554 |   display: flex;
555 |   flex-wrap: wrap;
556 |   gap: 5px;
557 |   margin-top: 10px;
558 | }
559 | 
560 | .privacy-chips span {
561 |   padding: 2px 7px;
562 |   color: rgba(197, 209, 241, 0.45);
563 |   background: rgba(255, 255, 255, 0.035);
564 |   border: 1px solid rgba(255, 255, 255, 0.055);
565 |   border-radius: 5px;
566 |   font-family: var(--font-mono);
567 |   font-size: 7.5px;
568 |   letter-spacing: 0.04em;
569 | }
570 | 
```
## `frontend/src/views/GuideView.vue`
开发指南周期字段
```text
// frontend/src/views/GuideView.vue:118-128
118 |           <pre class="code-block"><code>{{ configExample }}</code></pre>
119 |           <div class="doc-callout">
120 |             <el-icon><Timer /></el-icon>
121 |             <code>default_start_time</code> / <code>default_end_time</code> 使用 24 小时制
122 |             <code>HH:mm</code>，<code>default_repeat_cycle</code> 指定每日 / 每周 /
123 |             每月15日 / 每月 / 每年；<code>default_repeat_sub_value</code> 设置子选项默认值：
124 |             周几（1-7）、每月几号（1-28）或月-日（如 2-29）。新建模块会以它们作为初始值，
125 |             用户可在网页端修改，平台会在执行日的时间窗内随机选择执行时间。
126 |           </div>
127 |         </section>
128 | 
```
```text
// frontend/src/views/GuideView.vue:365-375
365 |   { name: 'author', type: 'string', required: false, desc: '作者或维护者名称。' },
366 |   { name: 'version', type: 'string', required: false, desc: '模块版本号，默认 1.0.0。' },
367 |   { name: 'icon', type: 'string', required: false, desc: '模块图标 emoji，默认 🧩。' },
368 |   { name: 'default_start_time', type: 'string', required: true, desc: '默认开始时间 HH:mm，例如 08:00。' },
369 |   { name: 'default_end_time', type: 'string', required: true, desc: '默认结束时间 HH:mm，例如 10:00。' },
370 |   { name: 'default_repeat_cycle', type: 'string', required: false, desc: 'daily / weekly / monthly_15 / monthly / yearly。' },
371 |   { name: 'default_repeat_sub_value', type: 'string', required: false, desc: '每周填 1-7；每月填 1-28；每年填 M-D（如 2-29）。' },
372 |   { name: 'multi_account', type: 'boolean', required: false, desc: '为 true 时 params 会按账号重复渲染并串行执行。' },
373 |   { name: 'params', type: 'array', required: false, desc: '参数定义数组；多账号模式下每个账号各填写一组。' },
374 | ]
375 | 
```
```text
// frontend/src/views/GuideView.vue:410-420
410 |   "description": "自动完成某平台每日签到",
411 |   "author": "your-name",
412 |   "version": "1.0.0",
413 |   "icon": "🎯",
414 |   "default_start_time": "08:00",
415 |   "default_end_time": "10:00",
416 |   "default_repeat_cycle": "daily",
417 |   "default_repeat_sub_value": "",
418 |   "multi_account": true,
419 |   "params": [
420 |     {
```
## `scripts/check_frontend_privacy.mjs`
无头 Chrome 隐私检查（完整）
```text
// scripts/check_frontend_privacy.mjs:1-123
  1 | #!/usr/bin/env node
  2 | /**
  3 |  * Unauthenticated frontend privacy smoke test.
  4 |  *
  5 |  * Runs Google Chrome headlessly against the already-built SPA and verifies that
  6 |  * /login (and every protected route when opened without a token) contains no
  7 |  * module names, time windows, account counts, or schedule-preview markup.
  8 |  *
  9 |  * Requirements:
 10 |  *   - Node.js 18+ (no npm dependencies)
 11 |  *   - Google Chrome / Chromium
 12 |  *   - backend serving frontend/dist, or a Vite dev server
 13 |  *
 14 |  * Usage:
 15 |  *   BASE_URL=http://127.0.0.1:5000 \
 16 |  *   CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
 17 |  *   node scripts/check_frontend_privacy.mjs
 18 |  */
 19 | 
 20 | import { execFileSync, spawnSync } from 'node:child_process'
 21 | import { existsSync, mkdtempSync, rmSync } from 'node:fs'
 22 | import { tmpdir } from 'node:os'
 23 | import { join } from 'node:path'
 24 | 
 25 | const BASE_URL = (process.env.BASE_URL || 'http://127.0.0.1:5000').replace(/\/+$/, '')
 26 | const ROUTES = ['/', '/login', '/dashboard', '/modules', '/modules/1', '/logs', '/settings', '/guide']
 27 | const FORBIDDEN = [
 28 |   'schedule-preview',
 29 |   'preview-row',
 30 |   'LIVE SCHEDULE',
 31 |   '演示签到',
 32 |   '摸鱼能量签到',
 33 |   'demo_checkin',
 34 |   'moyu_energy',
 35 |   '02 modules',
 36 |   '已排程',
 37 |   '待启用',
 38 | ]
 39 | const TIME_WINDOW = /\b(?:[01]\d|2[0-3]):[0-5]\d\s*[–-]\s*(?:[01]\d|2[0-3]):[0-5]\d\b/
 40 | const ACCOUNT_COUNT = /\b\d{1,3}\s*个账号\b/
 41 | 
 42 | function findChrome() {
 43 |   const explicit = process.env.CHROME_BIN
 44 |   if (explicit) {
 45 |     if (!existsSync(explicit)) throw new Error(`CHROME_BIN 不存在：${explicit}`)
 46 |     return explicit
 47 |   }
 48 |   const candidates = [
 49 |     '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
 50 |     '/Applications/Chromium.app/Contents/MacOS/Chromium',
 51 |     '/usr/bin/google-chrome',
 52 |     '/usr/bin/google-chrome-stable',
 53 |     '/usr/bin/chromium',
 54 |     '/usr/bin/chromium-browser',
 55 |   ]
 56 |   for (const candidate of candidates) {
 57 |     if (existsSync(candidate)) return candidate
 58 |   }
 59 |   for (const name of ['google-chrome', 'chromium', 'chromium-browser']) {
 60 |     const result = spawnSync('which', [name], { encoding: 'utf8' })
 61 |     if (result.status === 0 && result.stdout.trim()) return result.stdout.trim()
 62 |   }
 63 |   throw new Error('未找到 Chrome/Chromium，请设置 CHROME_BIN 或安装 Google Chrome')
 64 | }
 65 | 
 66 | function dumpDom(chrome, profile, route) {
 67 |   return execFileSync(
 68 |     chrome,
 69 |     [
 70 |       '--headless=new',
 71 |       '--disable-gpu',
 72 |       '--disable-dev-shm-usage',
 73 |       '--no-sandbox',
 74 |       '--hide-scrollbars',
 75 |       '--virtual-time-budget=5000',
 76 |       `--user-data-dir=${profile}`,
 77 |       '--dump-dom',
 78 |       `${BASE_URL}${route}`,
 79 |     ],
 80 |     {
 81 |       encoding: 'utf8',
 82 |       timeout: 45_000,
 83 |       maxBuffer: 20 * 1024 * 1024,
 84 |       stdio: ['ignore', 'pipe', 'pipe'],
 85 |     },
 86 |   )
 87 | }
 88 | 
 89 | function checkDom(route, dom) {
 90 |   const problems = []
 91 |   for (const text of FORBIDDEN) {
 92 |     if (dom.includes(text)) problems.push(`包含禁止内容「${text}」`)
 93 |   }
 94 |   const timeWindow = dom.match(TIME_WINDOW)
 95 |   if (timeWindow) problems.push(`包含时间窗「${timeWindow[0]}」`)
 96 |   const accountCount = dom.match(ACCOUNT_COUNT)
 97 |   if (accountCount) problems.push(`包含账号数量「${accountCount[0]}」`)
 98 |   if (!dom.includes('登录控制台')) {
 99 |     problems.push('未跳转到登录页（缺少“登录控制台”）')
100 |   }
101 |   if (problems.length) {
102 |     throw new Error(`${route} 隐私检查失败：\n  - ${problems.join('\n  - ')}`)
103 |   }
104 | }
105 | 
106 | const chrome = findChrome()
107 | const profile = mkdtempSync(join(tmpdir(), 'checkin-privacy-chrome-'))
108 | console.log(`[privacy] Chrome: ${chrome}`)
109 | console.log(`[privacy] Base URL: ${BASE_URL}`)
110 | 
111 | try {
112 |   for (const route of ROUTES) {
113 |     const dom = dumpDom(chrome, profile, route)
114 |     checkDom(route, dom)
115 |     console.log(`  [PASS] ${route} 未认证 DOM 无模块敏感信息 / schedule-preview`)
116 |   }
117 |   console.log('[privacy] 所有未认证路由检查通过')
118 | } catch (error) {
119 |   console.error(`\n[FAIL] ${error.message}`)
120 |   process.exitCode = 1
121 | } finally {
122 |   rmSync(profile, { recursive: true, force: true })
123 | }
```
## `scripts/verify_api.py`
API 验证新增部分
```text
// scripts/verify_api.py:44-52
44 | from typing import Any
45 | 
46 | BASE_URL = os.environ.get("VERIFY_BASE_URL", "http://127.0.0.1:5000/api").rstrip("/")
47 | ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
48 | ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin123")
49 | REQUEST_TIMEOUT = float(os.environ.get("VERIFY_TIMEOUT", "30"))
50 | RUN_TIMEOUT = int(os.environ.get("VERIFY_RUN_TIMEOUT", "90"))
51 | 
52 | CYCLE_CASES = [
```
```text
// scripts/verify_api.py:145-172
145 |             assert_true(bool(health.get("scheduler_running")), "调度器未运行")
146 |             passed(f"健康检查正常，调度器运行中（第 {attempt} 次尝试）")
147 |             return health
148 |         except VerificationError as exc:
149 |             last_error = str(exc)
150 |             time.sleep(1)
151 |     raise VerificationError(f"等待健康检查超时：{last_error}")
152 | 
153 | 
154 | def check_public_surface() -> None:
155 |     for path in ["/modules", "/dashboard", "/push/config", "/logs"]:
156 |         data = expect_error("GET", path, None, 401)
157 |         assert_true(isinstance(data, dict), f"{path} 未返回 JSON 错误")
158 |     preview_payload = {
159 |         "start_time": "09:00",
160 |         "end_time": "11:00",
161 |         "repeat_cycle": "daily",
162 |         "repeat_sub_value": "",
163 |     }
164 |     preview_error = expect_error(
165 |         "POST", "/modules/schedule-preview", preview_payload, 401
166 |     )
167 |     assert_true(isinstance(preview_error, dict), "未认证预览接口未返回 JSON 错误")
168 |     preview_error = expect_error(
169 |         "POST", "/modules/schedule/preview", preview_payload, 401
170 |     )
171 |     assert_true(isinstance(preview_error, dict), "未认证预览接口未返回 JSON 错误")
172 |     passed(
```
```text
// scripts/verify_api.py:325-368
325 | 
326 |     api(
327 |         "PUT",
328 |         f"/modules/{module_id}",
329 |         {
330 |             "start_time": start,
331 |             "end_time": end,
332 |             "repeat_cycle": "daily",
333 |             "params": params,
334 |             "enabled": False,
335 |         },
336 |         token=token,
337 |     )
338 |     passed("单账号模块参数加密保存并回读成功")
339 | 
340 |     for cycle, sub_value in CYCLE_CASES:
341 |         updated = api(
342 |             "PUT",
343 |             f"/modules/{module_id}",
344 |             {
345 |                 "start_time": start,
346 |                 "end_time": end,
347 |                 "repeat_cycle": cycle,
348 |                 "repeat_sub_value": sub_value,
349 |                 "params": params,
350 |                 "enabled": False,
351 |             },
352 |             token=token,
353 |         )
354 |         assert_true(updated.get("repeat_cycle") == cycle, f"周期 {cycle} 保存后未回显")
355 |         assert_true(
356 |             updated.get("repeat_sub_value") == sub_value,
357 |             f"周期 {cycle} 子选项保存后未回显",
358 |         )
359 |     passed("每日 / 每周 / 每月15日 / 每月 / 每年 5 种周期及子选项均可保存")
360 | 
361 |     preview = api(
362 |         "POST",
363 |         "/modules/schedule/preview",
364 |         {
365 |             "start_time": "09:00",
366 |             "end_time": "11:00",
367 |             "repeat_cycle": "yearly",
368 |             "repeat_sub_value": "2-29",
```
```text
// scripts/verify_api.py:735-795
735 | 
736 | def _import_backend():
737 |     try:
738 |         from app.database import SessionLocal  # noqa: F401
739 |     except ImportError:
740 |         backend = Path.cwd() / "backend"
741 |         if backend.is_dir():
742 |             sys.path.insert(0, str(backend))
743 |     from app.database import SessionLocal
744 |     from app.migrations import migrate_schema
745 |     from app.models import Module
746 | 
747 |     return SessionLocal, migrate_schema, Module
748 | 
749 | 
750 | async def _verify_legacy_cycle_migration() -> None:
751 |     """Insert a legacy row, run the real migration, and verify the downgrade."""
752 |     SessionLocal, migrate_schema, Module = _import_backend()
753 |     marker = f"verify_legacy_{int(time.time())}"
754 |     async with SessionLocal() as db:
755 |         row = Module(
756 |             key=marker,
757 |             name="Legacy migration verification",
758 |             description="temporary row",
759 |             author="verify",
760 |             version="0.0.0",
761 |             icon="🧪",
762 |             default_cron="0 8 * * *",
763 |             cron="0 8 * * *",
764 |             default_start_time="08:00",
765 |             default_end_time="10:00",
766 |             default_repeat_cycle="quarterly",
767 |             default_repeat_sub_value="",
768 |             start_time="08:00",
769 |             end_time="10:00",
770 |             repeat_cycle="half_month",
771 |             repeat_sub_value="",
772 |             enabled=False,
773 |             param_schema=[],
774 |         )
775 |         db.add(row)
776 |         await db.commit()
777 |         row_id = row.id
778 |     try:
779 |         await migrate_schema()
780 |         async with SessionLocal() as db:
781 |             row = await db.get(Module, row_id)
782 |             assert_true(row is not None, "旧周期迁移测试行丢失")
783 |             assert_true(
784 |                 row.repeat_cycle == "monthly" and row.repeat_sub_value == "1",
785 |                 f"旧周期 repeat_cycle 迁移错误：{row.repeat_cycle}/{row.repeat_sub_value}",
786 |             )
787 |             assert_true(
788 |                 row.default_repeat_cycle == "monthly"
789 |                 and row.default_repeat_sub_value == "1",
790 |                 "旧周期 default_repeat_cycle 迁移错误",
791 |             )
792 |     finally:
793 |         async with SessionLocal() as db:
794 |             row = await db.get(Module, row_id)
795 |             if row is not None:
```
## `verify_docker.sh`

Docker 验证摘要更新

```text
// verify_docker.sh:280-289
280 | else
281 |   log_info "验证完成后自动清理临时环境"
282 | fi
283 | 
284 | printf '\n%s%s✓ 部署验证通过%s\n' "$C_BOLD" "$C_GREEN" "$C_RESET"
285 | printf '  镜像构建、容器启动、健康检查、登录、未认证隔离、用户名/密码、\n'
286 | printf '  五种周期与条件子选项、旧周期迁移、随机时间、多账号串行、脱敏日志、\n'
287 | printf '  部分失败、推送配置、启用/禁用调度、手动执行、历史日志、目录扫描与仪表盘均已验证。\n\n'
288 | 
289 | exit 0
```

## `templates/advanced_checkin/config.json`

进阶模板默认子选项配置

```text
// templates/advanced_checkin/config.json:1-16
 1 | {
 2 |   "name": "Acme 签到（进阶多账号模板）",
 3 |   "description": "生产级多账号模块骨架：平台负责账号串行、随机时间与统一推送；单个 run(params) 专注 Cookie 过期检测、自动重新登录、指数退避重试和超时控制。默认模拟模式，无网络也能安全试跑。",
 4 |   "author": "Daily Check-in Platform",
 5 |   "version": "2.0.0",
 6 |   "icon": "🛰️",
 7 |   "default_start_time": "09:00",
 8 |   "default_end_time": "11:00",
 9 |   "default_repeat_cycle": "daily",
10 |   "default_repeat_sub_value": "",
11 |   "multi_account": true,
12 |   "params": [
13 |     {
14 |       "key": "api_base",
15 |       "label": "API 根地址",
16 |       "type": "text",
```


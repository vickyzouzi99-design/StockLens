# StockLens · 内测版

将普通投资者的自然语言偏好转成可理解、可修改、可核验的选股条件，再用真实数据筛选。不是自动交易、股票推荐或收益预测工具。

[源码仓库](https://github.com/vickyzouzi99-design/StockLens) · [AI 使用与验证记录](docs/AI使用与验证记录.md) · [测试说明](docs/测试说明.md) · [服务器部署](docs/服务器部署.md)

生产Docker部署请使用[DEPLOYMENT.md](DEPLOYMENT.md)：Caddy + FastAPI + 独立采集worker，适配2核2GB服务器；前后端默认DeepSeek，失败不自动回退OpenAI。执行筛选后默认显示符合条件列表，仍可切换其他状态。

## 产品选择

- 三步共享同一份状态：描述需求 → 确认条件 → 查看结果。模糊目标先澄清，缺失阈值不凭空补齐，AI 建议阈值须确认。
- 支持 PE TTM、PB MRQ 上限，归母净利润同比、营业收入同比、报告期加权平均 ROE 下限，以及近20日日收益率波动率上限。
- 数值条件全部同时满足。行业可以多选，所选行业满足任一项，再与数值条件组合。
- 明确区分符合、未符合和数据不足；逐项展示实际值、规则、数据时间、报告期及计算依据。技术编号只用于问题反馈。
- 调整条件默认使用同一快照，比较新增、移除和仍符合的股票；主动切换最新数据时建立新的比较起点。
- “我的策略”独立于三步流程，保存完整条件及停用指标阈值。恢复、修改、保存、重新筛选均不请求 AI。账号策略隔离持久化；旧浏览器策略可明确选择导入。

保留金融含义与用户控制权，比自动堆叠指标更重要。低估值、低波动或高增长都不等于低风险或未来收益。

## 从源码启动

需要 Python 3.10+、Node.js 26。以下为 Windows PowerShell，在仓库根目录执行：

    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
    if (!(Test-Path .env)) { Copy-Item .env.example .env }
    npm --prefix frontend ci

填写 .env 中的密钥后，首次采集并创建一个一次性邀请码：

    .\.venv\Scripts\python.exe backend\collect_data.py 300
    .\.venv\Scripts\python.exe backend\accounts.py --daily-limit 10 --days 7

邀请码只发给受邀用户，不提交或公开。分别在两个终端启动：

    .\.venv\Scripts\python.exe -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8000 --reload --reload-dir backend

    npm --prefix frontend run dev

打开 http://localhost:5173，通过邀请码注册，以后使用用户名和密码登录。Vite 将同源 /api 代理至本地后端。没有金融快照时，解析和筛选会提示数据不可用。需允许后端访问外部 API；Windows 10013 是网络权限错误，不应通过反复更换密钥解决。

## 环境变量

| 变量 | 用途 / 默认值 |
| --- | --- |
| OPENAI_API_KEY | OpenAI 服务端密钥；两家 AI 至少配置一家 |
| LLM_MODEL | OpenAI 模型，默认 gpt-4o-mini |
| DEEPSEEK_API_KEY / DEEPSEEK_MODEL | DeepSeek 密钥 / 默认 deepseek-flash |
| FUYAO_API_KEY | 扶摇金融数据采集密钥 |
| STOCKLENS_DATA_DIR | 金融快照目录，默认 data |
| STOCKLENS_ACCOUNT_DB | 账号与策略 SQLite 文件，默认 data/accounts.sqlite3 |
| STOCKLENS_GLOBAL_DAILY_LIMIT | 全站每日 AI 调用上限，默认200 |
| STOCKLENS_ACCESS_MODE | 默认 required；local 仅用于本机开发，生产不能绕过登录 |
| STOCKLENS_ENV | 线上设为 production，使用生产环境变量与 Secure 会话 Cookie |
| STOCKLENS_CORS_ORIGINS | 明确允许的前端来源；生产建议同源 |
| STOCKLENS_MIN_COVERAGE | 快照最低字段覆盖率，默认0.8 |
| STOCKLENS_UNIVERSE_LIMIT | 当前默认300，不扩大到其他股票池 |
| STOCKLENS_REPORT | 可选指定财报期，如2026-3；默认按可用报告期选择 |
| STOCKLENS_SNAPSHOT | 可选指定数据快照路径；通常无需设置 |
| VITE_API_BASE_URL | 前端构建时指定 API 地址；默认同源 |
| STOCKLENS_API_TARGET | 本地 Vite 代理目标，默认 http://127.0.0.1:8000 |

本地 API 和邀请码命令读取根目录 .env；生产环境优先使用服务环境变量。密钥、数据库、快照、依赖、构建产物、测试凭证与截图均不入库。

## AI、数据与费用

AI 只理解需求、提出澄清和可选补充指标，不能生成股票数据或决定入选。可选补充带理由和局限，用户主动加入并设置阈值后才执行；沿用同次解析，无额外模型请求。OpenAI / DeepSeek 由用户选择，不自动切换。

数据来自[扶摇金融 API](https://fuyao.aicubes.cn/docs)：沪深300成分股、同花顺行业、估值、财务指标与前复权日K线。波动率由21个完整交易日收盘价计算20个日收益率的样本标准差，未年化。ROE 不自行年化；缺失、非有限值及不齐的价格窗口不以0补齐。

快照通过数量、唯一性和覆盖率校验后原子发布，失败保留上次数据。可运行独立更新进程：

    .\.venv\Scripts\python.exe backend\refresh_worker.py

计划为交易日 GMT+8 的09:30、11:30、13:00、15:00；需常在线运行。四次采集不代表上游四次更新，也不是实时行情。实际采集时间、行情时间、完整交易日和财报期分别保留。

邀请码决定账号每日额度；两个提供商共用额度，调用前原子预占，失败或超时也计一次，避免重试绕过费用上限。每次模型输出最多2048 tokens。次数限制不是精确货币账单。

## 验证

    .\.venv\Scripts\python.exe -m unittest discover -s backend -p "test_*.py" -v
    npm --prefix frontend test
    npm --prefix frontend run lint
    npm --prefix frontend run build

离线回归不调用 AI；真实浏览器和收费语义验收的准备、执行范围见[测试说明](docs/测试说明.md)。GitHub Actions 运行离线检查，不自动产生 AI 用量。

## 已知边界与未做事项

- 当前固定沪深300；规则采用确认页的≤/≥及正 PE/PB 约束，不支持严格不等式、区间、跨指标 OR、NOT、嵌套策略或其他股票池。
- 财务数据有披露滞后，选定报告期可能回退；同一只股票不混合不同报告期补齐指标。行业关系可能滞后，查询时间不代表生效时间。
- 模型仍可能误解或漏提取。已有冲突与遗漏检查不能证明任意自然语言都被正确理解，必须人工核对。
- 尚未实际部署线上，未提供自动交易、回测、运行历史、定时选股提醒、网页管理后台和自助找回密码。账号恢复与备份需在运营前安排。
- 浏览器验收覆盖主要场景和指定尺寸，不是所有措辞、设备及 Linux 生产环境的穷举。当前未制作演示视频。

代码职责：backend 为 API / 数据采集 / 规则 / 账号；frontend 为 React 工作台与测试；deploy 为服务器模板；docs 仅保留最终交付资料。旧阶段文档可通过 Git 历史查看。

仅用于数据筛选与投资研究，不构成投资建议、确定性预测或收益承诺。

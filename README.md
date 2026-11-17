# StockLens

最新界面与研究辅助改进：[账号导航、行业多选与可读溯源验收](docs/账号导航与研究工作台改进.md)。AI 可在同次解析中提供可选补充指标及理由，用户加入并设置阈值后才参与筛选。

最新更新：[最终调整验收](docs/最终调整验收.md) · [邀请码与线上账号](docs/邀请码与线上账号.md)。默认邀请码注册后登录，账号策略持久化；开发端通过 Vite 同源代理连接 API。旧版浏览器策略可在登录后明确选择导入，原数据保留。

交付入口：[最终交付说明](docs/最终交付说明.md) · [测试报告](docs/测试报告.md) · [AI 使用与人工纠错记录](docs/AI使用与人工纠错记录.md)。

帮助普通投资者将模糊的投资偏好转化为可理解、可修改、可核验的股票筛选条件，再用真实金融数据验证。

产品定位与交互取舍见 [产品定位与交互原则](docs/产品定位与交互原则.md)。
前端紧凑工作台布局与本轮取舍见 [前端工作台布局调整](docs/前端工作台布局调整.md)。
本轮完成项与验证边界见 [2026-11-17续开发验证](docs/2026-11-17续开发验证.md)。
新增条件、行业与本地策略库见 [条件扩展与策略保存](docs/条件扩展与策略保存.md)。

## 核心目录

```text
StockLens/
├─ backend/                  # 唯一后端目录
│  ├─ app.py                 # FastAPI 接口、参数校验、快照加载
│  ├─ intent_parser.py       # 自然语言解析
│  ├─ screen_engine.py       # 确定性筛选与逐项证据
│  ├─ collect_data.py        # 金融数据采集、清洗、快照发布
│  ├─ refresh_worker.py      # 交易日四时点更新
│  ├─ requirements.txt       # 后端依赖
│  ├─ test_data_refresh.py   # 数据质量与调度回归测试
│  ├─ test_api_dynamic.py    # 路由处理函数测试
│  ├─ test_dynamic_screen.py # 筛选及解析结果标准化测试
│  └─ test_intent_guidance.py # 模糊目标澄清及补充解析回归测试
├─ frontend/                 # 唯一前端目录，React + TypeScript + Vite
│  ├─ src/                  # 页面、交互与样式
│  ├─ tests/                # 前端数值校验回归测试
│  ├─ public/               # 静态资源
│  └─ package.json          # 前端命令及依赖
├─ data/                     # 本地数据快照，不提交
├─ docs/                     # 交接文档、变更和验收记录
├─ deploy/                   # 服务器部署模板
├─ .env                      # 本地配置与密钥，不提交
└─ .gitignore
```

`.venv/`、`frontend/node_modules/` 和 `frontend/dist/` 分别是本地 Python 环境、前端依赖和构建产物，不是额外的项目源码。
升级前的 `backup_before_v04_20261116_173536/` 已在确认版本后清理；开发和启动均使用以上核心目录。

## 本地运行

以下命令使用现有本地环境，分别在两个 PowerShell 终端运行。

后端（项目根目录）：

```powershell
cd C:\StockLens
.\.venv\Scripts\python.exe -m uvicorn app:app --app-dir backend --reload
```

前端：

```powershell
cd C:\StockLens\frontend
npm.cmd run dev
```

访问 `http://localhost:5173/`，后端接口文档为 `http://127.0.0.1:8000/docs`。

首次使用请在与后端相同的环境执行 `.\.venv\Scripts\python.exe backend\accounts.py --daily-limit 10 --days 7` 生成一次性邀请码。仅限本机离线开发可显式设置 `STOCKLENS_ACCESS_MODE=local`；生产始终要求登录。邀请码、用户数据库和密钥禁止入库。

后端需要访问外部 AI API。请从正常的本地 PowerShell 启动；由 Codex 启动时，应使用获得网络授权的运行环境。受限沙箱中的后端可能仍能返回健康检查和本地筛选结果，但调用 OpenAI / DeepSeek 会出现 Windows 10013 网络权限错误。此时应重启到可联网环境，无需修改密钥或关闭防火墙。验证应通过运行中后端的 `/api/interpret` 完成，单独脚本成功不能证明网页所连接的后端具备网络权限。

现有 `.env` 使用 `OPENAI_API_KEY`、`LLM_MODEL`；可通过 `STOCKLENS_SNAPSHOT` 指定快照。
输入框右上角支持 OpenAI / DeepSeek 下拉选择。启用 DeepSeek 需在后端配置 `DEEPSEEK_API_KEY`，默认 `DEEPSEEK_MODEL=deepseek-flash`；说明与验证边界见 [AI服务选择与DeepSeek接入](docs/AI服务选择与DeepSeek接入.md)。
前端可通过 `VITE_API_BASE_URL` 指定后端；开发环境默认 `http://127.0.0.1:8000`，生产构建默认同域 `/api`。
采集脚本从进程环境或根目录 `.env` 读取 `FUYAO_API_KEY`，默认采集沪深300全部成分股。
自动更新与服务器部署见 [数据扩容与自动更新](docs/数据扩容与自动更新.md)。worker 已实现，尚未在常在线服务器启用。
完整应用部署模板（API、前端、HTTPS、独立 worker）见 [服务器部署](docs/服务器部署.md)。

## 验证

```powershell
cd C:\StockLens
.\.venv\Scripts\python.exe -m unittest discover -s backend -p "test_*.py" -v
cd frontend
npm.cmd test
npm.cmd run build
```

前端测试使用现有 Node.js v26 的 TypeScript 支持，无需新增测试依赖。
现有 Python 测试不调用外部 API，不覆盖真实 AI 解析或浏览器交互。
可选执行 `.\.venv\Scripts\python.exe -X utf8 backend\verify_persona_live.py --live` 验证6个真实解析场景；该命令调用现有 OpenAI 配置并产生 API 用量，不属于离线测试。
界面验收见 [目录与条件交互调整](docs/目录与条件交互调整.md)。
模糊自然语言的引导流程见 [自然语言澄清与参考条件](docs/自然语言澄清与参考条件.md)。

## 当前边界

当前支持正市盈率及正市净率上限、归母净利润同比增长率下限、报告期加权平均 ROE 下限、营业收入同比增长率下限、20 日波动率上限及单一同花顺行业；多个条件同时满足（AND）。
筛选使用本地快照，当前已发布沪深300全部300只成分股的数据。AI 只解析需求，筛选结论由规则引擎生成。
四次采集不意味着上游数据四次变化；实际数据时间、财报期和完整日K线截止日分别保留。

历史背景见 [项目交接文档](docs/StockLens_Codex_项目交接文档.md)。该文档的后续规划不等于已实现功能。

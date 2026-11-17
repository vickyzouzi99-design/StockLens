# AI 服务选择与 DeepSeek 接入

输入卡片右上角原 `Powered by OpenAI` 已替换为“AI 服务”下拉框，提供 OpenAI / DeepSeek。默认保留 OpenAI。

## 使用与配置

在项目根目录 `.env` 中追加以下两项，填入自己的 DeepSeek 服务密钥，然后重启后端。不要把密钥放进前端文件、`VITE_*` 变量或聊天消息。

```dotenv
DEEPSEEK_API_KEY=在本机填入你的密钥
DEEPSEEK_MODEL=deepseek-flash
```

服务器部署时在 `/etc/stocklens/api.env` 配置并重启 `stocklens-api`；模板 `deploy/api.env.example` 已增加这两项。
OpenAI 继续使用已有 `OPENAI_API_KEY`（兼容 `LLM_API_KEY`）、`LLM_MODEL` 和官方 `LLM_BASE_URL` 配置。
两家密钥独立；选择 DeepSeek 不需要配置 OpenAI 密钥，反之亦然。浏览器只发送服务标识，不持有密钥。

按当前[官方接口文档](https://api-docs.deepseek.com/)，DeepSeek 默认模型为 `deepseek-flash`，地址固定为 `https://api.deepseek.com/chat/completions`。
使用[JSON 输出](https://api-docs.deepseek.com/guides/json_mode/)，沿用同一意图提示词和标准化校验；关闭[思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)，输出上限2048 tokens。模型可通过后端环境变量调整。

## 行为约定

- `POST /api/interpret` 新增可选 `provider`，仅允许 `openai` / `deepseek`；省略时仍使用 OpenAI，旧调用兼容。
- 返回解析结果中包含 `provider` 和 `model`，页面“查看需求与规则说明”中展示本次解析来源。
- 切换服务保留输入、原条件与旧结果；重新解析前禁止执行旧条件。请求期间禁用选择框，避免响应来源与显示选择不一致。
- “补充说明”请求同样发送当前所选服务。明确指标、模糊需求、未支持条件的处理规则不因服务切换而改变。
- 未配置、网络错误、HTTP 错误、空白/无效/截断 JSON 都明确报错。不自动切换服务，不把失败伪装成解析成功。
- 筛选、股票数据、历史快照、四时点数据更新均由现有确定性逻辑负责；AI 仅用于解析需求。

浏览器访问的是 StockLens 后端，由后端连接所选服务。部署时应分别验证服务器到 OpenAI / DeepSeek 的实际连通性和账户可用性；下拉框本身不能保证任何地区的连接可用。

## 验证记录

- 48 项后端测试通过：新增8项覆盖供应商分流、密钥隔离、旧客户端兼容、非法服务拒绝、缺少配置、错误脱敏、无效和截断 JSON。
- 11 项前端测试、TypeScript + Vite 构建、ESLint 均通过。
- 当前浏览器刷新后的可访问性树已显示“AI 服务 / OpenAI”组合框；坐标输入及截图仍受电脑控制接口限制，未完成真实展开/切换的浏览器验收。
- 本地尚未配置 `DEEPSEEK_API_KEY`，没有声称 DeepSeek 真实联网解析已通过。接口协议通过模拟响应验证，配置密钥后可运行真实场景验收：

```powershell
.\.venv\Scripts\python.exe -X utf8 backend\verify_persona_live.py --live --provider deepseek
```

该命令会调用 DeepSeek 并产生 API 用量。OpenAI 可使用 `--provider openai`，或省略该参数。

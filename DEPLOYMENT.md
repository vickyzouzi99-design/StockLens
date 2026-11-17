# StockLens Docker 生产部署

目标：Ubuntu 24.04 / Docker Compose，2核2GB的单机演示环境。当前阶段仅准备代码和配置，没有连接云服务器。容器构建、Linux 文件权限、证书签发和实际常驻调度须在服务器执行后才能验收。

## 实际结构与选择

| 部分 | 实际入口 / 行为 |
| --- | --- |
| React + Vite | frontend；Node 26，npm ci，npm run build，产物 dist |
| FastAPI | backend/app.py；python -m uvicorn app:app --app-dir backend |
| Provider | 默认 DeepSeek；OpenAI 仅用户主动选择后调用，缺失密钥/失败均不自动回退 |
| 金融数据 | backend/collect_data.py 300；扶摇API → 清洗/校验 → 原子发布JSON快照 |
| 更新进程 | backend/refresh_worker.py；交易日 GMT+8 09:30 / 11:30 / 13:00 / 15:00；系统时区不影响排程 |
| 策略 | 账号隔离的SQLite；保存完整条件、停用值与来源；恢复与筛选不消耗AI调用 |

三个常驻容器：Caddy静态前端、单进程API、单个更新worker。前端没有Node运行服务；不引入Redis、PostgreSQL或额外任务系统。API/worker复用同一Python镜像。

只发布80/443，/api原样代理到api:8000。API信任本容器网络中的代理头；不要另行发布8000端口，也不要将不可信服务接入此网络。Caddy保留Host并重写转发来源和协议，生产Secure会话Cookie经HTTPS使用。同源配置无需CORS白名单；生产不默认允许localhost跨域。

## 环境变量与域名

只修改新建的.env.production，不复制覆盖已有.env。Compose通过插值只将明确列出的变量注入相应服务，不把整个env文件挂入容器。

| 名称 | 配置 |
| --- | --- |
| STOCKLENS_DOMAIN | 必填：真实域名，如stocks.example.com，不带协议、端口或路径；DNS A记录指向服务器；有AAAA记录时也必须可达 |
| DEEPSEEK_API_KEY | 必填，后端API使用 |
| DEEPSEEK_MODEL | 默认deepseek-flash，按自己的服务账号配置可用模型 |
| FUYAO_API_KEY | 必填，仅采集worker使用 |
| OPENAI_API_KEY / LLM_MODEL | 可选；不用OpenAI则保持密钥空白，默认模型gpt-4o-mini |
| STOCKLENS_GLOBAL_DAILY_LIMIT | 全站每日AI调用上限，默认200；账号每日额度由邀请码指定 |
| STOCKLENS_MIN_COVERAGE | 发布快照的最低字段覆盖率，默认0.8 |
| STOCKLENS_CORS_ORIGINS | 同源部署留空；需要跨域时显式填写完整来源，以逗号分隔 |
| STOCKLENS_IMAGE_TAG | 默认local；建议按下文导出Git提交号作为镜像标签 |

Compose固定production、登录必需、300只股票池及Linux持久路径。根目录示例里的STOCKLENS_DATA_DIR、STOCKLENS_ACCOUNT_DB为本地开发值，不会覆盖容器内路径。不支持将Windows路径传入容器。需要固定财报期等特殊配置时，先按实际业务审查后在worker的environment显式增加，不能将整份开发env直接注入。

API密钥只存在于后端服务环境，前端没有VITE密钥、构建参数或env文件。Docker白名单构建上下文排除.env、数据、账号库和本机依赖。Docker管理员仍可查看容器环境，因此限制服务器SSH和Docker权限。不要公开完整docker compose config或docker inspect输出。

Caddy自动申请和续期HTTPS证书，/data与/config持久化。公网需要域名DNS正确，腾讯云防火墙及系统防火墙放通TCP 80/443，且端口未被旧Nginx/Caddy占用。生产登录依赖HTTPS，不以关闭Secure Cookie绕过证书问题。未配置域名时，先完成DNS准备，再对外演示。

## 首次部署

先在开发机审阅并上传本次修改；尚未上传的代码不会出现在服务器git clone结果中：

```bash
git diff --check
git status --short
git add .dockerignore .gitattributes compose.yaml .env.example DEPLOYMENT.md README.md backend frontend deploy docs
git commit -m "Prepare Docker production deployment and refine screening UI"
git push origin main
```

确认真实env、数据库和快照未被跟踪后再push。以下命令供你在Ubuntu服务器执行，本阶段没有代为执行。仓库不要放在Web可直接下载的目录下。

```bash
git clone https://github.com/vickyzouzi99-design/StockLens.git
cd StockLens
test -f .env.production || cp .env.example .env.production
chmod 600 .env.production
nano .env.production
export STOCKLENS_IMAGE_TAG="$(git rev-parse --short=12 HEAD)"

# 只校验，不打印包含密钥的完整配置
docker compose --env-file .env.production config --quiet
# 2GB机器顺序构建；Node构建堆限制512MB
COMPOSE_PARALLEL_LIMIT=1 docker compose --env-file .env.production build --pull api frontend
docker compose --env-file .env.production run --rm --no-deps frontend caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

# 首次完整采集；有密钥且可联网才能执行，不复制开发账号库
docker compose --env-file .env.production run --rm --no-deps worker python backend/collect_data.py 300
# 此命令仅生成一次性邀请码，请私下保存交给面试官
docker compose --env-file .env.production run --rm --no-deps api python backend/accounts.py --daily-limit 10 --days 7

docker compose --env-file .env.production up -d --no-build
docker compose --env-file .env.production ps
curl --fail https://你的域名/api/health
```

首次采集未成功时不要写假快照。API健康接口仅说明进程在线，没有金融快照时数据接口应返回503。新部署默认是独立账号库；原电脑账号和本地策略不会自动上传，可通过当前产品已有策略导入流程或另行安排受控迁移。

如果2GB机器构建期间出现OOM，先检查docker stats与free -h；暂停worker后重试，或在有Docker的开发/CI环境构建镜像再传输。运行时内存上限：API512MB、worker512MB、Caddy192MB，总计约1.2GB；这是配置上限，尚不是实测峰值或并发容量承诺。单worker、API并发上限8、日志每服务最多3×10MB。不在此机器上同时运行旧systemd采集任务或第二套调度。

## 验收、日志与持久化

```bash
docker compose --env-file .env.production logs --tail=100 api worker frontend
docker compose --env-file .env.production logs -f --tail=50 worker
docker stats --no-stream
# 检查实际JSON中的采集时间和调度状态，不暴露金融原始响应
docker compose --env-file .env.production exec -T worker python -c 'from pathlib import Path; print(Path("/app/data/scheduler_status.json").read_text())'
```

- 公网HTTPS打开 → 邀请注册/登录 → 默认DeepSeek解析 → 确认阈值/多行业 → 筛选默认显示符合列表 → 查看逐项依据。
- 保存策略 → 刷新/退出再登录 → 恢复停用阈值和行业 → 改阈值重新筛选；恢复不调用AI。
- 重启api后策略仍在；重启worker后快照仍在；实际观察四个交易时点，失败保留旧快照。
- 单独检查DeepSeek失败不会触发OpenAI；需要真实调用时少量手动执行并记录额度。健康检查和镜像构建不会请求AI。
- Caddy健康检查只验证容器内静态服务，API健康检查只验证进程；两者都不代表公网证书、上游API或数据新鲜度已通过。

Compose项目名固定stocklens，四个命名卷分别保存金融快照、账号/策略、证书和Caddy配置。API对金融卷只读，worker无账号库或AI密钥。不要运行docker compose down -v或docker volume prune；普通down/重建容器不删除这些数据。历史快照暂无自动清理，定期查看磁盘；删除旧快照会影响旧版比较。

## 备份与更新

更新前记录旧Git提交号与镜像标签。以下备份会短暂停止API和worker，保证SQLite与文件一致；前端可能短暂显示接口不可用。

```bash
mkdir -p ../stocklens-backups
chmod 700 ../stocklens-backups
docker compose --env-file .env.production stop api worker
docker compose --env-file .env.production run --rm --no-deps -T api python -c 'import sys,tarfile; t=tarfile.open(fileobj=sys.stdout.buffer,mode="w|gz"); t.add("/app/data",arcname="data"); t.add("/app/accounts",arcname="accounts"); t.close()' > "../stocklens-backups/state-$(date -u +%Y%m%dT%H%M%SZ).tgz"
chmod 600 ../stocklens-backups/*.tgz
docker compose --env-file .env.production start api worker

# 使用已审阅的新提交；env文件和持久卷保留
git pull --ff-only
export STOCKLENS_IMAGE_TAG="$(git rev-parse --short=12 HEAD)"
docker compose --env-file .env.production config --quiet
# 2GB服务器更新时暂停采集，API仍可读取上次快照
docker compose --env-file .env.production stop worker
COMPOSE_PARALLEL_LIMIT=1 docker compose --env-file .env.production build --pull api frontend
docker compose --env-file .env.production up -d --no-build
docker compose --env-file .env.production ps
```

确认备份命令退出成功且归档可读后再继续。备份包含用户信息与策略，禁止放进公开仓库或Web目录。另行加密备份.env.production并限制访问；Caddy证书卷也应按需备份。不要在新版本验收前清理旧镜像。

更新构建失败时，不启动缺失的新镜像；用docker compose --env-file .env.production start worker恢复原采集容器，再排查构建错误。

## 回滚

```bash
git log --oneline -6
# 替换成上次成功的真实提交号；不会覆盖被忽略的.env.production
git switch --detach <上次成功的提交号>
export STOCKLENS_IMAGE_TAG="$(git rev-parse --short=12 HEAD)"
docker compose --env-file .env.production up -d --no-build --force-recreate
docker compose --env-file .env.production ps
```

前提是旧提交已包含Docker配置，且相应镜像仍保留。否则先按该旧版本重新构建，不能直接使用本次Docker化之前的提交执行Compose。回滚代码不会回滚账号库/快照，也不应覆盖用户之后新增的策略。本次未更改数据库结构；未来若存在不兼容迁移，应先验证备份恢复方案并安排维护窗口。

回滚后再次更新前，先git switch main回到主分支，再按更新步骤执行。

## 本地验证边界

真实执行结果见[测试说明](docs/测试说明.md)。Windows开发机未安装Docker引擎，不能声明镜像build、容器启动、Linux卷权限、HTTPS证书或服务器持久化已通过。配置校验与Windows上的应用回归只覆盖各自范围。公开演示前仍需执行上述服务器验收。

配置依据：[Docker Compose服务定义](https://docs.docker.com/reference/compose-file/services/)、[Caddy自动HTTPS](https://caddyserver.com/docs/automatic-https)、[Caddy容器持久化](https://caddyserver.com/docs/running)。

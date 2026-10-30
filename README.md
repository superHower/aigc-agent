# AI 生图

v4 正在按阶段实施：已加入数据库迁移、备份恢复、PostgreSQL、手机号注册/找回密码、会话认证、用户资源隔离及积分生图结算。启动业务前须初始化超管，无默认密码。操作方法与当前限制见 [v4 实施记录](文档/v4实施记录.md)。短信默认禁用，须配置后才能注册；普通用户可使用积分生图，会员与充值尚未开放。

普通用户每张最终图片消耗 1 积分，多比例分别计数；提交时冻结，成功扣费，最终失败或取消释放。新注册账号赠送 3 积分，7 天有效；升级前已有账号不补发体验积分。工作台展示所需积分，账户「我的积分」可查看余额、来源及流水。自动重试不额外扣费，手动重试重新冻结；管理员旧版入口保留内部使用。

## 首页统计

- 首页（`/`）展示任务数、成功出图数、出图成功率、失败图片数及与上一周期的对比，支持日、周、月和历史日期筛选，每 15 秒自动刷新。
- 图表包括生成趋势堆叠柱状图与任务折线图、出图结果环形图、渠道出图横向排行；另有任务状态、基础预估费用和最近任务入口。工作台移至 `/workspace`。
- 数据覆盖所选周期的全部任务，按任务创建时间及浏览器时区归属，展示当前结果；最终图片排除 OCR 和 Logo 中间步骤。成功率为成功数除以成功与失败之和。渠道排行按重试后的最终执行渠道归属；历史未记录渠道的任务标为“未分配渠道”。
- 周为周一至周日，月为自然月；上一周期为紧邻的等长时间段。费用为计划步骤数 × ¥0.05，含 OCR、不含重试，为预估而非真实账单。

## 渠道管理

- 顶部“渠道管理”（`/channels`）可增删改查渠道名称、模型、API 地址、API Key、备注，并单独设置并发数（默认 3，范围 1–20）与请求超时（默认 30 秒，范围 1–300 秒）。修改密钥时留空保留原值，接口不会返回已有密钥。
- 批量任务使用所有已启用且无异常的渠道，按轮询平均分配最终图片；10 张图片、4 个渠道分别分配 3、3、2、2。OCR 前置步骤单独轮询，保持原有依赖顺序。
- 同一渠道在多个批量任务间共享并发额度。渠道余额、鉴权、网络、超时或无效响应异常时立即停止该渠道的排队及在途请求；其他渠道继续执行。每轮全部步骤结束后，失败步骤自动分配到仍可用的渠道重试，最多追加 3 轮（含首次最多执行 4 次）。成功步骤不重复生成，取消任务或无可用渠道时停止自动重试。任务页面显示重试轮数；轮数存储在数据库中，重启后保留。仍失败时可修复渠道并手动重试。
- 渠道配置与异常状态存储在 SQLite 中。首次启动将已有环境变量中的接口配置导入“默认渠道”（并发 3）；也可以不设置环境变量，启动后直接在页面添加渠道。修改、停用或删除配置从后续任务生效，正在执行的任务保留提交时配置。
- 批量并发上限是可用渠道并发数之和；原有 `MAX_CONCURRENCY` 用于单图/高级编辑接口。并发控制适用于单个后端进程。请求超时会取消本地等待，上游已接受的请求仍可能产生费用。

## 提示词模板

- 顶部“提示词管理”（`/prompts`）支持新建、查看、编辑、删除模板，按名称或内容搜索，以及分类筛选。
- “管理分类”支持新增、重命名和删除分类；删除分类会将模板移至“未分类”，保留模板内容。
- 工作台“多图”和“参考图组合”通过 Tab 切换，两种模式都支持多行提示词输入和模板选择。模板可按分类筛选、搜索、展开预览；点击“选择”直接填入并关闭弹窗，覆盖已有内容，填入后仍可编辑。
- 当前输入可通过“保存为模板”保存。模板和分类存储在服务端 SQLite 数据库中，刷新页面或重启服务后仍可使用。

支持多图通用提示词、参考图组合、多比例独立生成、可选 OCR 文字编辑、多任务并发、进度查询、取消/重试和逐张/ZIP 下载。

## 新版批量工作台

- 最多上传 50 张图片，按文件名自然排序（图1、图2、图10）；工作台不再提供品牌文案或 Logo 替换。
- OCR 默认关闭，不请求识别接口且不显示文字块编辑。打开后可编辑每张图的文字；参考图组合模式不启用 OCR。
- 通用提示词模式：每张图片独立执行同一个提示词，默认只生成原比例一张；可多选原比例、1:1、3:4、16:9，50 张全选四种比例共生成 200 张。
- 参考图组合模式：多选待处理图，输入「背景」等替换内容，选择一张参考图；只向模型提供当前待处理图与参考图，参考图不计入生成目标。
- 每种比例都从同一输入独立生成，不串联其他比例的输出。OCR 编辑步骤依赖串行完成后再生成比例变体；不同图片/任务可并发执行，单个变体失败不阻断其他变体。
- 模型提示词要求保留主体自然比例；后处理采用等比缩放补白而非拉伸。原比例输出保持原图尺寸；1:1 为 1024×1024，3:4 为 900×1200，16:9 为 1600×900。补白可能出现白边，模型自身的内容生成仍需人工检查。
- 输出命名如 `图1-原比例.png`、`图1-16比9.png`（冒号不能用于 Windows 文件名）；重名自动加序号。ZIP 按原图顺序收录已完成的最终结果，OCR 中间步骤仍可逐张下载。
- 按每次生成 0.05 元显示预估，50 张单比例预计 2.50 元，四比例预计 10.00 元；OCR 编辑调用也计入估算。失败重试可能产生额外费用，以实际账单为准。
- 批量任务通过“渠道管理”分别设置每个渠道的并发，所有批量任务共享各渠道额度；使用异步任务和信号量，不为每张图片创建操作系统线程。
- `POST /api/generate/multi-image` 创建新模式任务，`GET /api/task/{task_id}/download` 下载已完成最终结果 ZIP；原批量/高级编辑 API 保持兼容。

## 前端页面与生成结果

- 顶部导航支持切换工作台（`/`）、任务历史（`/tasks`）和长图拼接（`/composite`）；手机端同样直接显示导航入口。
- 工作台的「任务进度与生成结果」按步骤实时显示已生成图片，点击图片可放大预览，每张图片都可单独下载，无需等待任务全部完成。
- 刷新页面或切换页面后返回工作台，会恢复当前浏览器标签页最近提交的任务。历史任务可从任务历史进入详情（`/tasks/:id`）查看结果并下载。
- 任务查询遇到临时网络错误会自动重试；在详情页重试失败步骤后会重新追踪进度和结果。

## 启动

### Docker 一键启动

#### Windows

1. 安装 Docker Desktop for Windows，安装时启用 WSL 2 backend。
2. 启动 Docker Desktop，确认右下角状态为 Running。
3. 用 PowerShell 进入项目根目录：

```powershell
cd C:\path\to\aigc-agent
Copy-Item .env.example .env
notepad .env
```

在 `.env` 中填入 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`，保存后执行：

```powershell
docker compose up --build
```

浏览器打开 `http://localhost:8080`。停止服务时，在 PowerShell 按 `Ctrl+C`，或者执行：

```powershell
docker compose down
```

Windows 不需要安装 Conda、Python、Node.js 或 PaddleOCR；这些依赖都在 Docker 容器中安装。

#### NATAPP 内网穿透自动启动

在项目根目录 `.env` 中设置 `NATAPP_AUTHTOKEN=你的隧道token`，然后执行 `docker compose up --build -d`，项目和隧道会一起启动，不再需要双击桌面的 `内网隧穿.bat`。本机已从该批处理迁移 token；真实 token 仅保存在不提交 Git 的 `.env` 中。

现有隧道在 NATAPP 控制台配置的本地地址是 `127.0.0.1:5173`。NATAPP 容器与前端共享网络，前端 Nginx 在该地址额外监听，将公网请求交给同一个项目；本机仍使用 `http://localhost:8080`。更换隧道时，也请将控制台的本地地址设为 `127.0.0.1:5173`。

首次启动会从 NATAPP 官网下载 Linux 客户端，缓存到 `natapp-client` volume；之后启动直接使用缓存。留空 `NATAPP_AUTHTOKEN` 可禁用隧道，修改后执行 `docker compose up -d` 生效。不要同时运行使用同一 token 的桌面批处理。

执行 `docker compose logs -f natapp` 查看连接状态和公网地址。`docker compose stop` 或 `docker compose down` 会一起停止项目和隧道。

#### macOS / Linux

电脑安装 Docker 后，在项目根目录执行：

```bash
cp .env.example .env
# 编辑 .env，填入 OPENAI_API_KEY 和 OPENAI_BASE_URL
docker compose up --build
```

打开 `http://localhost:8080` 使用系统，API 文档地址为 `http://localhost:8080/docs`。

停止服务：

```bash
docker compose down
```

上传文件、任务数据库和生成结果保存在 Docker volumes 中。需要连同数据一起删除时执行：

```bash
docker compose down -v
```

首次构建会安装 OCR、图像处理和模型依赖，耗时可能较长；之后启动可直接执行 `docker compose up`。

```bash
cp .env.example .env
# 编辑 .env，填入 OPENAI_API_KEY 和 OPENAI_BASE_URL
conda env create -f environment.yml
conda activate ecom-image-studio
uvicorn backend.main:app --reload --port 8000
```

如果环境已经创建过，可执行：

```bash
conda activate ecom-image-studio
conda install -c conda-forge libmagic
python -m pip install -r backend/requirements.txt pytest
```

运行测试：

```bash
conda activate ecom-image-studio
python -m pytest -q
```

## API 示例

```bash
curl http://localhost:8000/api/health

curl -F 'files=@test.png' http://localhost:8000/api/upload

curl -X POST http://localhost:8000/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{"file_ids":["src_xxx"]}'

curl -X POST http://localhost:8000/api/generate/batch \
  -H 'Content-Type: application/json' \
  -d '{"source_ids":["src_xxx"],"edit_rule":{"quality":"high","strategy":"serial"},"per_source_overrides":{"src_xxx":{"text_blocks":[{"id":"T1","replace":"新品首发"}]}}}'

curl -X POST http://localhost:8000/api/prompt/preview \
  -H 'Content-Type: application/json' \
  -d '{"prompt_type":"text","original":"音乐随身携带","replace":"新品首发","position":"top-left"}'

curl -X POST http://localhost:8000/api/task/create \
  -H 'Content-Type: application/json' \
  -d '{"file_id":"src_xxx","mask":{"x1":100,"y1":100,"x2":500,"y2":220},"prompt":"Replace the text in this area with New Copy."}'

curl http://localhost:8000/api/task/task_xxx
curl -X POST http://localhost:8000/api/task/task_xxx/cancel
```

详细设计和后续阶段见 `文档/终极开发文档.md`。

## OCR 分析

`POST /api/analyze` 接受 1 至 16 个已上传的 `file_ids`，按图片返回 `T1`、`T2` 等文字块、原图像素坐标、九宫格位置、原文、置信度、独立 Mask URL 和缩略图 URL。

分析结果保存在 SQLite 中，同一 `file_id` 重复分析使用缓存以保持编号和 Mask URL 稳定。单张图片失败会返回该图片的 `error`，不会中断其他图片。首次分析需要下载 PaddleOCR 模型；后续使用本地模型缓存。CPU 推理在线程中运行并串行访问 OCR 引擎，不阻塞异步接口。

本阶段只识别文字，不进行 Logo 检测；`logo_blocks` 暂为空。Mask 向外扩展 6 像素并裁剪到原图边界，保持原图尺寸和 RGBA Alpha 语义。

## Prompt 模板

第四阶段将 Prompt 统一收敛到 `backend/services/prompt_builder.py`，支持 `background`、`shade`、`bulb`、`text` 和 `logo` 五类模板。批量文字替换强制携带原文、替换文案和九宫格位置；实际调用的完整 Prompt 会随 Job 输入快照保存。`POST /api/prompt/preview` 可在提交任务前预览模板渲染结果。

## 第五阶段高级编辑

`POST /api/edit/advanced` 支持 `logo`、`background`、`shade` 和 `bulb` 四类单步编辑。Logo 编辑需要 `reference_file_id`，后端会把原图和 Logo 参考图作为两张输入图提交；背景编辑使用 `rembg` 生成主体保护 Mask；换色和组件替换使用请求中的矩形 Mask。

示例：

```bash
curl -X POST http://localhost:8000/api/edit/advanced \
  -H 'Content-Type: application/json' \
  -d '{"source_id":"src_xxx","edit_type":"background","background":"a clean white studio background","subject":"the waist bag"}'
```

高级编辑仍然是异步 Task/Job，使用 `GET /api/task/{task_id}` 查询结果。背景分割模型首次运行会下载本地模型文件；Logo、背景和主体编辑只在后端完成验证，前端工作台将在后续阶段接入。

## 第六阶段长图拼接

`POST /api/composite` 接受已上传的 `file_id` 或已完成 Job 的输出文件名，按 `image_ids` 顺序纵向拼接，支持 `width`、`gap`、`background_color`、`padding_top` 和 `padding_bottom`。图片等比缩放到目标宽度，结果登记为新的 `file_id`，可通过 `GET /api/files/{file_id}` 下载。

```bash
curl -X POST http://localhost:8000/api/composite \
  -H 'Content-Type: application/json' \
  -d '{"image_ids":["src_a","src_b"],"width":750,"gap":0,"background_color":"#FFFFFF","padding_top":20,"padding_bottom":20}'
```

# ECOM IMAGE STUDIO

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
- 建议先设置 `MAX_CONCURRENCY=10`，验证服务商限流后再提高到 20；支持 1–20。使用异步任务和共享信号量，不为每张图片创建操作系统线程；所有任务合计不超过上限。现有 `.env` 中的旧值不会自动覆盖，需要自行修改并重启后端。此上限适用于单后端进程，暂不支持多进程共享限流。
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

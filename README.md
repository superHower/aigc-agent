# ECOM IMAGE STUDIO

当前实现包含第三阶段批量任务：上传图片、OCR 识别文字、生成独立 Mask、按图片串行批量编辑、最多 3 个模型调用并发、查询任务、取消任务和下载输出。

## 启动

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

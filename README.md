# ECOM IMAGE STUDIO

当前实现为第一阶段后端闭环：上传图片、生成矩形 Mask、创建异步单图编辑任务、查询任务、取消任务和下载输出。

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

curl -X POST http://localhost:8000/api/task/create \
  -H 'Content-Type: application/json' \
  -d '{"file_id":"src_xxx","mask":{"x1":100,"y1":100,"x2":500,"y2":220},"prompt":"Replace the text in this area with New Copy."}'

curl http://localhost:8000/api/task/task_xxx
curl -X POST http://localhost:8000/api/task/task_xxx/cancel
```

详细设计和后续阶段见 `文档/终极开发文档.md`。

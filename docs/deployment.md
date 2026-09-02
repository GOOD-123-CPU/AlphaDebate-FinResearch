# 部署指南

## 本地运行

### 1. 克隆与安装

```bash
git clone https://github.com/GOOD-123-CPU/finsightpro.git
cd finsightpro
pip install -r requirements.txt
```

### 2. 配置

```bash
# Windows
copy .env.example .env
# Linux / macOS
cp .env.example .env
```

编辑 `.env`，至少填写：

```bash
SECRET_KEY=<随机字符串>
LLM_API_URL=https://api.deepseek.com/v1/chat/completions
LLM_API_KEY=<你的Key>
LLM_MODEL=deepseek-v3
```

支持任意 OpenAI 兼容服务商（DeepSeek / Qwen / GLM / Kimi / 本地 vLLM），
只需修改 `LLM_API_URL` 与 `LLM_MODEL`。

### 3. 启动

```bash
python run.py                 # 默认 http://127.0.0.1:5231
python run.py --port 8080     # 自定义端口
```

首次启动自动创建 SQLite 数据库并生成演示账号：

- 用户名：`demo`
- 密码：`password`

> 上线前请删除 demo 账号或修改密码。

### 4. 使用

1. 浏览器打开 `http://127.0.0.1:5231`，登录
2. 左侧选择股票（内置 10 只 A 股快捷选项，可搜索）
3. 选择报告类型：股票分析报告 / 前景分析 / 风险预测 / 行业市场分析
4. 点击"生成分析报告"，等待流式生成完成
5. 在"问答记录"标签中针对报告继续提问

## 生产部署

### Gunicorn（Linux）

```bash
pip install gunicorn
gunicorn -w 2 -b 0.0.0.0:5231 "finsight:create_app()"
```

> 注意：报告生成为长耗时 SSE 流式接口，建议将 gunicorn worker
> timeout 设为 600 以上：`--timeout 600`。

### Waitress（Windows）

```bash
pip install waitress
waitress-serve --host 0.0.0.0 --port 5231 finsight:app
```

### 反向代理（Nginx）

```nginx
location / {
    proxy_pass http://127.0.0.1:5231;
    proxy_http_version 1.1;
    proxy_set_header Connection '';
    proxy_buffering off;           # SSE 必须关闭缓冲
    proxy_read_timeout 600s;
}
```

## Docker（可选）

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5231
CMD ["python", "run.py", "--host", "0.0.0.0", "--port", "5231"]
```

```bash
docker build -t finsightpro .
docker run -p 5231:5231 --env-file .env finsightpro
```

## 数据库

默认使用 SQLite（`instance/database.db`），适合单机演示。
生产环境建议更换为 PostgreSQL：修改 `finsight/config.py` 中
`SQLALCHEMY_DATABASE_URI` 即可（SQLAlchemy 兼容）。

## 常见问题

**Q: 报告生成卡在"抓取数据中"？**
AkShare 依赖东财等公开接口，交易时段偶发限流。系统会自动使用 30 分钟内
缓存；如首次抓取失败，稍后点击"重新生成"。

**Q: 生成报错"未配置 LLM_API_KEY"？**
检查 `.env` 是否放在项目根目录、Key 是否有效、`LLM_API_URL` 是否与服务商匹配。

**Q: 想用自己微调的模型？**
见 `docs/finetuning.md` 第 5 节。

FROM python:3.14-slim

WORKDIR /app

# 先装依赖以利用层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 运行时生成目录（也可挂载卷持久化）
RUN mkdir -p instance result cache

EXPOSE 5231

CMD ["python", "run.py", "--host", "0.0.0.0", "--port", "5231"]

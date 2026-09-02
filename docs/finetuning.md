# 微调复现指南

从数据到模型到服务的完整复现路径。

## 1. 环境准备

需要一张显存 ≥ 24GB 的 GPU（QwQ-32B 4bit LoRA）。
小显存显卡可将基础模型换成 Qwen2.5-7B 等小型号。

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu121
pip install unsloth transformers datasets trl
```

## 2. 数据准备

数据位于 `data/` 目录，格式为 `{system, user, assistant}` 指令微调三段式：

```json
{
    "system": "作为股票分析师，请基于最新A股数据进行投研风险分析……",
    "user": "请进行基本面风险分析",
    "assistant": "贵州茅台(600519)最新年度财报披露显示……"
}
```

可用 4 个分项文件中的任意一个直接训练（见 `data/README.md`）。

## 3. 训练

```bash
python finetune/train.py \
    --model unsloth/QwQ-32B-unsloth-bnb-4bit \
    --data data/industry/clean_industry.json \
    --output output/finance_model \
    --epochs 3 --lora-r 16 --learning-rate 2e-5
```

训练完成后自动导出合并的 16bit 模型到 `output/finance_model/merged_16bit`。

默认超参（LoRA r=16 / alpha=16 / dropout=0.05 / cosine 调度 / warmup 10%）
为原始课题验证过的组合，一般无需修改。

## 4. 交互式验证

```bash
python finetune/infer.py --model output/finance_model/merged_16bit
```

## 5. 部署为 OpenAI 兼容服务（可选）

使用 vLLM 将微调模型暴露为 OpenAI 兼容接口：

```bash
pip install vllm
vllm serve output/finance_model/merged_16bit \
    --host 0.0.0.0 --port 8731 \
    --api-key your-vllm-key
```

然后在 `.env` 中切换 Web 平台使用的模型：

```bash
LLM_API_URL=http://127.0.0.1:8731/v1/chat/completions
LLM_API_KEY=your-vllm-key
LLM_MODEL=output/finance_model/merged_16bit   # vLLM 会以路径作为模型名
```

这样 Web 平台的辩论引擎三个角色（Generator A / Generator B / Judge）
都可以使用你自己微调的模型，实现"自研模型生成研报"的完整闭环。

## 6. 提示

- `--model` 也可以传本地路径或 ModelScope id（unsloth 脚本默认走 HF 生态）。
- 训练数据量小时（<1k 条）建议增加 `--epochs` 至 4–5 并观察 loss。
- 微调模型主要影响文风与分析框架；行情数据实时性由 Web 层 AkShare 保证，
  两者互补而非替代。

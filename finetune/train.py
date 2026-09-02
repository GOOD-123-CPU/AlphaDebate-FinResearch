#!/usr/bin/env python3
"""金融研报模型 LoRA 微调脚本（Unsloth + Qwen/QwQ 系列）。

所有路径与超参均通过命令行参数传入，无硬编码路径。

用法示例：
    python train.py \
        --model unsloth/QwQ-32B-unsloth-bnb-4bit \
        --data data/industry/clean_industry.json \
        --output output/finance_model

依赖（GPU 环境）：
    pip install unsloth transformers datasets trl
"""
import argparse
import os


def parse_args():
    parser = argparse.ArgumentParser(description="金融研报模型 LoRA 微调")
    parser.add_argument("--model", required=True, help="基础模型路径或 HuggingFace/ModelScope id")
    parser.add_argument("--data", required=True, help="训练数据 JSON 文件路径（system/user/assistant 格式）")
    parser.add_argument("--output", required=True, help="训练输出目录")
    parser.add_argument("--max-seq-length", type=int, default=2048)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=16)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--grad-accum", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--seed", type=int, default=3407)
    return parser.parse_args()


TRAIN_PROMPT_STYLE = """### system:
{}

### user:
{}

### assistant:
{}"""

EOS_TOKEN = "<|im_end|>"


def main():
    args = parse_args()
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")

    import torch
    from datasets import load_dataset
    from transformers import TrainingArguments
    from trl import SFTTrainer
    from unsloth import FastLanguageModel

    # 1. 加载模型（4bit 量化）
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.model,
        max_seq_length=args.max_seq_length,
        load_in_4bit=True,
        device_map={"": "cuda:0"},
    )

    # 2. 配置 LoRA
    model = FastLanguageModel.get_peft_model(
        model,
        r=args.lora_r,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        use_gradient_checkpointing=True,
        random_state=args.seed,
    )
    model.to("cuda:0")

    # 3. 加载并格式化数据集
    dataset = load_dataset("json", data_files=args.data, split="train")

    def format_data(examples):
        texts = []
        for system, user, assistant in zip(examples["system"], examples["user"], examples["assistant"]):
            text = TRAIN_PROMPT_STYLE.format(system, user, assistant) + EOS_TOKEN
            texts.append(text)
        return {"text": texts}

    formatted_dataset = dataset.map(format_data, batched=True)

    # 4. 训练配置（自动选择 BF16/FP16）
    supports_bf16 = torch.cuda.is_bf16_supported()

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=formatted_dataset,
        dataset_text_field="text",
        max_seq_length=args.max_seq_length,
        args=TrainingArguments(
            per_device_train_batch_size=args.batch_size,
            gradient_accumulation_steps=args.grad_accum,
            warmup_ratio=0.1,
            num_train_epochs=args.epochs,
            learning_rate=args.learning_rate,
            fp16=not supports_bf16,
            bf16=supports_bf16,
            logging_steps=10,
            optim="adamw_torch",
            weight_decay=0.01,
            lr_scheduler_type="cosine",
            output_dir=args.output,
            seed=args.seed,
            dataloader_pin_memory=False,
            dataloader_num_workers=0,
        ),
    )

    print("\n=== 精度验证 ===")
    print(f"BF16支持状态: {supports_bf16}")
    print(f"当前训练精度: {'BF16' if supports_bf16 else 'FP16'}")

    # 5. 执行训练
    trainer.train()

    # 6. 保存合并后的 16bit 模型
    model.save_pretrained_merged(
        save_directory=os.path.join(args.output, "merged_16bit"),
        tokenizer=tokenizer,
        save_method="merged_16bit",
        push_to_hub=False,
    )
    print(f"\n✓ 训练完成，模型已保存至: {os.path.join(args.output, 'merged_16bit')}")


if __name__ == "__main__":
    main()

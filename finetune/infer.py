#!/usr/bin/env python3
"""微调后的金融分析模型交互式推理脚本。

用法示例：
    python infer.py --model output/finance_model/merged_16bit

依赖（GPU 环境）：
    pip install torch transformers accelerate bitsandbytes modelscope
"""
import argparse

PROMPT_STYLE = """### system:
{}

### user:
{}

### assistant:
{}"""


def main():
    parser = argparse.ArgumentParser(description="金融分析模型交互式推理")
    parser.add_argument("--model", required=True, help="微调后模型目录（merged_16bit）")
    parser.add_argument("--system", default="你是一个金融分析师", help="system 提示词")
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    parser.add_argument("--temperature", type=float, default=0.7)
    args = parser.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    quantization_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_quant_type="nf4",
    )

    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        quantization_config=quantization_config,
        device_map="auto",
        trust_remote_code=True,
    )
    tokenizer = AutoTokenizer.from_pretrained(args.model)

    print("欢迎使用金融分析问答系统，输入 'exit' 可退出。")
    while True:
        user_prompt = input("请输入你的问题: ").strip()
        if user_prompt.lower() == "exit":
            break
        if not user_prompt:
            continue

        prompt = PROMPT_STYLE.format(args.system, user_prompt, "")
        model_inputs = tokenizer(prompt, return_tensors="pt").to("cuda")

        generated_ids = model.generate(
            **model_inputs,
            max_new_tokens=args.max_new_tokens,
            do_sample=True,
            temperature=args.temperature,
            top_p=0.9,
            repetition_penalty=1.1,
        )

        response = tokenizer.decode(
            generated_ids[0][len(model_inputs.input_ids[0]):],
            skip_special_tokens=True,
        )
        print(response)


if __name__ == "__main__":
    main()

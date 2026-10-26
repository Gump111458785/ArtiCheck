"""Minimal assistant-only LoRA SFT. GPU execution is not validated in this MVP."""
from __future__ import annotations

import argparse
import json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-length", type=int, default=4096)
    parser.add_argument("--epochs", type=float, default=1)
    args = parser.parse_args()
    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    examples = []
    with open(args.data) as file:
        for line in file:
            row = json.loads(line)
            messages = row["messages"]
            if messages[-1]["role"] != "assistant":
                raise ValueError("SFT sample must end with assistant")
            prompt = tokenizer.apply_chat_template(messages[:-1], add_generation_prompt=True)
            full = tokenizer.apply_chat_template(messages, add_generation_prompt=False)
            if full[:len(prompt)] != prompt:
                raise ValueError("Chat template is not prefix-preserving; implement a template-aware label mask")
            if len(full) > args.max_length:
                continue  # never truncate a planner action mid-JSON
            examples.append({"input_ids": full, "attention_mask": [1]*len(full),
                             "labels": [-100]*len(prompt) + full[len(prompt):]})
    if not examples:
        raise ValueError("No accepted, in-budget SFT samples")
    model = AutoModelForCausalLM.from_pretrained(args.model, torch_dtype=torch.bfloat16)
    model.config.use_cache = False
    model = get_peft_model(model, LoraConfig(r=16, lora_alpha=32, lora_dropout=.05,
                                          target_modules="all-linear", task_type="CAUSAL_LM"))
    model.enable_input_require_grads()
    def collate(rows):
        length = max(len(r["input_ids"]) for r in rows)
        return {key: torch.tensor([r[key] + [padding]*(length-len(r[key])) for r in rows])
                for key, padding in (("input_ids", tokenizer.pad_token_id), ("attention_mask", 0), ("labels", -100))}
    trainer = Trainer(model=model, train_dataset=Dataset.from_list(examples), data_collator=collate,
                      args=TrainingArguments(output_dir=args.output, num_train_epochs=args.epochs,
                                             per_device_train_batch_size=1, gradient_accumulation_steps=8,
                                             learning_rate=2e-5, bf16=True, gradient_checkpointing=True,
                                             report_to="none", save_strategy="epoch"))
    trainer.train()
    model.save_pretrained(args.output)
    tokenizer.save_pretrained(args.output)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence

import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import (
    AutoModelForCausalLM,
    AutoModelForImageTextToText,
    AutoModelForVision2Seq,
    AutoProcessor,
    AutoTokenizer,
    BitsAndBytesConfig,
    Trainer,
    TrainingArguments,
)


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Run QLoRA SFT for campus semantic mission parsing.")
    parser.add_argument("--model-path", type=Path, default=Path("/workspace/models/Qwen3-VL-4B-Instruct"))
    parser.add_argument(
        "--train-file",
        type=Path,
        default=project_root / "data" / "training" / "semantic_sft" / "semantic_sft_train.jsonl",
    )
    parser.add_argument(
        "--eval-file",
        type=Path,
        default=project_root / "data" / "training" / "semantic_sft" / "semantic_sft_eval.jsonl",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=project_root / "data" / "models" / "semantic_sft",
    )
    parser.add_argument("--num-train-epochs", type=float, default=1.0)
    parser.add_argument("--per-device-train-batch-size", type=int, default=1)
    parser.add_argument("--per-device-eval-batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--weight-decay", type=float, default=0.01)
    parser.add_argument("--warmup-ratio", type=float, default=0.05)
    parser.add_argument("--logging-steps", type=int, default=5)
    parser.add_argument("--max-length", type=int, default=1536)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def set_seed(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def build_chat_text(processor, tokenizer, messages: Sequence[Dict[str, Any]], add_generation_prompt: bool) -> str:
    for candidate in (processor, tokenizer):
        if candidate is None or not hasattr(candidate, "apply_chat_template"):
            continue
        try:
            return candidate.apply_chat_template(
                list(messages),
                tokenize=False,
                add_generation_prompt=add_generation_prompt,
            )
        except Exception:
            continue

    text_parts: List[str] = []
    for item in messages:
        text_parts.append(f"{item['role']}: {item['content']}")
    if add_generation_prompt:
        text_parts.append("assistant:")
    return "\n".join(text_parts)


def load_processing_stack(model_path: Path):
    processor = None
    try:
        processor = AutoProcessor.from_pretrained(str(model_path), trust_remote_code=True)
    except Exception:
        processor = None
    tokenizer = AutoTokenizer.from_pretrained(str(model_path), trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    return processor, tokenizer


def tokenize_example(processor, tokenizer, record: Dict[str, Any], max_length: int) -> Dict[str, Any]:
    messages = record["messages"]
    prompt_messages = messages[:-1]
    full_text = build_chat_text(processor, tokenizer, messages, add_generation_prompt=False)
    prompt_text = build_chat_text(processor, tokenizer, prompt_messages, add_generation_prompt=True)
    full_ids = tokenizer(full_text, add_special_tokens=False).input_ids
    prompt_ids = tokenizer(prompt_text, add_special_tokens=False).input_ids

    input_ids = list(full_ids)
    labels = list(full_ids)
    prompt_len = min(len(prompt_ids), len(labels))
    labels[:prompt_len] = [-100] * prompt_len

    if len(input_ids) > max_length:
        overflow = len(input_ids) - max_length
        input_ids = input_ids[overflow:]
        labels = labels[overflow:]

    attention_mask = [1] * len(input_ids)
    return {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
        "labels": labels,
    }


class SupervisedCollator:
    def __init__(self, pad_token_id: int):
        self.pad_token_id = pad_token_id

    def __call__(self, features: List[Dict[str, Any]]) -> Dict[str, torch.Tensor]:
        max_len = max(len(item["input_ids"]) for item in features)
        batch = {"input_ids": [], "attention_mask": [], "labels": []}
        for item in features:
            pad_len = max_len - len(item["input_ids"])
            batch["input_ids"].append(item["input_ids"] + [self.pad_token_id] * pad_len)
            batch["attention_mask"].append(item["attention_mask"] + [0] * pad_len)
            batch["labels"].append(item["labels"] + [-100] * pad_len)
        return {key: torch.tensor(value, dtype=torch.long) for key, value in batch.items()}


def load_quantized_model(model_path: Path):
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )
    model_kwargs = {
        "trust_remote_code": True,
        "low_cpu_mem_usage": True,
        "device_map": {"": 0},
        "attn_implementation": "sdpa",
        "quantization_config": bnb_config,
    }
    last_error = None
    for model_class in (AutoModelForVision2Seq, AutoModelForImageTextToText, AutoModelForCausalLM):
        try:
            return model_class.from_pretrained(str(model_path), **model_kwargs)
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"failed to load model from {model_path}: {last_error}")


def count_trainable_params(model) -> Dict[str, int]:
    trainable = 0
    total = 0
    for _, param in model.named_parameters():
        total += param.numel()
        if param.requires_grad:
            trainable += param.numel()
    return {"trainable": int(trainable), "total": int(total)}


def prepare_datasets(processor, tokenizer, train_rows: List[Dict[str, Any]], eval_rows: List[Dict[str, Any]], max_length: int):
    train_ds = Dataset.from_list([tokenize_example(processor, tokenizer, row, max_length) for row in train_rows])
    eval_ds = Dataset.from_list([tokenize_example(processor, tokenizer, row, max_length) for row in eval_rows])
    return train_ds, eval_ds


def main() -> None:
    args = parse_args()
    set_seed(args.seed)
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for QLoRA training in this setup.")

    model_path = args.model_path.resolve()
    output_root = args.output_root.resolve()
    runs_dir = output_root / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_name = datetime.now().strftime("run_%Y%m%d_%H%M%S")
    run_dir = runs_dir / run_name
    adapter_dir = run_dir / "adapter"
    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    train_rows = read_jsonl(args.train_file.resolve())
    eval_rows = read_jsonl(args.eval_file.resolve())
    processor, tokenizer = load_processing_stack(model_path)
    train_ds, eval_ds = prepare_datasets(processor, tokenizer, train_rows, eval_rows, args.max_length)

    model = load_quantized_model(model_path)
    model.config.use_cache = False
    model.gradient_checkpointing_enable()
    model = prepare_model_for_kbit_training(model)

    lora_config = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora_config)

    training_args = TrainingArguments(
        output_dir=str(run_dir / "checkpoints"),
        per_device_train_batch_size=args.per_device_train_batch_size,
        per_device_eval_batch_size=args.per_device_eval_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        weight_decay=args.weight_decay,
        warmup_ratio=args.warmup_ratio,
        num_train_epochs=args.num_train_epochs,
        logging_steps=args.logging_steps,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=2,
        fp16=True,
        bf16=False,
        dataloader_pin_memory=False,
        remove_unused_columns=False,
        report_to=["tensorboard"],
        logging_dir=str(logs_dir),
        optim="paged_adamw_8bit",
        gradient_checkpointing=True,
        seed=args.seed,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        data_collator=SupervisedCollator(tokenizer.pad_token_id),
    )

    train_result = trainer.train()
    eval_metrics = trainer.evaluate()
    adapter_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    if processor is not None:
        try:
            processor.save_pretrained(str(adapter_dir))
        except Exception:
            pass

    active_dir = output_root / "active"
    if active_dir.is_symlink() or active_dir.is_file():
        active_dir.unlink()
    elif active_dir.exists():
        shutil.rmtree(active_dir)
    shutil.copytree(adapter_dir, active_dir)

    summary = {
        "run_name": run_name,
        "base_model_path": str(model_path),
        "adapter_dir": str(adapter_dir),
        "active_adapter_dir": str(active_dir),
        "train_examples": len(train_rows),
        "eval_examples": len(eval_rows),
        "trainable_params": count_trainable_params(model),
        "training_args": {
            "num_train_epochs": args.num_train_epochs,
            "per_device_train_batch_size": args.per_device_train_batch_size,
            "gradient_accumulation_steps": args.gradient_accumulation_steps,
            "learning_rate": args.learning_rate,
            "max_length": args.max_length,
            "lora_r": args.lora_r,
            "lora_alpha": args.lora_alpha,
            "lora_dropout": args.lora_dropout,
        },
        "train_metrics": train_result.metrics,
        "eval_metrics": eval_metrics,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

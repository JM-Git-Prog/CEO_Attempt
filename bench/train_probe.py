"""Training probe - QLoRA fine-tune of llama-3.1-8B on the probe dataset.

Runs in the dedicated venv created by INSTALL-TRAINING-KIT.bat, on the 4090.
Outputs a GGUF + Modelfile and prints the exact `ollama create` command, so
the tuned model becomes a normal Ollama lane that plan_bench.py can score
against base llama3.1's measured legal-plan rate.

Expectations set honestly: with tens of examples this proves the PIPELINE
and gives a baseline delta. Gains, if any, will be format-tightening.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "flywheel" / "training" / "probe-v1.jsonl"
OUT = ROOT / "bench" / "trained" / time.strftime("probe-v1-%Y%m%dT%H%M%S")

BASE_MODEL = "unsloth/Meta-Llama-3.1-8B-Instruct-bnb-4bit"  # ~6 GB download, 4-bit
MAX_SEQ = 4096
EPOCHS = 3
LR = 2e-4

# Live status for the Training Monitor desktop app - one small JSON file,
# overwritten as training moves. Only ever written from real trainer
# callbacks and real stage transitions below - never fabricated.
PROGRESS = ROOT / "bench" / "training-progress.json"


def _write_progress(**fields) -> None:
    PROGRESS.write_text(json.dumps({"updated": time.time(), **fields}), encoding="utf-8")


def main() -> int:
    if not DATA.exists():
        print(f"Missing {DATA} - run make_training_set.py first.")
        return 1

    from datasets import Dataset
    from unsloth import FastLanguageModel
    from trl import SFTTrainer
    from transformers import TrainingArguments, TrainerCallback

    class ProgressCallback(TrainerCallback):
        """Mirrors the trainer's own step/loss into PROGRESS - real numbers only."""

        def on_train_begin(self, args, state, control, **kw):
            _write_progress(stage="training", run_id=run_id, rows=len(rows),
                             step=0, max_steps=state.max_steps, epoch=0.0, loss=None)

        def on_log(self, args, state, control, logs=None, **kw):
            if logs and "loss" in logs:
                _write_progress(stage="training", run_id=run_id, rows=len(rows),
                                 step=state.global_step, max_steps=state.max_steps,
                                 epoch=round(state.epoch or 0, 3), loss=logs["loss"])

    rows = [json.loads(l) for l in DATA.read_text(encoding="utf-8").splitlines() if l.strip()]
    print(f"Training rows: {len(rows)} | base: {BASE_MODEL}")
    run_id = OUT.name
    _write_progress(stage="loading_model", run_id=run_id, rows=len(rows))

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=BASE_MODEL, max_seq_length=MAX_SEQ, load_in_4bit=True,
    )
    model = FastLanguageModel.get_peft_model(
        model, r=16, lora_alpha=16, lora_dropout=0.0,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )

    def to_text(row):
        return {"text": tokenizer.apply_chat_template(
            row["messages"], tokenize=False, add_generation_prompt=False)}

    ds = Dataset.from_list([to_text(r) for r in rows])
    trainer = SFTTrainer(
        model=model, tokenizer=tokenizer, train_dataset=ds,
        dataset_text_field="text", max_seq_length=MAX_SEQ,
        args=TrainingArguments(
            output_dir=str(OUT / "checkpoints"),
            per_device_train_batch_size=1, gradient_accumulation_steps=4,
            num_train_epochs=EPOCHS, learning_rate=LR, logging_steps=5,
            save_strategy="no", bf16=True, report_to=[], seed=13,
        ),
        callbacks=[ProgressCallback()],
    )
    trainer.train()

    OUT.mkdir(parents=True, exist_ok=True)
    _write_progress(stage="saving_gguf", run_id=run_id, rows=len(rows))
    print("Saving merged GGUF (q4_k_m) - takes a few minutes...")
    model.save_pretrained_gguf(str(OUT), tokenizer, quantization_method="q4_k_m")

    gguf = next(OUT.glob("*.gguf"), None)
    modelfile = OUT / "Modelfile"
    modelfile.write_text(f"FROM {gguf}\n", encoding="utf-8")
    ollama_cmd = f'ollama create planner-probe-v1 -f "{modelfile}"'
    _write_progress(stage="done", run_id=run_id, rows=len(rows), ollama_cmd=ollama_cmd,
                     modelfile=str(modelfile))
    print("\n=== DONE - register the lane ===")
    print(ollama_cmd)
    print('then bench it:')
    print('python bench\\plan_bench.py --lanes "llama3.1,planner-probe-v1" --prompts 30')
    return 0


if __name__ == "__main__":
    sys.exit(main())

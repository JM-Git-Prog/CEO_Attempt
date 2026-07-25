"""Training probe - QLoRA fine-tune of llama-3.1-8B on the probe dataset.

Runs in the dedicated venv created by INSTALL-TRAINING-KIT.bat, on the 4090.
Outputs a GGUF + Modelfile and prints the exact `ollama create` command, so
the tuned model becomes a normal Ollama lane that plan_bench.py can score
against base llama3.1's measured legal-plan rate.

Expectations set honestly: with tens of examples this proves the PIPELINE
and gives a baseline delta. Gains, if any, will be format-tightening.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "flywheel" / "training" / "probe-v1.jsonl"

BASE_MODEL = "unsloth/Meta-Llama-3.1-8B-Instruct-bnb-4bit"  # ~6 GB download, 4-bit
MAX_SEQ = 4096

# Hyperparameter defaults. bench/best-hparams.json - written by Stage C's
# sweep (bench/hparam_sweep.py) once a candidate beats the current default
# on the holdout set - overrides these automatically; explicit CLI flags
# override both. A plain run with no file and no flags trains exactly like
# it always has.
DEFAULTS = {"rank": 16, "alpha": 16, "dropout": 0.0, "epochs": 3, "lr": 2e-4,
            "model_name": "planner-probe-v1"}
BEST_HPARAMS_FILE = ROOT / "bench" / "best-hparams.json"

# Live status for the Training Monitor desktop app - one small JSON file,
# overwritten as training moves. Only ever written from real trainer
# callbacks and real stage transitions below - never fabricated.
PROGRESS = ROOT / "bench" / "training-progress.json"


def _load_defaults() -> dict:
    cfg = dict(DEFAULTS)
    if BEST_HPARAMS_FILE.exists():
        try:
            cfg.update(json.loads(BEST_HPARAMS_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


def _write_progress(**fields) -> None:
    PROGRESS.write_text(json.dumps({"updated": time.time(), **fields}), encoding="utf-8")


def main() -> int:
    if not DATA.exists():
        print(f"Missing {DATA} - run make_training_set.py first.")
        return 1

    cfg = _load_defaults()
    ap = argparse.ArgumentParser()
    ap.add_argument("--rank", type=int, default=cfg["rank"])
    ap.add_argument("--alpha", type=int, default=cfg["alpha"])
    ap.add_argument("--dropout", type=float, default=cfg["dropout"])
    ap.add_argument("--epochs", type=int, default=cfg["epochs"])
    ap.add_argument("--lr", type=float, default=cfg["lr"])
    ap.add_argument("--model-name", dest="model_name", default=cfg["model_name"],
                     help="Ollama registration name - use a distinct name for "
                          "sweep candidates so the live default is never overwritten")
    ap.add_argument("--run-name", dest="run_name", default="",
                     help="optional label folded into the output folder name")
    args = ap.parse_args()

    out_stamp = time.strftime("%Y%m%dT%H%M%S")
    out_label = f"probe-v1-{args.run_name}-{out_stamp}" if args.run_name else f"probe-v1-{out_stamp}"
    out = ROOT / "bench" / "trained" / out_label

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
    print(f"Training rows: {len(rows)} | base: {BASE_MODEL} | "
          f"rank={args.rank} alpha={args.alpha} dropout={args.dropout} "
          f"epochs={args.epochs} lr={args.lr} -> {args.model_name}")
    run_id = out.name
    _write_progress(stage="loading_model", run_id=run_id, rows=len(rows))

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=BASE_MODEL, max_seq_length=MAX_SEQ, load_in_4bit=True,
    )
    model = FastLanguageModel.get_peft_model(
        model, r=args.rank, lora_alpha=args.alpha, lora_dropout=args.dropout,
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
            output_dir=str(out / "checkpoints"),
            per_device_train_batch_size=1, gradient_accumulation_steps=4,
            num_train_epochs=args.epochs, learning_rate=args.lr, logging_steps=5,
            save_strategy="no", bf16=True, report_to=[], seed=13,
        ),
        callbacks=[ProgressCallback()],
    )
    trainer.train()

    out.mkdir(parents=True, exist_ok=True)
    _write_progress(stage="saving_gguf", run_id=run_id, rows=len(rows))
    print("Saving merged GGUF (q4_k_m) - takes a few minutes...")
    model.save_pretrained_gguf(str(out), tokenizer, quantization_method="q4_k_m")

    gguf = next(out.glob("*.gguf"), None)
    modelfile = out / "Modelfile"
    modelfile.write_text(f"FROM {gguf}\n", encoding="utf-8")
    ollama_cmd = f'ollama create {args.model_name} -f "{modelfile}"'
    _write_progress(stage="done", run_id=run_id, rows=len(rows), ollama_cmd=ollama_cmd,
                     modelfile=str(modelfile), model_name=args.model_name,
                     hparams={"rank": args.rank, "alpha": args.alpha, "dropout": args.dropout,
                              "epochs": args.epochs, "lr": args.lr})
    print("\n=== DONE - register the lane ===")
    print(ollama_cmd)
    print('then bench it:')
    print(f'python bench\\plan_bench.py --lanes "llama3.1,{args.model_name}" --prompts 30')
    return 0


if __name__ == "__main__":
    sys.exit(main())

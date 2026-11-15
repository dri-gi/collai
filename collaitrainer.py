
import os
import json
import shutil
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path

# ============================================================
# COLLAI TRAINER
# Windows GUI + conversation editor + LoRA training + deployment
# ============================================================

UNO_HOST = os.environ.get("COLLAI_UNO_HOST", "arduino@collain.local")
REMOTE_JSONL = "/home/arduino/conversations.jsonl"
REMOTE_DIR = "/home/arduino/CollAI_Trainer"

BASE_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
OLLAMA_MODEL = "collai:trained"

APP_DIR = Path.home() / "CollAI_Trainer"
IMPORT_DIR = APP_DIR / "imports"
OUTPUT_DIR = APP_DIR / "output"
MERGED_DIR = OUTPUT_DIR / "merged_model"

APP_DIR.mkdir(exist_ok=True)
IMPORT_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

records = []
selected_index = None
current_file = None


# ============================================================
# UTILITIES
# ============================================================

def log(message):
    root.after(0, lambda: (
        log_box.insert(tk.END, message + "\n"),
        log_box.see(tk.END)
    ))


def run_command(command, description):
    log(description)
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        shell=False
    )

    if result.stdout:
        log(result.stdout.strip())

    if result.stderr:
        log(result.stderr.strip())

    if result.returncode != 0:
        raise RuntimeError(
            f"{description} failed:\n{result.stderr}"
        )

    return result


def get_messages(record):
    """
    Supports the JSONL format used by the UNO Q chat program.
    """
    if isinstance(record, list):
        return record

    if isinstance(record, dict):
        messages = record.get("messages")

        if isinstance(messages, list):
            return messages

        conversation = record.get("conversation")

        if isinstance(conversation, list):
            return conversation

    return []


def normalize_message(message):
    if not isinstance(message, dict):
        return {
            "role": "user",
            "content": str(message)
        }

    role = message.get("role", "user")
    content = message.get("content", "")

    if isinstance(content, list):
        content = " ".join(
            str(item.get("text", item))
            if isinstance(item, dict)
            else str(item)
            for item in content
        )

    return {
        "role": str(role),
        "content": str(content)
    }


def load_jsonl(path):
    loaded = []

    with open(path, "r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, 1):
            if not line.strip():
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as e:
                log(f"Skipped malformed line {line_number}: {e}")
                continue

            messages = get_messages(record)

            if not messages:
                log(f"Skipped line {line_number}: no messages found")
                continue

            normalized = [
                normalize_message(m)
                for m in messages
            ]

            loaded.append({
                "messages": normalized,
                "approved": False,
                "source": record
            })

    return loaded


def save_records(path):
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            output = {
                "messages": record["messages"],
                "approved": record["approved"]
            }

            f.write(json.dumps(output, ensure_ascii=False) + "\n")


# ============================================================
# IMPORT / EXPORT
# ============================================================

def import_local():
    global records, current_file

    path = filedialog.askopenfilename(
        title="Import conversation JSONL",
        filetypes=[("JSONL files", "*.jsonl"), ("All files", "*.*")]
    )

    if not path:
        return

    try:
        records = load_jsonl(path)
        current_file = Path(path)

        refresh_list()

        log(f"Imported {len(records)} conversations.")
        messagebox.showinfo(
            "Import complete",
            f"Imported {len(records)} conversations."
        )

    except Exception as e:
        messagebox.showerror("Import error", str(e))


def import_from_uno():
    def worker():
        try:
            destination = IMPORT_DIR / "conversations.jsonl"

            run_command(
                [
                    "scp",
                    f"{UNO_HOST}:{REMOTE_JSONL}",
                    str(destination)
                ],
                "Importing conversations from UNO Q..."
            )

            global records, current_file

            records = load_jsonl(destination)
            current_file = destination

            root.after(0, refresh_list)

            log(f"Imported {len(records)} conversations from UNO Q.")

        except Exception as e:
            log(f"Import failed: {e}")
            root.after(
                0,
                lambda: messagebox.showerror("Import failed", str(e))
            )

    threading.Thread(target=worker, daemon=True).start()


def export_records():
    if not records:
        messagebox.showwarning("Nothing to export", "Import conversations first.")
        return

    path = filedialog.asksaveasfilename(
        defaultextension=".jsonl",
        filetypes=[("JSONL files", "*.jsonl")]
    )

    if not path:
        return

    try:
        save_records(path)
        messagebox.showinfo("Exported", f"Saved to:\n{path}")
        log(f"Exported conversations to {path}")
    except Exception as e:
        messagebox.showerror("Export error", str(e))


# ============================================================
# CONVERSATION LIST
# ============================================================

def refresh_list():
    conversation_list.delete(0, tk.END)

    for i, record in enumerate(records):
        messages = record["messages"]

        user_count = sum(
            1 for m in messages if m["role"] == "user"
        )

        status = "APPROVED" if record["approved"] else "REVIEW"

        preview = next(
            (
                m["content"].replace("\n", " ")[:45]
                for m in messages
                if m["role"] == "user"
            ),
            "Empty conversation"
        )

        conversation_list.insert(
            tk.END,
            f"{i + 1}. [{status}] ({user_count} user msgs) {preview}"
        )

    count_label.config(
        text=f"Conversations: {len(records)} | "
             f"Approved: {sum(r['approved'] for r in records)}"
    )


def select_conversation(event=None):
    global selected_index

    selection = conversation_list.curselection()

    if not selection:
        return

    selected_index = selection[0]
    load_editor()


# ============================================================
# EDITOR
# ============================================================

def load_editor():
    editor.delete("1.0", tk.END)

    if selected_index is None:
        return

    record = records[selected_index]

    for i, message in enumerate(record["messages"]):
        editor.insert(
            tk.END,
            f"--- MESSAGE {i + 1} | {message['role'].upper()} ---\n"
        )

        editor.insert(
            tk.END,
            message["content"] + "\n\n"
        )

    status_label.config(
        text="APPROVED" if record["approved"] else "NOT APPROVED"
    )


def parse_editor():
    """
    Editor format:
    --- MESSAGE 1 | USER ---
    message text

    --- MESSAGE 2 | ASSISTANT ---
    response text
    """
    text = editor.get("1.0", tk.END).strip()

    messages = []
    current_role = None
    current_content = []

    for line in text.splitlines():
        if line.startswith("--- MESSAGE ") and line.endswith(" ---"):
            if current_role is not None:
                messages.append({
                    "role": current_role,
                    "content": "\n".join(current_content).strip()
                })

            header = line.split("|")

            if len(header) < 2:
                raise ValueError(f"Invalid message header: {line}")

            role = header[1].replace("---", "").strip().lower()

            if role not in ("user", "assistant", "system"):
                raise ValueError(
                    f"Invalid role '{role}'. Use user, assistant, or system."
                )

            current_role = role
            current_content = []

        else:
            if current_role is not None:
                current_content.append(line)

    if current_role is not None:
        messages.append({
            "role": current_role,
            "content": "\n".join(current_content).strip()
        })

    return [
        m for m in messages
        if m["content"].strip()
    ]


def save_edit():
    if selected_index is None:
        return

    try:
        messages = parse_editor()

        if not messages:
            messagebox.showwarning(
                "Empty conversation",
                "Add at least one message before saving."
            )
            return

        records[selected_index]["messages"] = messages

        refresh_list()
        conversation_list.selection_set(selected_index)

        log(f"Saved edits to conversation {selected_index + 1}.")

        messagebox.showinfo(
            "Saved",
            "Conversation edits saved in memory."
        )

    except Exception as e:
        messagebox.showerror("Editor error", str(e))


def add_message():
    if selected_index is None:
        return

    save_edit()

    editor.insert(
        tk.END,
        "\n--- MESSAGE NEW | USER ---\n"
        "Write your message here.\n\n"
    )


def delete_last_message():
    if selected_index is None:
        return

    try:
        messages = parse_editor()

        if not messages:
            return

        messages.pop()

        records[selected_index]["messages"] = messages
        load_editor()

        log("Deleted last message.")

    except Exception as e:
        messagebox.showerror("Editor error", str(e))


def approve():
    if selected_index is None:
        return

    try:
        messages = parse_editor()

        if not messages:
            messagebox.showwarning(
                "Empty conversation",
                "Cannot approve an empty conversation."
            )
            return

        records[selected_index]["messages"] = messages
        records[selected_index]["approved"] = True

        refresh_list()
        conversation_list.selection_set(selected_index)
        load_editor()

        log(f"Approved conversation {selected_index + 1}.")

    except Exception as e:
        messagebox.showerror("Approval error", str(e))


def exclude():
    if selected_index is None:
        return

    records[selected_index]["approved"] = False

    refresh_list()
    conversation_list.selection_set(selected_index)
    load_editor()

    log(f"Excluded conversation {selected_index + 1} from training.")


# ============================================================
# TRAINING DATASET
# ============================================================

def build_training_data():
    examples = []

    for record in records:
        if not record["approved"]:
            continue

        messages = record["messages"]

        # Pair each user message with the next assistant response.
        for i, message in enumerate(messages):
            if message["role"] != "user":
                continue

            for j in range(i + 1, len(messages)):
                if messages[j]["role"] == "assistant":
                    examples.append({
                        "messages": [
                            {
                                "role": "user",
                                "content": message["content"]
                            },
                            {
                                "role": "assistant",
                                "content": messages[j]["content"]
                            }
                        ]
                    })
                    break

                if messages[j]["role"] == "user":
                    break

    return examples


# ============================================================
# FINE TUNING
# ============================================================

def train_model():
    approved_count = sum(r["approved"] for r in records)

    if approved_count == 0:
        messagebox.showwarning(
            "No approved conversations",
            "Approve at least one conversation first."
        )
        return

    examples = build_training_data()

    if not examples:
        messagebox.showwarning(
            "No training examples",
            "Approved conversations need user and assistant messages."
        )
        return

    threading.Thread(
        target=training_worker,
        args=(examples,),
        daemon=True
    ).start()


def training_worker(examples):
    try:
        log(f"Preparing {len(examples)} training examples.")

        import torch
        from datasets import Dataset
        from transformers import (
            AutoTokenizer,
            AutoModelForCausalLM,
            Trainer,
            TrainingArguments,
            DataCollatorForLanguageModeling
        )
        from peft import (
            LoraConfig,
            get_peft_model,
            TaskType
        )

        dataset = Dataset.from_list(examples)

        log(f"Loading {BASE_MODEL}...")

        tokenizer = AutoTokenizer.from_pretrained(
            BASE_MODEL,
            trust_remote_code=True
        )

        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        model = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL,
            torch_dtype=(
                torch.float16 if torch.cuda.is_available()
                else torch.float32
            ),
            device_map="auto" if torch.cuda.is_available() else None
        )

        def format_example(example):
            text = tokenizer.apply_chat_template(
                example["messages"],
                tokenize=False,
                add_generation_prompt=False
            )

            return {"text": text}

        dataset = dataset.map(format_example)

        def tokenize(example):
            result = tokenizer(
                example["text"],
                truncation=True,
                max_length=512,
                padding="max_length"
            )

            result["labels"] = [
                token if mask == 1 else -100
                for token, mask in zip(
                    result["input_ids"],
                    result["attention_mask"]
                )
            ]

            return result

        tokenized = dataset.map(
            tokenize,
            remove_columns=dataset.column_names
        )

        config = LoraConfig(
            task_type=TaskType.CAUSAL_LM,
            r=8,
            lora_alpha=16,
            lora_dropout=0.05,
            target_modules=[
                "q_proj",
                "k_proj",
                "v_proj",
                "o_proj"
            ]
        )

        model = get_peft_model(model, config)

        log("Starting LoRA training...")

        args = TrainingArguments(
            output_dir=str(OUTPUT_DIR / "lora"),
            num_train_epochs=3,
            per_device_train_batch_size=1,
            gradient_accumulation_steps=4,
            learning_rate=2e-4,
            logging_steps=1,
            save_strategy="epoch",
            report_to="none",
            fp16=torch.cuda.is_available()
        )

        trainer = Trainer(
            model=model,
            args=args,
            train_dataset=tokenized,
            data_collator=DataCollatorForLanguageModeling(
                tokenizer=tokenizer,
                mlm=False
            )
        )

        trainer.train()

        adapter_path = OUTPUT_DIR / "lora" / "final_adapter"
        adapter_path.mkdir(parents=True, exist_ok=True)

        model.save_pretrained(adapter_path)
        tokenizer.save_pretrained(adapter_path)

        log("LoRA adapter saved. Merging with base model...")

        from peft import PeftModel

        del trainer
        del model

        base = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL,
            torch_dtype=(
                torch.float16 if torch.cuda.is_available()
                else torch.float32
            ),
            device_map="auto" if torch.cuda.is_available() else None
        )

        adapted = PeftModel.from_pretrained(base, adapter_path)
        merged = adapted.merge_and_unload()

        if MERGED_DIR.exists():
            shutil.rmtree(MERGED_DIR)

        MERGED_DIR.mkdir(parents=True)

        merged.save_pretrained(
            MERGED_DIR,
            safe_serialization=True
        )

        tokenizer.save_pretrained(MERGED_DIR)

        log("Merged model saved.")
        log(f"Model location: {MERGED_DIR}")

        root.after(
            0,
            lambda: messagebox.showinfo(
                "Training complete",
                f"Model trained successfully.\n\n{MERGED_DIR}"
            )
        )

    except Exception as e:
        log(f"TRAINING ERROR: {e}")

        root.after(
            0,
            lambda: messagebox.showerror("Training failed", str(e))
        )


# ============================================================
# DEPLOY TO UNO Q
# ============================================================

def deploy_model():
    if not MERGED_DIR.exists():
        messagebox.showwarning(
            "No trained model",
            "Train the model before deploying."
        )
        return

    threading.Thread(
        target=deployment_worker,
        daemon=True
    ).start()


def deployment_worker():
    try:
        log("Creating remote model directory...")

        run_command(
            [
                "ssh",
                UNO_HOST,
                f"mkdir -p {REMOTE_DIR}/merged_model"
            ],
            "Preparing UNO Q..."
        )

        log("Transferring model to UNO Q...")

        run_command(
            [
                "scp",
                "-r",
                str(MERGED_DIR) + "/.",
                f"{UNO_HOST}:{REMOTE_DIR}/merged_model/"
            ],
            "Uploading trained model..."
        )

        log("Creating Ollama Modelfile...")

        modelfile = (
            f"FROM {REMOTE_DIR}/merged_model\n"
            "PARAMETER temperature 0.7\n"
            "PARAMETER num_ctx 2048\n"
        )

        local_modelfile = APP_DIR / "Modelfile"

        local_modelfile.write_text(
            modelfile,
            encoding="utf-8"
        )

        run_command(
            [
                "scp",
                str(local_modelfile),
                f"{UNO_HOST}:{REMOTE_DIR}/Modelfile"
            ],
            "Uploading Modelfile..."
        )

        run_command(
            [
                "ssh",
                UNO_HOST,
                f"ollama create {OLLAMA_MODEL} -f {REMOTE_DIR}/Modelfile"
            ],
            "Creating Ollama model..."
        )

        log("Deployment complete.")

        root.after(
            0,
            lambda: messagebox.showinfo(
                "Deployment complete",
                f"Created {OLLAMA_MODEL} on your UNO Q."
            )
        )

    except Exception as e:
        log(f"DEPLOYMENT ERROR: {e}")

        root.after(
            0,
            lambda: messagebox.showerror("Deployment failed", str(e))
        )


# ============================================================
# GUI
# ============================================================

root = tk.Tk()
root.title("CollAI Trainer")
root.geometry("1250x850")

root.columnconfigure(0, weight=1)
root.rowconfigure(1, weight=1)

top = ttk.Frame(root, padding=10)
top.grid(row=0, column=0, sticky="ew")

ttk.Button(
    top,
    text="Import from UNO Q",
    command=import_from_uno
).pack(side="left", padx=4)

ttk.Button(
    top,
    text="Import JSONL",
    command=import_local
).pack(side="left", padx=4)

ttk.Button(
    top,
    text="Export JSONL",
    command=export_records
).pack(side="left", padx=4)

count_label = ttk.Label(top, text="Conversations: 0")
count_label.pack(side="right", padx=8)

main = ttk.PanedWindow(
    root,
    orient=tk.HORIZONTAL
)
main.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)

left = ttk.Frame(main, padding=5)
right = ttk.Frame(main, padding=5)

main.add(left, weight=1)
main.add(right, weight=3)

ttk.Label(
    left,
    text="Conversations",
    font=("Segoe UI", 12, "bold")
).pack(anchor="w")

conversation_list = tk.Listbox(
    left,
    font=("Consolas", 9),
    width=45,
    selectmode=tk.SINGLE
)

conversation_list.pack(
    fill="both",
    expand=True,
    pady=5
)

conversation_list.bind(
    "<<ListboxSelect>>",
    select_conversation
)

ttk.Label(
    right,
    text="Conversation Editor",
    font=("Segoe UI", 12, "bold")
).pack(anchor="w")

ttk.Label(
    right,
    text=(
        "Edit the message text and headers below. "
        "Keep headers in the format shown."
    )
).pack(anchor="w", pady=3)

editor = tk.Text(
    right,
    wrap="word",
    font=("Consolas", 10),
    undo=True,
    height=25
)

editor.pack(
    fill="both",
    expand=True,
    pady=5
)

status_label = ttk.Label(
    right,
    text="Select a conversation"
)

status_label.pack(anchor="w")

edit_buttons = ttk.Frame(right)
edit_buttons.pack(fill="x", pady=5)

ttk.Button(
    edit_buttons,
    text="Save Edits",
    command=save_edit
).pack(side="left", padx=3)

ttk.Button(
    edit_buttons,
    text="Add Message",
    command=add_message
).pack(side="left", padx=3)

ttk.Button(
    edit_buttons,
    text="Delete Last Message",
    command=delete_last_message
).pack(side="left", padx=3)

ttk.Button(
    edit_buttons,
    text="Approve",
    command=approve
).pack(side="left", padx=3)

ttk.Button(
    edit_buttons,
    text="Exclude",
    command=exclude
).pack(side="left", padx=3)

bottom = ttk.Frame(root, padding=10)
bottom.grid(row=2, column=0, sticky="ew")

ttk.Button(
    bottom,
    text="TRAIN MODEL",
    command=train_model
).pack(side="left", padx=5)

ttk.Button(
    bottom,
    text="DEPLOY TO UNO Q",
    command=deploy_model
).pack(side="left", padx=5)

ttk.Label(
    bottom,
    text=f"Base: {BASE_MODEL} | Output: {OLLAMA_MODEL}"
).pack(side="right")

log_frame = ttk.LabelFrame(
    root,
    text="Activity Log",
    padding=5
)

log_frame.grid(
    row=3,
    column=0,
    sticky="ew",
    padx=10,
    pady=5
)

log_box = tk.Text(
    log_frame,
    height=7,
    wrap="word",
    font=("Consolas", 9)
)

log_box.pack(fill="both", expand=True)

log("CollAI Trainer ready.")
log(f"UNO Q target: {UNO_HOST}")
log(f"Workspace: {APP_DIR}")

root.mainloop()

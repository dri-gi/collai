import json
import os
import re
import shlex
import subprocess
import threading
import time
import urllib.request
import urllib.error
import uuid

from pathlib import Path
from datetime import datetime, timezone


# ============================================================
# CONFIGURATION
# ============================================================

MODEL = "collai:trained"
OLLAMA_URL = "http://localhost:11434/api/chat"

WHISPER_CLI = str(
    Path.home() / "whisper.cpp/build/bin/whisper-cli"
)
WHISPER_MODEL = str(
    Path.home() / "whisper.cpp/models/ggml-tiny.en.bin"
)

AUDIO_FILE = str(Path.home() / "billy_input.wav")
AUDIO_DEVICE = "plughw:0,0"

SPEAKER_URL = "http://172.20.10.8:8765"

SAVE_FILE = Path.home() / "conversations.jsonl"

# Arduino serial monitor command.
SENSOR_COMMAND = os.environ.get(
    "BILLY_SENSOR_COMMAND",
    "arduino-app-cli monitor"
)

# Keep only the most recent readings for Billy's context.
MAX_SENSOR_HISTORY = 10


SYSTEM_PROMPT = """
You are Billy, a friendly offline AI companion.

You are running locally and prioritize privacy.

You can receive heart-rate readings from a connected MAX30102
sensor through the HealthAssistant hardware.

When heart-rate data is provided:
- Use the latest available reading when answering questions.
- Distinguish current readings from older readings.
- Never invent missing sensor measurements.
- If no recent reading is available, say so.
- Explain measurements in plain, accessible language.
- Never claim that a heart-rate reading diagnoses a condition.
- Do not tell someone they are healthy or unhealthy based
  on a sensor reading alone.

You are conversational, curious, supportive, and concise.
"""


# ============================================================
# HEART RATE SENSOR
# ============================================================

class SensorReader:

    def __init__(self):
        self.process = None
        self.thread = None
        self.running = False

        self.lock = threading.Lock()
        self.readings = []

        self.pending_bpm = None
        self.pending_average = None

    def start(self):
        print("[HealthAssistant] Starting sensor monitor...")

        try:
            command = shlex.split(SENSOR_COMMAND)

            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            self.running = True

            self.thread = threading.Thread(
                target=self.read_serial,
                daemon=True
            )

            self.thread.start()

            print("[HealthAssistant] Sensor monitor connected.")

        except Exception as e:
            print("[HealthAssistant] Could not start monitor:", e)

    def read_serial(self):
        try:
            for line in self.process.stdout:
                if not self.running:
                    break

                self.parse_line(line.strip())

        except Exception as e:
            print("[HealthAssistant] Serial error:", e)

        finally:
            self.running = False

    def parse_line(self, line):
        if not line:
            return

        # ----------------------------------------------------
        # CURRENT HEALTHASSISTANT CSV FORMAT:
        # elapsed_s,ir_value,bpm,average_bpm
        # 38.19,96515,71.3,71
        # ----------------------------------------------------

        parts = line.strip().split(",")

        if len(parts) == 4:
            try:
                elapsed = float(parts[0])
                ir_value = int(float(parts[1]))
                bpm = float(parts[2])
                average = float(parts[3])

                # Never accept zero or invalid BPM values.
                if not (40 <= bpm <= 200):
                    return

                if not (40 <= average <= 200):
                    return

                if ir_value <= 10000:
                    return

                self.add_reading({
                    "timestamp": time.time(),
                    "elapsed": elapsed,
                    "ir": ir_value,
                    "bpm": round(bpm, 1),
                    "average_bpm": round(average, 1)
                })

                return

            except ValueError:
                # Ignore CSV headers and startup messages.
                pass

        # ----------------------------------------------------
        # BACKWARD COMPATIBILITY:
        # Supports older output such as:
        # BPM: 75
        # Average BPM: 74
        # ----------------------------------------------------

        bpm_match = re.search(
            r"\bBPM:\s*(\d+(?:\.\d+)?)",
            line,
            re.IGNORECASE
        )

        average_match = re.search(
            r"(?:Average|Avg)\s*BPM:\s*(\d+(?:\.\d+)?)",
            line,
            re.IGNORECASE
        )

        if average_match:
            self.pending_average = float(average_match.group(1))

        if bpm_match and not average_match:
            self.pending_bpm = float(bpm_match.group(1))

        if self.pending_bpm is not None and self.pending_average is not None:

            bpm = self.pending_bpm
            average = self.pending_average

            if 40 <= bpm <= 200 and 40 <= average <= 200:
                self.add_reading({
                    "timestamp": time.time(),
                    "elapsed": None,
                    "ir": None,
                    "bpm": round(bpm, 1),
                    "average_bpm": round(average, 1)
                })

            self.pending_bpm = None
            self.pending_average = None

    def add_reading(self, reading):
        with self.lock:
            self.readings.append(reading)

            if len(self.readings) > 100:
                self.readings = self.readings[-100:]

    def get_latest(self):
        with self.lock:
            if not self.readings:
                return None

            return dict(self.readings[-1])

    def get_recent(self):
        with self.lock:
            return [
                dict(r)
                for r in self.readings[-MAX_SENSOR_HISTORY:]
            ]

    def get_context(self):
        latest = self.get_latest()

        if latest is None:
            return (
                "HEART RATE SENSOR:\n"
                "No valid heart-rate readings have been received yet."
            )

        age = time.time() - latest["timestamp"]

        if age > 20:
            return (
                "HEART RATE SENSOR:\n"
                "The last valid reading is stale. "
                "Do not describe it as the current heart rate."
            )

        recent = self.get_recent()

        readings_text = "\n".join(
            f"BPM: {r['bpm']}, Average BPM: {r['average_bpm']}"
            for r in recent
        )

        return f"""
HEART RATE SENSOR DATA

Latest valid reading:
BPM: {latest['bpm']}
Average BPM: {latest['average_bpm']}
Seconds since reading: {age:.1f}

Recent readings:
{readings_text}

Only use these actual readings. Do not invent measurements.
"""

    def get_history(self):
        return self.get_recent()

    def stop(self):
        self.running = False

        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                self.process.kill()


# ============================================================
# MICROPHONE / OFFLINE WHISPER
# ============================================================

def record_audio():

    print("\nRecording for 5 seconds...")

    try:
        subprocess.run(
            [
                "arecord",
                "-q",
                "-D", AUDIO_DEVICE,
                "-f", "S16_LE",
                "-r", "16000",
                "-c", "1",
                "-d", "5",
                AUDIO_FILE
            ],
            check=True
        )

        return True

    except Exception as e:
        print("Microphone recording failed:", e)
        return False


def transcribe_audio():

    if not record_audio():
        return ""

    print("Transcribing offline...")

    try:
        result = subprocess.run(
            [
                WHISPER_CLI,
                "-m", WHISPER_MODEL,
                "-f", AUDIO_FILE,
                "-nt",
                "-np",
                "-t", "2"
            ],
            capture_output=True,
            text=True,
            timeout=120
        )

        transcript = result.stdout.strip()

        if not transcript:
            transcript = result.stderr.strip()

        return transcript.strip()

    except Exception as e:
        print("Whisper error:", e)
        return ""


# ============================================================
# BILLY SPEAKER
# ============================================================

def speak_billy(text):

    try:
        payload = json.dumps({
            "text": text
        }).encode("utf-8")

        request = urllib.request.Request(
            SPEAKER_URL,
            data=payload,
            headers={
                "Content-Type": "application/json"
            },
            method="POST"
        )

        urllib.request.urlopen(
            request,
            timeout=15
        )

    except Exception as e:
        print("[Speaker] Could not send audio:", e)


# ============================================================
# OLLAMA CHAT
# ============================================================

def ask_billy(messages):

    payload = json.dumps({
        "model": MODEL,
        "messages": messages,
        "stream": False
    }).encode("utf-8")

    request = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=180
        ) as response:

            result = json.loads(
                response.read().decode("utf-8")
            )

            return result["message"]["content"].strip()

    except Exception as e:
        print("[Ollama] Error:", e)
        return "I'm having trouble thinking right now."


# ============================================================
# CONVERSATION SAVING
# ============================================================

def save_conversation(messages, sensor):

    record = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(
            timezone.utc
        ).isoformat(),

        "model": MODEL,

        "messages": [
            m for m in messages
            if m["role"] in ("user", "assistant")
        ],

        "heart_rate_readings": sensor.get_history()
    }

    try:
        with open(SAVE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

        print("[Billy] Conversation saved.")

    except Exception as e:
        print("[Billy] Save failed:", e)


# ============================================================
# MAIN PROGRAM
# ============================================================

def main():

    sensor = SensorReader()
    sensor.start()

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]

    saved = False

    print("\n===================================")
    print("       BILLY + HEALTH ASSISTANT")
    print("===================================")
    print("Model:", MODEL)
    print("Heart sensor: Active monitor")
    print("Enter text to chat.")
    print("Press Enter without typing to speak.")
    print("")
    print("Commands:")
    print("/heart  - Show latest heart-rate reading")
    print("/save   - Save conversation")
    print("/clear  - Clear conversation")
    print("/help   - Show commands")
    print("/quit   - Exit")
    print("===================================\n")

    try:

        while True:

            try:
                user_text = input("You: ").strip()

            except EOFError:
                break

            # ------------------------------------------------
            # COMMANDS
            # ------------------------------------------------

            if user_text.lower() == "/quit":
                break

            if user_text.lower() == "/help":
                print("""
Commands:
/heart  - Show latest heart-rate reading
/save   - Save conversation
/clear  - Clear conversation
/help   - Show commands
/quit   - Exit

Press Enter without typing to record a voice message.
""")
                continue

            if user_text.lower() == "/save":
                save_conversation(messages, sensor)
                saved = True
                continue

            if user_text.lower() == "/clear":
                messages = [
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT
                    }
                ]

                print("[Billy] Conversation cleared.")
                continue

            if user_text.lower() == "/heart":

                latest = sensor.get_latest()

                if latest is None:
                    print("[HealthAssistant] No valid readings yet.")

                else:
                    age = time.time() - latest["timestamp"]

                    if age > 20:
                        print("[HealthAssistant] Last reading is stale.")

                    print(
                        f"BPM: {latest['bpm']} | "
                        f"Average BPM: {latest['average_bpm']} | "
                        f"Age: {age:.1f}s"
                    )

                continue

            # ------------------------------------------------
            # VOICE INPUT
            # ------------------------------------------------

            if not user_text:
                user_text = transcribe_audio()

                if not user_text:
                    print("[Billy] I didn't catch that.")
                    continue

                print("You (voice):", user_text)

            # ------------------------------------------------
            # ATTACH SENSOR CONTEXT
            # ------------------------------------------------

            sensor_context = sensor.get_context()

            complete_prompt = f"""
{sensor_context}

USER MESSAGE:
{user_text}
"""

            messages.append({
                "role": "user",
                "content": complete_prompt
            })

            # ------------------------------------------------
            # ASK BILLY
            # ------------------------------------------------

            response = ask_billy(messages)

            messages.append({
                "role": "assistant",
                "content": response
            })

            print("\nBilly:", response, "\n")

            # ------------------------------------------------
            # SPEAK RESPONSE
            # ------------------------------------------------

            speak_billy(response)

    except KeyboardInterrupt:
        print("\n[Billy] Interrupted.")

    finally:

        sensor.stop()

        print("[Billy] Sensor monitor stopped.")

        if len(messages) > 1:
                save_conversation(messages, sensor)
                print("[Billy] Conversation automatically saved.")


if __name__ == "__main__":
    main()

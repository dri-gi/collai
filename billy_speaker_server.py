
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from queue import Queue
from threading import Thread
import json
import pythoncom
import pyttsx3
import time

speech_queue = Queue()

def speech_worker():
    pythoncom.CoInitialize()
    print("Billy TTS worker ready!")

    while True:
        message = speech_queue.get()

        try:
            print("Billy speaking:", message)

            # Create a fresh speech engine for each message
            engine = pyttsx3.init('sapi5')
            engine.setProperty("rate", 175)
            engine.setProperty("volume", 1.0)

            engine.say(message)
            engine.runAndWait()
            engine.stop()

            print("Speech completed!")

            del engine
            time.sleep(0.2)

        except Exception as e:
            print("Speech error:", repr(e))

        finally:
            speech_queue.task_done()

    pythoncom.CoUninitialize()


class BillyHandler(BaseHTTPRequestHandler):

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length))

            message = str(data.get("text", "")).strip()[:2000]

            if not message:
                self.send_error(400, "No text provided")
                return

            print("Billy received:", message)

            speech_queue.put(message)

            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Queued for speech")

        except Exception as e:
            print("Request error:", repr(e))
            self.send_error(500, str(e))


if __name__ == "__main__":

    worker = Thread(target=speech_worker, daemon=True)
    worker.start()

    server = ThreadingHTTPServer(("0.0.0.0", 8765), BillyHandler)

    print("Billy speaker server running on port 8765")
    print("Waiting for Billy to speak...")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBilly speaker server shutting down.")
        server.shutdown()
        server.server_close()

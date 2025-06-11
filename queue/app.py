# queue/app.py

from flask import Flask, request, jsonify, abort
import threading, time, os, requests
from collections import deque
from shard import ConsistentHash

app = Flask(__name__)

# ─── Configuration ─────────────────────────────────────────────────────────
MAX_QUEUE_SIZE = int(os.getenv("MAX_QUEUE_SIZE", "100"))
print("MAX_QUEUE_SIZE:", MAX_QUEUE_SIZE)
WORKER_COUNT  = int(os.getenv("WORKER_COUNT",     "1"))
print("WORKER_COUNT:", WORKER_COUNT)
QUEUE_PORT    = int(os.getenv("QUEUE_PORT",      "7000"))
STORE_NODES   = os.getenv("STORE_NODES",         "").split(",")

# Build the consistent-hash ring over all primaries
ring = ConsistentHash(STORE_NODES)

# Thread-safe in-memory queue
QUEUE = deque(maxlen=MAX_QUEUE_SIZE)
LOCK  = threading.Lock()

@app.route("/enqueue", methods=["POST"])
def enqueue():
    job = request.get_json()
    if not job or "action" not in job or "key" not in job:
        abort(400, description="Must provide JSON with 'action' and 'key'")
    with LOCK:
        if len(QUEUE) >= QUEUE.maxlen:
            abort(429, description="Queue is full")
        QUEUE.append(job)
    return jsonify({"status": "enqueued"}), 202

def worker():
    while True:
        job = None
        with LOCK:
            if QUEUE:
                job = QUEUE.popleft()

        if not job:
            time.sleep(0.1)
            continue

        action = job["action"]
        key    = job["key"]
        if action != "increment":
            print(f"[worker] unknown action: {action}")
            continue

        node = ring.get_node(key)
        print(f"[worker] routing key={key} → node={node}")
        store_url = f"{node}/store/{key}"

        # Fetch current
        try:
            resp = requests.get(store_url)
            if resp.status_code == 404:
                current = 0
            else:
                resp.raise_for_status()
                current = int(resp.json().get("value", 0))
        except Exception as e:
            print(f"[worker] fetch error ({key}@{node}): {e}")
            continue

        # Increment and persist
        new_value = current + 1
        try:
            post = requests.post(store_url, json={"value": new_value})
            post.raise_for_status()
        except Exception as e:
            print(f"[worker] persist error ({key}@{node}): {e}")

if __name__ == "__main__":
    # Start WORKER_COUNT background threads
    for _ in range(WORKER_COUNT):
        threading.Thread(target=worker, daemon=True).start()

    app.run(host="0.0.0.0", port=QUEUE_PORT)

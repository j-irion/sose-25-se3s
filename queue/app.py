# queue/app.py

from flask import Flask, request, jsonify, abort
import threading, time, os, requests
from shard import ConsistentHash
from collections import defaultdict, deque

app = Flask(__name__)

# ─── Configuration ─────────────────────────────────────────────────────────

# limits for spillover queues
MAX_KEY_RATE = int(os.getenv("MAX_KEY_RATE", "50"))  # per-10-seconds key limit
STALE_THRESHOLD_SEC = int(os.getenv("STALE_THRESHOLD_SEC", "5"))  # age in seconds before sidelining
SPILLOVER_QUEUE_SIZE= int(os.getenv("SPILLOVER_QUEUE_SIZE", "100"))

# limits for main queue system
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

# spillover queues as mitigation strategy
EXCESS_QUEUE = deque(maxlen=SPILLOVER_QUEUE_SIZE)
STALE_QUEUE = deque(maxlen=SPILLOVER_QUEUE_SIZE)

KEY_TIMESTAMPS = defaultdict(list)  # For per-key rate limiting


@app.route("/enqueue", methods=["POST"])
def enqueue():
    job = request.get_json()
    if not job or "action" not in job or "key" not in job:
        abort(400, description="Must provide JSON with 'action' and 'key'")

    job["timestamp"] = time.time()

    key = job["key"]
    now = time.time()
    timestamps = KEY_TIMESTAMPS[key]

    # Clean old timestamps (older than 10s)
    KEY_TIMESTAMPS[key] = [t for t in timestamps if now - t < 10]

    if len(KEY_TIMESTAMPS[key]) >= MAX_KEY_RATE:
        with LOCK:
            if len(EXCESS_QUEUE) >= EXCESS_QUEUE.maxlen:
                abort(429, description="Excess queue is full")
            EXCESS_QUEUE.append(job)
            print(f"[enqueue] {key} → spillover:EXCESS_QUEUE (rate limit)")
            return jsonify({"status": "sidelined:rate"}), 200

    with LOCK:
        if len(QUEUE) >= QUEUE.maxlen:
            abort(429, description="Queue is full")
        QUEUE.append(job)
        KEY_TIMESTAMPS[key].append(now)

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

        # Age-based sidelining
        age = time.time() - job.get("timestamp", time.time())
        if age > STALE_THRESHOLD_SEC:
            with LOCK:
                if len(STALE_QUEUE) >= STALE_QUEUE.maxlen:
                    abort(429, description="Stale queue is full")
                STALE_QUEUE.append(job)
                print(f"[worker] sidelined key={job['key']} to STALE_QUEUE (age {age:.2f}s)")
                continue

        process_job(job)


def process_job(job):
    action = job["action"]
    key = job["key"]
    if action != "increment":
        print(f"[worker] unknown action: {action}")
        return

    node = ring.get_node(key)
    print(f"[worker] routing key={key} → node={node}")
    store_url = f"{node}/store/{key}"

    try:
        resp = requests.get(store_url)
        current = 0 if resp.status_code == 404 else int(resp.json().get("value", 0))
    except Exception as e:
        print(f"[worker] fetch error ({key}@{node}): {e}")
        return

    new_value = current + 1
    try:
        post = requests.post(store_url, json={"value": new_value})
        post.raise_for_status()
    except Exception as e:
        print(f"[worker] persist error ({key}@{node}): {e}")

def spillover_worker(queue_name, spillover_queue):
    while True:
        with LOCK:
            if len(QUEUE) < MAX_QUEUE_SIZE and spillover_queue:
                job = spillover_queue.popleft()
                print(f"[spillover_worker] retrying {job['key']} from {queue_name}")
                QUEUE.append(job)
        time.sleep(0.05)


if __name__ == "__main__":
    # Start WORKER_COUNT background threads
    for _ in range(WORKER_COUNT):
        threading.Thread(target=worker, daemon=True).start()

    threading.Thread(target=spillover_worker, args=("EXCESS_QUEUE", EXCESS_QUEUE), daemon=True).start()
    threading.Thread(target=spillover_worker, args=("STALE_QUEUE", STALE_QUEUE), daemon=True).start()

    app.run(host="0.0.0.0", port=QUEUE_PORT)

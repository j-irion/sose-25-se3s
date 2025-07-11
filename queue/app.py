import logging
import os
import requests
import threading
import time
from collections import defaultdict, deque

from flask import Flask, request, jsonify, abort

from shard import ConsistentHash

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

MAX_KEY_RATE = int(os.getenv("MAX_KEY_RATE", "50"))  # per-10-seconds key limit
STALE_THRESHOLD_SEC = int(os.getenv("STALE_THRESHOLD_SEC", "5"))  # age in seconds before sidelining
SPILLOVER_QUEUE_SIZE= int(os.getenv("SPILLOVER_QUEUE_SIZE", "100"))

MAX_QUEUE_SIZE = int(os.getenv("MAX_QUEUE_SIZE", "100"))
logging.log(logging.INFO, f"MAX_QUEUE_SIZE: {MAX_QUEUE_SIZE}")
WORKER_COUNT  = int(os.getenv("WORKER_COUNT",     "1"))
logging.log(logging.INFO, f"WORKER_COUNT: {WORKER_COUNT}")
QUEUE_PORT    = int(os.getenv("QUEUE_PORT",      "7000"))
STORE_NODES   = os.getenv("STORE_NODES",         "").split(",")
MAX_STALE_RETRIES = int(os.getenv("MAX_STALE_RETRIES", "3"))

ring = ConsistentHash(STORE_NODES)

QUEUE = deque(maxlen=MAX_QUEUE_SIZE)
LOCK  = threading.Lock()

EXCESS_QUEUE = deque(maxlen=SPILLOVER_QUEUE_SIZE)
STALE_QUEUE = deque(maxlen=SPILLOVER_QUEUE_SIZE)

KEY_TIMESTAMPS = defaultdict(list)  # For per-key rate limiting


@app.route("/enqueue", methods=["POST"])
def enqueue():
    """
    Handle POST requests to enqueue a job.

    A job must contain a 'key' and an 'action'. This endpoint handles:
    - Rate limiting per key over a 10-second sliding window.
    - Adding jobs to the main queue or, if over the rate limit, to the excess queue.
    - Rejecting requests if both the main and excess queues are full.

    Returns:
        Response: JSON indicating the result ("enqueued" or "sidelined:rate").
    Raises:
        400: If required fields are missing.
        429: If the queue or excess queue is full.
    """
    job = request.get_json()
    if not job or "action" not in job or "key" not in job:
        abort(400, description="Must provide JSON with 'action' and 'key'")

    job["timestamp"] = time.time()

    key = job["key"]
    now = time.time()

    KEY_TIMESTAMPS[key] = [t for t in KEY_TIMESTAMPS[key] if now - t < 10]
    KEY_TIMESTAMPS[key].append(now)
    timestamps = KEY_TIMESTAMPS[key]

    if len(timestamps) > MAX_KEY_RATE:
        with LOCK:
            if len(EXCESS_QUEUE) >= EXCESS_QUEUE.maxlen:
                abort(429, description="Excess queue is full")
            EXCESS_QUEUE.append(job)
            logging.warning(f"[enqueue] sidelined {key} to EXCESS_QUEUE (rate limit of {MAX_KEY_RATE} requests per key reached)")
            return jsonify({"status": "sidelined:rate"}), 202

    with LOCK:
        if len(QUEUE) >= QUEUE.maxlen:
            abort(429, description="Queue is full")
        QUEUE.append(job)

    return jsonify({"status": "enqueued"}), 202


def worker():
    """
    Background worker thread that processes jobs from the main queue.

    - Skips jobs that are too old and moves them to the stale queue.
    - For valid jobs, routes them to the appropriate storage node using consistent hashing.
    """
    while True:
        job = None
        with LOCK:
            if QUEUE:
                job = QUEUE.popleft()

        if not job:
            time.sleep(0.05)
            continue

        age = time.time() - job.get("timestamp", time.time())
        if age > STALE_THRESHOLD_SEC:
            with LOCK:
                if len(STALE_QUEUE) >= STALE_QUEUE.maxlen:
                    abort(429, description="Stale queue is full")
                STALE_QUEUE.append(job)
                logging.warning(f"[worker] sidelined key={job['key']} to STALE_QUEUE (age {age:.2f}s)")
                continue
        else:
            process_job(job)


def process_job(job):
    """
    Process a single job by incrementing its value in the appropriate store node.

    Args:
        job (dict): The job to process. Must include 'key' and 'action'.

    Logs errors if the storage request fails or the action is unsupported.
    """
    action = job["action"]
    key = job["key"]
    if action != "increment":
        logging.exception(msg=f"[worker] unknown action: {action}")
        return

    node = ring.get_node(key)
    logging.log(logging.INFO, f"[worker] routing key={key} → node={node}")
    store_url = f"{node}/store/{key}/increment"

    try:
        post = requests.post(store_url)
        post.raise_for_status()
    except Exception as e:
        logging.exception(f"[worker] increment error ({key}@{node}): {e}")

def excess_worker():
    """
    Background thread that retries jobs from the excess queue.

    - Moves jobs from the excess queue to the main queue when there's capacity.
    - Prevents loss of jobs that were sidelined due to per-key rate limits.
    """
    while True:
        with LOCK:
            if len(QUEUE) < MAX_QUEUE_SIZE and EXCESS_QUEUE:
                job = EXCESS_QUEUE.popleft()
                logging.log(logging.INFO, f"[excess worker] retrying {job['key']}")
                QUEUE.append(job)
        time.sleep(0.05)


def stale_worker():
    """
    Background thread that retries stale jobs.

    - Retries jobs in the stale queue up to MAX_STALE_RETRIES.
    - Drops jobs that exceed the retry limit.
    - Adds delay (backoff) to reduce system pressure.
    """
    while True:
        job = None
        with LOCK:
            if STALE_QUEUE:
                job = STALE_QUEUE.popleft()

        if not job:
            time.sleep(0.1)
            continue

        job["retries"] = job.get("retries", 0) + 1
        if job["retries"] > MAX_STALE_RETRIES:
            logging.warning(f"Dropping stale job key={job['key']} after {job['retries']} retries")
            continue

        time.sleep(0.2)

        process_job(job)

if __name__ == "__main__":
    for _ in range(WORKER_COUNT):
        threading.Thread(target=worker, daemon=True).start()

    threading.Thread(target=excess_worker, daemon=True).start()
    threading.Thread(target=stale_worker, daemon=True).start()

    app.run(host="0.0.0.0", port=QUEUE_PORT)

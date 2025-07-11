# api/app.py

from flask import Flask, jsonify, abort
import requests
import os
from shard import ConsistentHash

app = Flask(__name__)

# ─── Configuration ─────────────────────────────────────────────────────────
STORE_NODES      = [n for n in os.getenv("STORE_NODES", "").split(",") if n]
SECONDARY_NODES  = [n for n in os.getenv("STORE_SECONDARIES", "").split(",") if n]
QUEUE_URL        = os.getenv("QUEUE_URL",   "http://queue:7000/enqueue")

# Build the consistent-hash ring for sharding
ring = ConsistentHash(STORE_NODES)

# ─── Health Check ──────────────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    """
    Health check endpoint.

    Returns:
        JSON: {"status": "api up"} with 200 OK.
    """
    return jsonify({"status": "api up"}), 200

# ─── Read Endpoint ─────────────────────────────────────────────────────────
@app.route("/counter/<key>", methods=["GET"])
def get_counter(key):
    """
    Fetch the counter value for a given key.

    Uses consistent hashing to route to the correct store node.
    Falls back to a secondary node if the primary is unreachable.

    Args:
        key (str): The key to look up.

    Returns:
        JSON: {"key": key, "value": value} with 200 OK.
    Raises:
        503: If the primary and secondary nodes are both unreachable.
    """
    node = ring.get_node(key)
    idx = STORE_NODES.index(node) if node in STORE_NODES else -1
    secondary = SECONDARY_NODES[idx] if idx >= 0 and idx < len(SECONDARY_NODES) else None
    try:
        resp = requests.get(f"{node}/store/{key}")
    except requests.exceptions.ConnectionError:
        if secondary:
            resp = requests.get(f"{secondary}/store/{key}")
        else:
            abort(503, description="Primary unreachable")
    if resp.status_code == 404:
        return jsonify({"key": key, "value": 0}), 200
    resp.raise_for_status()
    return jsonify(resp.json()), 200

# ─── Write Endpoint (enqueue) ──────────────────────────────────────────────
@app.route("/counter/<key>/increment", methods=["POST"])
def increment_counter(key):
    """
    Enqueue a request to increment the counter for a given key.

    Sends a job to the queueing service for asynchronous processing.

    Args:
        key (str): The key to increment.

    Returns:
        JSON: {"status": "queued", "key": key} with 202 Accepted.
    Raises:
        429: If the queue system is full or rate-limited.
    """
    # send job {action, key} to the queue
    resp = requests.post(QUEUE_URL, json={"action": "increment", "key": key})
    if resp.status_code == 429:
        abort(429, description="Too many requests – queue is full")
    resp.raise_for_status()
    return jsonify({"status": "queued", "key": key}), 202

# ─── Launch ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Bind explicitly to 8000 so Docker mapping works correctly
    app.run(host="0.0.0.0", port=8000)

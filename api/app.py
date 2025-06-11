# api/app.py

from flask import Flask, jsonify, abort
import requests
import os
from shard import ConsistentHash

app = Flask(__name__)

# ─── Configuration ─────────────────────────────────────────────────────────
STORE_NODES = os.getenv("STORE_NODES", "").split(",")
QUEUE_URL   = os.getenv("QUEUE_URL",   "http://queue:7000/enqueue")

# Build the consistent-hash ring for sharding
ring = ConsistentHash(STORE_NODES)

# ─── Health Check ──────────────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "api up"}), 200

# ─── Read Endpoint ─────────────────────────────────────────────────────────
@app.route("/counter/<key>", methods=["GET"])
def get_counter(key):
    node = ring.get_node(key)
    resp = requests.get(f"{node}/store/{key}")
    if resp.status_code == 404:
        return jsonify({"key": key, "value": 0}), 200
    resp.raise_for_status()
    return jsonify(resp.json()), 200

# ─── Write Endpoint (enqueue) ──────────────────────────────────────────────
@app.route("/counter/<key>/increment", methods=["POST"])
def increment_counter(key):
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

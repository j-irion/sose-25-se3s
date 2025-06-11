# api/app.py
from flask import Flask, jsonify, abort
import os, requests
from shard import ConsistentHash

app = Flask(__name__)
QUEUE_URL = "http://queue:7000/enqueue"

# Configure via env var, comma-separated:
nodes = os.getenv("STORE_NODES", "http://store1:9000,http://store2:9000").split(",")
ring = ConsistentHash(nodes)

@app.route("/counter", methods=["GET"])
def get_counter():
    node = ring.get_node("counter")
    resp = requests.get(f"{node}/store/counter")
    if resp.status_code == 404:
        return jsonify({"value": 0}), 200
    resp.raise_for_status()
    return jsonify(resp.json()), 200

@app.route("/counter/increment", methods=["POST"])
def increment_counter():
    resp = requests.post(QUEUE_URL, json={"action": "increment"})
    if resp.status_code == 429:
        abort(429, "Too many requests – queue is full")
    resp.raise_for_status()
    return jsonify({"status": "queued"}), 202

@app.route("/health", methods=["GET"])
def health():
    return {"status": "api up"}, 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)

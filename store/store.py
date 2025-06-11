# store/store.py
from flask import Flask, request, jsonify, abort
import os

LOG_PATH = "log.txt"

class SimpleStore:
    def __init__(self, log_path=LOG_PATH):
        self.data = {}
        self.log_path = log_path
        # ensure log exists
        open(self.log_path, "a").close()
        self._replay_log()

    def _replay_log(self):
        with open(self.log_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                key, val = line.split(":", 1)
                if val == "__deleted__":
                    self.data.pop(key, None)
                else:
                    self.data[key] = val

    def append(self, key, value):
        self.data[key] = value
        with open(self.log_path, "a") as f:
            f.write(f"{key}:{value}\n")

    def delete(self, key):
        existed = key in self.data
        self.data.pop(key, None)
        with open(self.log_path, "a") as f:
            f.write(f"{key}:__deleted__\n")
        return existed

store = SimpleStore()
app = Flask(__name__)

@app.route("/store/<key>", methods=["POST"])
def write_key(key):
    body = request.get_json()
    if body is None or "value" not in body:
        abort(400, "JSON must include a ‘value’ field")
    val = str(body["value"])
    store.append(key, val)
    return jsonify({"key": key, "value": val}), 201

@app.route("/store/<key>", methods=["GET"])
def read_key(key):
    if key not in store.data:
        abort(404)
    return jsonify({"key": key, "value": store.data[key]}), 200

@app.route("/store/<key>", methods=["DELETE"])
def delete_key(key):
    existed = store.delete(key)
    if not existed:
        abort(404)
    return "", 204

if __name__ == "__main__":
    # listen on all interfaces for Docker
    app.run(host="0.0.0.0", port=9000)

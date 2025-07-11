# store/store.py

from flask import Flask, request, jsonify, abort
import os
import threading
import requests
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Configuration via environment variables
LOG_PATH        = os.getenv("LOG_PATH", "log.txt")
SECONDARIES_RAW = os.getenv("SECONDARIES", "")
SECONDARIES    = [url for url in SECONDARIES_RAW.split(",") if url]
STORE_PORT      = int(os.getenv("STORE_PORT", "9000"))
PRIMARY_URL = os.getenv("PRIMARY_URL")

# Thread‐safety lock for store operations
STORE_LOCK = threading.Lock()

class SimpleStore:
    def __init__(self, log_path):
        self.data = {}
        self.log_path = log_path
        # ensure log file exists
        open(self.log_path, "a").close()
        # replay any existing entries to rebuild in-memory state
        self._replay_log()

        if PRIMARY_URL:
            threading.Thread(target=self._reconcile_loop, daemon=True).start()

    def _reconcile_loop(self):
        import time
        while True:
            time.sleep(10)
            if not PRIMARY_URL:
                continue

            for key in list(self.data.keys()):
                try:
                    resp = requests.get(f"{PRIMARY_URL}/store/{key}", timeout=1)
                    if resp.status_code != 200:
                        logging.log(logging.INFO, f"[RECONCILE] Skipping key={key} (primary gave status {resp.status_code})")
                        continue
                    primary_val = resp.json().get("value")
                    with STORE_LOCK:
                        local_val = self.data.get(key)
                        if int(primary_val) > int(local_val):
                            logging.log(logging.INFO,f"[RECONCILE] Updating key={key} from {local_val} → {primary_val}")
                            self.data[key] = primary_val
                            with open(self.log_path, "a") as f:
                                f.write(f"{key}:{primary_val}\n")
                except Exception as e:
                    logging.log(logging.INFO,f"[RECONCILE] Could not contact primary for key={key}: {e}")
                    continue

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
        with STORE_LOCK:
            # update in-memory
            self.data[key] = value
            # append to disk log
            with open(self.log_path, "a") as f:
                f.write(f"{key}:{value}\n")
        # trigger async replication
        threading.Thread(target=self._replicate, args=(key, value), daemon=True).start()

    def increment(self, key, delta=1):
        """Atomically increment a key by ``delta``."""
        with STORE_LOCK:
            current = int(self.data.get(key, "0"))
            new_value = current + delta
            self.data[key] = str(new_value)
            with open(self.log_path, "a") as f:
                f.write(f"{key}:{self.data[key]}\n")
        threading.Thread(target=self._replicate, args=(key, self.data[key]), daemon=True).start()
        return new_value

    def delete(self, key):
        with STORE_LOCK:
            existed = key in self.data
            self.data.pop(key, None)
            with open(self.log_path, "a") as f:
                f.write(f"{key}:__deleted__\n")
        # replicate deletion
        threading.Thread(target=self._replicate, args=(key, "__deleted__"), daemon=True).start()
        return existed

    def _replicate(self, key, value):
        """POST the same change to each secondary, fire-and-forget."""
        for secondary in SECONDARIES:
            try:
                requests.post(
                    f"{secondary}/store/{key}",
                    json={"value": value},
                    timeout=1
                )
            except Exception:
                # ignore failures; secondary will catch up from its own log if needed
                pass

# initialize
store = SimpleStore(LOG_PATH)
app   = Flask(__name__)

@app.route("/store/<key>", methods=["POST"])
def write_key(key):
    body = request.get_json()
    if not body or "value" not in body:
        abort(400, description="Request JSON must include a 'value' field")
    val = str(body["value"])
    store.append(key, val)
    return jsonify({"key": key, "value": val}), 201

@app.route("/store/<key>/increment", methods=["POST"])
def increment_key(key):
    new_val = store.increment(key)
    return jsonify({"key": key, "value": str(new_val)}), 201

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
    app.run(host="0.0.0.0", port=STORE_PORT)

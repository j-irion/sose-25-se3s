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

LOG_PATH        = os.getenv("LOG_PATH", "log.txt")
SECONDARIES_RAW = os.getenv("SECONDARIES", "")
SECONDARIES    = [url for url in SECONDARIES_RAW.split(",") if url]
STORE_PORT      = int(os.getenv("STORE_PORT", "9000"))
PRIMARY_URL = os.getenv("PRIMARY_URL")

STORE_LOCK = threading.Lock()

class SimpleStore:
    """
    A simple, thread-safe key-value store with write-ahead logging and async primary-copy replication.

    Attributes:
        data (dict): In-memory key-value data store.
        log_path (str): Path to the persistent log file.
    """

    def __init__(self, log_path):
        """
        Initialize the store and replay the log file to rebuild state.

        Args:
            log_path (str): Path to the persistent log file.
        """
        self.data = {}
        self.log_path = log_path
        open(self.log_path, "a").close()
        self._replay_log()

        if PRIMARY_URL:
            threading.Thread(target=self._reconcile_loop, daemon=True).start()

    def _reconcile_loop(self):
        """
        Periodically reconcile the local store with the primary store.

        This method runs in an infinite loop, checking every 10 seconds if the primary
        store is available. For each key in the local store, it attempts to fetch the
        corresponding value from the primary store. If the value in the primary store
        is greater than the local value, the local store is updated to match the primary.

        The reconciliation process ensures eventual consistency between the local store
        and the primary store.

        Raises:
            Exception: Logs any exceptions encountered while contacting the primary store.
        """
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
        """
        Reconstruct the in-memory store by replaying the write-ahead log.
        """
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
        """
        Append a key-value pair to the store and log file.

        Args:
            key (str): The key to write.
            value (str): The value to associate with the key.
        """
        with STORE_LOCK:
            self.data[key] = value
            with open(self.log_path, "a") as f:
                f.write(f"{key}:{value}\n")
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
        """
        Delete a key from the store and log the deletion.

        Args:
            key (str): The key to delete.

        Returns:
            bool: True if the key existed, False otherwise.
        """
        with STORE_LOCK:
            existed = key in self.data
            self.data.pop(key, None)
            with open(self.log_path, "a") as f:
                f.write(f"{key}:__deleted__\n")
        threading.Thread(target=self._replicate, args=(key, "__deleted__"), daemon=True).start()
        return existed

    def _replicate(self, key, value):
        """
        Fire-and-forget replication to all configured secondaries.

        Args:
            key (str): The key to replicate.
            value (str): The value to replicate (or "__deleted__").
        """
        for secondary in SECONDARIES:
            try:
                requests.post(
                    f"{secondary}/store/{key}",
                    json={"value": value},
                    timeout=1
                )
            except Exception:
                pass

store = SimpleStore(LOG_PATH)
app   = Flask(__name__)

@app.route("/store/<key>", methods=["POST"])
def write_key(key):
    """
    Write or update the value of a given key.

    Request Body:
        JSON: {"value": <value>}

    Returns:
        JSON: {"key": <key>, "value": <value>} with 201 Created.

    Raises:
        400: If 'value' is missing from request.
    """
    body = request.get_json()
    if not body or "value" not in body:
        abort(400, description="Request JSON must include a 'value' field")
    val = str(body["value"])
    store.append(key, val)
    return jsonify({"key": key, "value": val}), 201

@app.route("/store/<key>/increment", methods=["POST"])
def increment_key(key):
    """
    Increment the value of a given key in the store.

    Args:
        key (str): The key whose value should be incremented.

    Returns:
        Response: A JSON object containing the key and its new value with a 201 Created status.
        Example: {"key": "example_key", "value": "new_value"}
    """
    new_val = store.increment(key)
    return jsonify({"key": key, "value": str(new_val)}), 201

@app.route("/store/<key>", methods=["GET"])
def read_key(key):
    """
    Retrieve the current value of a given key.

    Args:
        key (str): The key to retrieve.

    Returns:
        JSON: {"key": <key>, "value": <value>} with 200 OK.

    Raises:
        404: If the key is not found.
    """
    if key not in store.data:
        abort(404)
    return jsonify({"key": key, "value": store.data[key]}), 200

@app.route("/store/<key>", methods=["DELETE"])
def delete_key(key):
    """
    Delete a given key from the store.

    Args:
        key (str): The key to delete.

    Returns:
        Empty response with 204 No Content.

    Raises:
        404: If the key does not exist.
    """
    existed = store.delete(key)
    if not existed:
        abort(404)
    return "", 204

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=STORE_PORT)

# api/app.py
from flask import Flask, jsonify
import requests

STORE_URL = "http://store:9000/store/counter"
app = Flask(__name__)

@app.route("/counter", methods=["GET"])
def get_counter():
    resp = requests.get(STORE_URL)
    if resp.status_code == 404:
        return jsonify({"value": 0}), 200
    resp.raise_for_status()
    return jsonify(resp.json()), 200

@app.route("/counter/increment", methods=["POST"])
def increment_counter():
    # fetch current
    resp = requests.get(STORE_URL)
    if resp.status_code == 404:
        current = 0
    else:
        resp.raise_for_status()
        current = int(resp.json().get("value", 0))
    new = current + 1
    # persist new
    post = requests.post(STORE_URL, json={"value": new})
    post.raise_for_status()
    return jsonify({"value": new}), 200

@app.route("/health", methods=["GET"])
def health():
    return {"status": "api up"}, 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)

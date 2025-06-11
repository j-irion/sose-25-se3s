from flask import Flask
app = Flask(__name__)

@app.route("/health")
def health():
    return {"status": "api up"}, 200

if __name__ == "__main__":
    # listen on all interfaces for Docker
    app.run(host="0.0.0.0", port=8000)

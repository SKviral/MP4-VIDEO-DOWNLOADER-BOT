"""
Keep-alive server for Render hosting.
Flask web server that responds to health checks.
"""

import os
import time
import json
from threading import Thread
from flask import Flask, jsonify

flask_app = Flask(__name__)
BOT_START_TIME = time.time()


def get_uptime():
    seconds = int(time.time() - BOT_START_TIME)
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds//60}m {seconds%60}s"
    else:
        return f"{seconds//3600}h {(seconds%3600)//60}m"


@flask_app.route("/")
def home():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Terabox Bot — Running</title>
        <meta charset="utf-8">
        <style>
            body { font-family: Arial, sans-serif; background: #0d1117; color: #c9d1d9;
                   display: flex; justify-content: center; align-items: center;
                   min-height: 100vh; margin: 0; }
            .card { background: #161b22; border: 1px solid #30363d; border-radius: 12px;
                    padding: 40px; text-align: center; max-width: 400px; }
            h1 { color: #58a6ff; }
            .badge { background: #238636; color: #fff; border-radius: 20px;
                     padding: 6px 16px; display: inline-block; margin: 10px 0; }
            .info { color: #8b949e; font-size: 14px; margin-top: 20px; }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>🤖 Terabox Bot</h1>
            <div class="badge">✅ Online &amp; Running</div>
            <p class="info">Premium Video Downloader Bot v2.0</p>
            <p class="info">Powered by Pyrogram + Flask</p>
        </div>
    </body>
    </html>
    """


@flask_app.route("/health")
def health():
    stats = {}
    try:
        if os.path.exists("bot_stats.json"):
            with open("bot_stats.json") as f:
                stats = json.load(f)
    except Exception:
        pass

    return jsonify({
        "status": "ok",
        "uptime": get_uptime(),
        "total_downloads": stats.get("total_downloads", 0),
        "total_users": stats.get("total_users", 0),
    })


@flask_app.route("/ping")
def ping():
    return jsonify({"pong": True, "time": int(time.time())})


def run():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


def keep_alive():
    t = Thread(target=run, daemon=True)
    t.start()

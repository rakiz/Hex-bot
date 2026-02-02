import logging

from flask import Flask, request, jsonify

from config import Config
from slack_client import verify_slack_signature
from dispatcher import dispatch_app_mention

logging.basicConfig(level=Config.LOG_LEVEL)
log = logging.getLogger(__name__)

def create_app() -> Flask:
    flask_app = Flask(__name__)

    @flask_app.route("/healthz", methods=["GET"])
    def healthz():
        return "ok", 200

    @flask_app.route("/slack/events", methods=["POST"])
    def slack_events():
        if not verify_slack_signature(request):
            return "invalid signature", 403

        payload = request.get_json(force=True, silent=True) or {}

        # URL verification handshake
        if payload.get("type") == "url_verification":
            return jsonify({"challenge": payload.get("challenge")})

        if payload.get("type") == "event_callback":
            event = payload.get("event", {})
            event_type = event.get("type")

            if event_type == "app_mention":
                dispatch_app_mention(event)

        # Always respond quickly to Slack
        return "", 200

    return flask_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
import logging
import threading

from flask import Flask, request, jsonify

from .config import Config
from .slack_client import verify_slack_signature
from .dispatcher import dispatch_app_mention
from .db import is_duplicate_event

logging.basicConfig(level=Config.LOG_LEVEL)
log = logging.getLogger(__name__)

def create_app() -> Flask:
    flask_app = Flask(__name__)

    @flask_app.route("/healthz", methods=["GET"])
    def healthz():
        return "ok", 200

    @flask_app.route("/oauth/google/callback", methods=["GET"])
    def oauth_google_callback():
        # Lazy imports: these symbols are only needed in this one route; keeping
        # them local avoids polluting the module namespace and makes the function
        # easier to patch in tests without touching top-level imports.
        from .oauth import verify_state, exchange_code
        from .db import upsert_user
        from .slack_client import slack

        error = request.args.get("error")
        if error:
            log.warning("OAuth error from Google: %s", error)
            return f"Google OAuth error: {error}. Please try @Hex register again.", 400

        code = request.args.get("code")
        state = request.args.get("state")
        if not code or not state:
            return "Missing code or state.", 400

        try:
            slack_user_id = verify_state(state)
        except Exception:
            log.warning("Invalid or expired OAuth state")
            return "This link has expired or is invalid. Please try @Hex register again.", 400

        try:
            refresh_token = exchange_code(code)
        except Exception:
            log.exception("Token exchange failed")
            return "Failed to connect your Google account. Please try again.", 500

        upsert_user(slack_user_id, refresh_token)
        log.info("User %s registered via OAuth", slack_user_id)

        try:
            slack.chat_postMessage(
                channel=slack_user_id,  # passing a user_id opens a DM
                text="✅ Your Google Tasks account is now connected to Hex! You can now use @Hex tasks.",
            )
        except Exception as exc:
            log.warning("Failed to send DM after OAuth: %s", exc)

        return "✅ Connected! You can close this tab and return to Slack.", 200

    @flask_app.route("/slack/events", methods=["POST"])
    def slack_events():
        if not verify_slack_signature(request):
            return "invalid signature", 403

        # force=True because Slack sometimes sends content-type: text/plain
        payload = request.get_json(force=True, silent=True) or {}

        # Slack sends this once when you first register the events URL
        if payload.get("type") == "url_verification":
            return jsonify({"challenge": payload.get("challenge")})

        if payload.get("type") == "event_callback":
            event_id = payload.get("event_id")
            if event_id and is_duplicate_event(event_id):
                log.warning("Duplicate Slack event ignored: %s", event_id)
                return "", 200

            event = payload.get("event", {})
            event_type = event.get("type")
            log.debug("event_callback received: type=%s event_id=%s", event_type, event_id)

            if event_type == "app_mention":
                # Slack expects a 200 within 3 seconds or it retries the event,
                # which would create duplicate tasks. We fire-and-forget here and
                # return immediately below.
                threading.Thread(
                    target=dispatch_app_mention,
                    args=(event,),
                    daemon=True,  # dies with the main process, no cleanup needed
                ).start()
            else:
                log.warning("Unhandled event type: %s (check Slack app event subscriptions)", event_type)

        return "", 200

    return flask_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
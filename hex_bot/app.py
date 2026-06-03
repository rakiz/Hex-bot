import logging
import threading

from flask import Flask, jsonify, redirect, request, url_for
from markupsafe import escape

from . import scheduler
from .config import Config
from .db import is_duplicate_event
from .dispatcher import dispatch_app_mention
from .slack_client import verify_slack_signature

logging.basicConfig(level=Config.LOG_LEVEL)
log = logging.getLogger(__name__)


def create_app() -> Flask:
    flask_app = Flask(__name__)

    scheduler.start()

    @flask_app.route("/", methods=["GET"])
    def index():
        return redirect(url_for("stats_page"))

    @flask_app.route("/healthz", methods=["GET"])
    def healthz():
        return "ok", 200

    @flask_app.route("/stats", methods=["GET"])
    def stats_page():
        from .db import get_records, get_stats_summary

        try:
            n_weeks = max(1, min(52, int(request.args.get("weeks", 8))))
        except (ValueError, TypeError):
            n_weeks = 8
        raw_week = request.args.get("week") or None
        up_to_week = str(escape(raw_week)) if raw_week else None
        weeks = get_stats_summary(n_weeks, up_to_week=up_to_week)
        records = get_records()
        current = weeks[0] if weeks else {}

        max_created = max((w["tasks_created"] for w in weeks), default=1) or 1

        rows = ""
        for w in weeks:
            pct = round(w["tasks_created"] / max_created * 100)
            err_class = "err" if w["tasks_failed"] else ""
            rows += f"""
            <tr>
              <td>{w["week"]}</td>
              <td>{w["tasks_created"]}</td>
              <td class="{err_class}">{w["tasks_failed"]}</td>
              <td>{w["unique_senders"]}</td>
              <td>{w["unique_assignees"]}</td>
              <td><span class="bar" style="width:{pct}%"></span></td>
            </tr>"""

        if current.get("errors"):
            error_items = "".join(
                f"<li><code>{e}</code> &times; {c}</li>"
                for e, c in current["errors"].items()
            )
            errors_html = f"<ul class='errors'>{error_items}</ul>"
        else:
            errors_html = "<p class='ok'>No errors this week &#x2705;</p>"

        bw = records["best_week"]
        max_sent = records["max_sent_by_one"]
        max_assigned = records["max_assigned_to_one"]

        anchor_label = (
            escape(up_to_week) if up_to_week else current.get("week", "&mdash;")
        )
        anchor_hint = (
            " <span style='color:#f59e0b'>(browsing history)</span>"
            if up_to_week
            else ""
        )

        failed_class = "bad" if current.get("tasks_failed", 0) else "good"

        html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Hex &mdash; Dashboard</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #0f1117; color: #e2e8f0; padding: 2rem; }}
    h1 {{ font-size: 1.8rem; margin-bottom: 0.25rem; }}
    h1 span {{ color: #7c3aed; }}
    .subtitle {{ color: #64748b; margin-bottom: 2rem; font-size: 0.9rem; }}
    .cards {{ display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 2rem; }}
    .card {{ background: #1e2130; border-radius: 10px; padding: 1.25rem 1.5rem;
             min-width: 140px; flex: 1; }}
    .card .label {{ font-size: 0.75rem; color: #64748b; text-transform: uppercase;
                    letter-spacing: 0.05em; margin-bottom: 0.4rem; }}
    .card .value {{ font-size: 2rem; font-weight: 700; }}
    .card.good .value {{ color: #34d399; }}
    .card.bad .value {{ color: #f87171; }}
    .card.neutral .value {{ color: #60a5fa; }}
    .card.gold .value {{ color: #fbbf24; }}
    h2 {{ margin-bottom: 1rem; font-size: 1.1rem; color: #94a3b8; }}
    table {{ width: 100%; border-collapse: collapse; margin-bottom: 2rem;
             background: #1e2130; border-radius: 10px; overflow: hidden; }}
    th {{ text-align: left; padding: 0.75rem 1rem; font-size: 0.75rem;
          text-transform: uppercase; letter-spacing: 0.05em; color: #64748b;
          border-bottom: 1px solid #2d3148; }}
    td {{ padding: 0.65rem 1rem; font-size: 0.9rem;
          border-bottom: 1px solid #2d3148; }}
    tr:last-child td {{ border-bottom: none; }}
    td.err {{ color: #f87171; }}
    .bar-cell {{ width: 200px; }}
    .bar {{ display: inline-block; height: 8px; background: #7c3aed;
            border-radius: 4px; min-width: 2px; }}
    .errors {{ padding-left: 1.2rem; }}
    .errors li {{ margin-bottom: 0.4rem; color: #f87171; }}
    .errors code {{ background: #2d3148; padding: 0.1rem 0.4rem;
                    border-radius: 4px; font-size: 0.85rem; }}
    .record-label {{ font-size: 0.8rem; color: #64748b; margin-top: 0.3rem; }}
    .ok {{ color: #34d399; }}
    section {{ margin-bottom: 2rem; }}
  </style>
</head>
<body>
  <h1>&#x1F916; <span>Hex</span> &mdash; Dashboard</h1>
  <p class="subtitle">Current week: {anchor_label}{anchor_hint}</p>

  <div class="cards">
    <div class="card good">
      <div class="label">Tasks created</div>
      <div class="value">{current.get("tasks_created", 0)}</div>
    </div>
    <div class="card {failed_class}">
      <div class="label">Tasks failed</div>
      <div class="value">{current.get("tasks_failed", 0)}</div>
    </div>
    <div class="card neutral">
      <div class="label">Registered users</div>
      <div class="value">{current.get("registered_users", 0)}</div>
    </div>
    <div class="card neutral">
      <div class="label">Active (senders)</div>
      <div class="value">{current.get("unique_senders", 0)}</div>
    </div>
    <div class="card neutral">
      <div class="label">Active (assignees)</div>
      <div class="value">{current.get("unique_assignees", 0)}</div>
    </div>
  </div>

  <section>
    <h2>&#x1F3C6; All-time records</h2>
    <div class="cards">
      <div class="card gold">
        <div class="label">Best week</div>
        <div class="value">{bw["tasks_created"]}</div>
        <div class="record-label">{bw["week"] or "&mdash;"}</div>
      </div>
      <div class="card gold">
        <div class="label">Most sent (1 person)</div>
        <div class="value">{max_sent}</div>
        <div class="record-label">in a single week</div>
      </div>
      <div class="card gold">
        <div class="label">Most received (1 person)</div>
        <div class="value">{max_assigned}</div>
        <div class="record-label">in a single week</div>
      </div>
    </div>
  </section>

  <section>
    <h2>Errors this week</h2>
    {errors_html}
  </section>

  <section>
    <h2>History ({n_weeks} weeks)</h2>
    <table>
      <thead>
        <tr>
          <th>Week</th>
          <th>Created</th>
          <th>Failed</th>
          <th>Senders</th>
          <th>Assignees</th>
          <th class="bar-cell">Volume</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </section>
</body>
</html>"""
        return html, 200

    @flask_app.route("/oauth/google/callback", methods=["GET"])
    def oauth_google_callback():
        # Lazy imports: these symbols are only needed in this one route; keeping
        # them local avoids polluting the module namespace and makes the function
        # easier to patch in tests without touching top-level imports.
        from .db import upsert_user
        from .oauth import exchange_code, verify_state
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
            return (
                "This link has expired or is invalid. Please try @Hex register again.",
                400,
            )

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
            log.debug(
                "event_callback received: type=%s event_id=%s", event_type, event_id
            )

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
                log.warning(
                    "Unhandled event type: %s (check Slack app event subscriptions)",
                    event_type,
                )

        return "", 200

    return flask_app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)

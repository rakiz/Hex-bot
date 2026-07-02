import logging
import threading

log = logging.getLogger(__name__)


def start_socket_mode(app_token: str, bot_token: str) -> None:
    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler
    from .dispatcher import dispatch_app_mention

    bolt_app = App(token=bot_token)

    @bolt_app.event("app_mention")
    def handle_app_mention(event, ack):
        ack()
        threading.Thread(
            target=dispatch_app_mention,
            args=(event,),
            daemon=True,
        ).start()

    handler = SocketModeHandler(bolt_app, app_token)
    threading.Thread(target=handler.start, daemon=True, name="slack-socket-mode").start()

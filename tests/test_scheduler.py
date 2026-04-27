import threading
from unittest.mock import patch, call


def test_start_creates_daemon_thread():
    from hex_bot import scheduler
    with patch.object(scheduler, "_loop"):
        with patch("hex_bot.scheduler.threading.Thread") as mock_thread:
            mock_thread.return_value.start = lambda: None
            scheduler.start()
    mock_thread.assert_called_once()
    assert mock_thread.call_args[1]["daemon"] is True
    assert mock_thread.call_args[1]["name"] == "stats-scheduler"


def test_loop_calls_init_week_stats():
    from hex_bot import scheduler
    call_count = 0

    def fake_init():
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise SystemExit

    with patch("hex_bot.scheduler.time.sleep"), \
         patch("hex_bot.db.init_week_stats", side_effect=fake_init):
        try:
            scheduler._loop()
        except SystemExit:
            pass

    assert call_count == 2

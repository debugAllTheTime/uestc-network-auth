"""Service entry point."""
import logging
import signal
import sys
from threading import Event

from .auth import AuthClient
from .config import ConfigError, Settings, load_credentials
from .monitor import run_monitor


def main():
    logging.basicConfig(
        level=logging.INFO, stream=sys.stdout,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )
    # Keep dependency logs at warning level.
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    stop = Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda _signum, _frame: stop.set())
    try:
        settings = Settings.from_env()
        credentials = load_credentials(settings.credentials_file)
        run_monitor(settings, AuthClient(settings, credentials), stop)
    except ConfigError as exc:
        logging.getLogger(__name__).error('Configuration error: %s', exc)
        return 2
    except Exception as exc:
        logging.getLogger(__name__).error('Service stopped: %s', type(exc).__name__)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

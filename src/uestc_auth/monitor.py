"""Ping-based monitor with consecutive-failure counting and login cooldown."""
import logging
import subprocess
from threading import Event

from .auth import AuthClient, AuthError
from .config import Settings

LOGGER = logging.getLogger(__name__)


def ping(target: str) -> bool:
    # Probe one packet per check.
    completed = subprocess.run(
        ['ping', target, '-c', '1'], stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, check=False,
    )
    return completed.returncode == 0


def run_monitor(settings: Settings, client: AuthClient, stop: Event, probe=ping):
    failed = 0
    delay = settings.interval
    was_unreachable = False
    LOGGER.info('Network monitor started; ping target=%s', settings.ping_target)
    while not stop.is_set():
        reachable = probe(settings.ping_target)
        if stop.is_set():
            break
        if reachable:
            if was_unreachable:
                LOGGER.info('Ping reachable again')
            failed = 0
            delay = settings.interval
            was_unreachable = False
        else:
            was_unreachable = True
            failed += 1
            delay /= 2
            LOGGER.warning('Ping failed (%s/%s)', failed, settings.max_failed)
            if failed >= settings.max_failed:
                LOGGER.warning('Ping failure threshold reached; attempting authentication')
                try:
                    client.login()
                except AuthError as exc:
                    LOGGER.error('Authentication stopped: %s', exc)
                except Exception as exc:
                    # Report unexpected failures by exception type.
                    LOGGER.error('Authentication raised %s', type(exc).__name__)
                finally:
                    LOGGER.info('Authentication cooldown: %s seconds', settings.cooldown)
                    stop.wait(settings.cooldown)
                failed = 0
                delay = settings.interval
                continue
        stop.wait(delay)
    LOGGER.info('Network monitor stopped')

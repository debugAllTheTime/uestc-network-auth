"""Rotating JSONL archive for authentication HTTP exchanges."""
import base64
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import stat

MAX_BYTES = 10 * 1024 * 1024
BEIJING = timezone(timedelta(hours=8))


def _private_file(path):
    fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise OSError('Archive file must be regular and owned by service user')
        os.fchmod(fd, 0o600)
        return fd
    except BaseException:
        os.close(fd)
        raise


def save_exchange(directory: Path, request, response=None, error=None):
    """Keep three JSONL files. A single oversized record is never truncated.

    body is decoded text for inspection; body_base64 preserves every byte of
    requests' decoded HTTP entity body, not raw TLS/HTTP framing or compression.
    """
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = directory.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
        raise OSError('Archive directory must be owned by service user')
    directory.chmod(0o700)
    record = {
        'time': datetime.now(BEIJING).isoformat(),
        'request': request,
        'response': None if response is None else {
            'url': response.url,
            'http_status': response.status_code,
            'headers': dict(response.headers),
            'encoding': response.encoding,
            'body': response.text,
            'body_base64': base64.b64encode(response.content).decode('ascii'),
        },
        'error_type': error,
    }
    payload = (json.dumps(record, ensure_ascii=False) + '\n').encode('utf-8')
    lock_fd = _private_file(directory / '.lock')
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        current = directory / 'auth-exchanges.jsonl'
        fd = _private_file(current)
        try:
            size = os.fstat(fd).st_size
        finally:
            os.close(fd)
        if size and size + len(payload) > MAX_BYTES:
            # Rotate the two historical files.
            for name in ('auth-exchanges.jsonl.1', 'auth-exchanges.jsonl.2'):
                path = directory / name
                if path.is_symlink():
                    raise OSError('Archive symlink not permitted')
            first = directory / 'auth-exchanges.jsonl.1'
            if first.exists():
                os.replace(first, directory / 'auth-exchanges.jsonl.2')
            os.replace(current, first)
        fd = _private_file(current)
        with os.fdopen(fd, 'ab') as stream:
            stream.write(payload)
            stream.flush()
    finally:
        os.close(lock_fd)

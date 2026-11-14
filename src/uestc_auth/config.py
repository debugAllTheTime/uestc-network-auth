"""Service settings and JSON credential configuration."""
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Mapping


class ConfigError(ValueError):
    """Invalid configuration."""


@dataclass(frozen=True)
class Credentials:
    username: str = field(repr=False)
    password: str = field(repr=False)


@dataclass(frozen=True)
class Settings:
    network: str = 'uestc'
    ping_target: str = 'www.scu.edu.cn'
    interval: float = 16
    max_failed: int = 3
    cooldown: float = 60
    connect_timeout: float = 5
    read_timeout: float = 10
    credentials_file: Path = Path('/run/secrets/uestc_credentials')
    response_dir: Path = Path('/var/lib/uestc-auth/responses')
    archive_enabled: bool = False

    def __post_init__(self):
        if self.network not in {'uestc', 'dx', 'cmcc'}:
            raise ConfigError('NETWORK must be uestc, dx or cmcc')
        if (not isinstance(self.ping_target, str) or len(self.ping_target) > 253 or
                not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', self.ping_target)):
            raise ConfigError('PING_TARGET must be an IPv4 address or hostname')
        if type(self.max_failed) is not int or self.max_failed < 1:
            raise ConfigError('MAX_FAILED must be a positive integer')
        for name in ('interval', 'cooldown', 'connect_timeout', 'read_timeout'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ConfigError(name + ' must be finite and positive')
        if self.cooldown < 60:
            raise ConfigError('LOGIN_COOLDOWN must be at least 60 seconds')

    @property
    def gateway(self):
        return 'http://10.253.0.237' if self.network == 'uestc' else 'http://10.253.0.235'

    @property
    def ac_id(self):
        return '1' if self.network == 'uestc' else '3'

    @property
    def domain(self):
        return '@dx-uestc' if self.network == 'uestc' else '@' + self.network

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None):
        env = os.environ if environ is None else environ
        try:
            archive = env.get('ARCHIVE_ENABLED', 'false').lower()
            if archive not in {'true', 'false'}:
                raise ConfigError('ARCHIVE_ENABLED must be true or false')
            return cls(
                network=env.get('NETWORK', 'uestc'),
                ping_target=env.get('PING_TARGET', 'www.scu.edu.cn'),
                interval=float(env.get('CHECK_INTERVAL', '16')),
                max_failed=int(env.get('MAX_FAILED', '3')),
                cooldown=float(env.get('LOGIN_COOLDOWN', '60')),
                credentials_file=Path(env.get('CREDENTIALS_FILE', '/run/secrets/uestc_credentials')),
                response_dir=Path(env.get('RESPONSE_DIR', '/var/lib/uestc-auth/responses')),
                archive_enabled=archive == 'true',
            )
        except (TypeError, ValueError):
            raise ConfigError('Invalid network or monitor configuration') from None


def load_credentials(path: Path) -> Credentials:
    try:
        with path.open('r', encoding='utf-8') as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
                raise ConfigError('Credential file must be a regular file with mode 0600')
            data = json.load(stream)
    except (OSError, ValueError, UnicodeError):
        raise ConfigError('Cannot read valid private credential configuration (required mode 0600)') from None
    if not isinstance(data, dict) or any(not isinstance(data.get(k), str) or not data[k] for k in ('id', 'passwd')):
        raise ConfigError('Credential file requires nonempty id and passwd strings')
    username, password = data['id'], data['passwd']
    if username != username.strip() or '@' in username:
        raise ConfigError('Credential id must not contain surrounding whitespace or a domain suffix')
    # The protocol encoder accepts ASCII credentials.
    if not username.isascii() or not password.isascii():
        raise ConfigError('Non-ASCII credentials are not supported by the existing encoder')
    return Credentials(username, password)

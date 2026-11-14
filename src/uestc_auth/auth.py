"""Srun authentication client."""
from dataclasses import dataclass
from html.parser import HTMLParser
import ipaddress
import json
import logging
import re
from urllib.parse import urlencode

import requests

from .config import Credentials, Settings
from .responses import save_exchange
from .encryption.srun_md5 import get_md5
from .encryption.srun_sha1 import get_sha1
from .encryption.srun_base64 import get_base64
from .encryption.srun_xencode import get_xencode

LOGGER = logging.getLogger(__name__)
CHALLENGE_CALLBACK = 'jsonp1583251661367'
LOGIN_CALLBACK = 'jQuery112407481914773997063_1631531125398'
HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36'}
KNOWN_MESSAGES = {
    'ok', 'ip_already_online_error', 'not_online_error', 'no_response_data_error',
    'user_must_modify_password', 'vcode_error', 'account_locked', 'challenge_expire_error',
}


class AuthError(RuntimeError):
    """Authentication request or protocol error."""


@dataclass(frozen=True)
class AuthResult:
    status: str
    details: str = ''


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.legacy_ips = []
        self._script = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script':
            self._script = []
        elif tag == 'input' and attrs.get('id') == 'user_ip':
            self.legacy_ips.append(attrs.get('value', ''))

    def handle_data(self, data):
        if self._script is not None:
            self._script.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self._script is not None:
            self.scripts.append(''.join(self._script))
            self._script = None


def _config_ips(script):
    """Read literal top-level CONFIG.ip, skipping strings/comments/nested objects."""
    tokens = re.findall(r'''//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[A-Za-z_$][\w$]*|[^\s]''', script)
    tokens = [t for t in tokens if not t.startswith(('//', '/*'))]
    start = next((i + 3 for i in range(len(tokens) - 2)
                  if tokens[i:i + 3] == ['CONFIG', '=', '{']), None)
    if start is None:
        return []
    depth = 1
    ips = []
    for i in range(start, len(tokens)):
        token = tokens[i]
        if token in ('{', '['):
            depth += 1
        elif token in ('}', ']'):
            depth -= 1
            if depth == 0:
                break
        elif (depth == 1 and token in ('ip', '"ip"', "'ip'") and
              tokens[i - 1] in ('{', ',') and i + 2 < len(tokens) and tokens[i + 1] == ':'):
            value = tokens[i + 2]
            if value.startswith(('"', "'")):
                ips.append(value[1:-1])
    return ips


def extract_ip(page: str) -> str:
    parser = _PageParser()
    parser.feed(page)
    candidates = [ip for script in parser.scripts for ip in _config_ips(script)]
    candidates.extend(parser.legacy_ips)
    for value in candidates:
        try:
            address = ipaddress.ip_address(value)
        except (ValueError, TypeError):
            continue
        if (address.version == 4 and not address.is_unspecified and
                not address.is_multicast and not address.is_loopback and
                str(address) != '255.255.255.255'):
            return str(address)
    raise AuthError('No valid IPv4 address found in CONFIG.ip or legacy user_ip')


def parse_response(text: str, callback: str) -> dict:
    text = text.strip()
    if not text.startswith('{'):
        match = re.fullmatch(re.escape(callback) + r'\s*\((.*)\)\s*;?', text, re.S)
        if not match:
            raise AuthError('Invalid JSON/JSONP response or unexpected callback')
        text = match.group(1)
    try:
        data = json.loads(text)
    except ValueError:
        raise AuthError('Invalid JSON response') from None
    if not isinstance(data, dict):
        raise AuthError('Expected a JSON object')
    return data


def response_status(data: dict) -> str:
    if 'error' in data and 'code' not in data:
        if not isinstance(data['error'], str) or not data['error']:
            return 'unknown'
        return 'success' if data['error'] == 'ok' else 'failed'
    if 'code' in data and 'error' not in data:
        if type(data['code']) is not int:
            return 'unknown'
        return 'success' if data['code'] == 0 else 'failed'
    return 'unknown'


def classify_result(data: dict) -> AuthResult:
    status = response_status(data)
    if status == 'success' and data.get('suc_msg') == 'ip_already_online_error':
        status = 'already_online'
    elif status == 'failed' and 'ip_already_online_error' in (data.get('error'), data.get('error_msg')):
        status = 'already_online_conflict'
    details = []
    # Format recognized result codes for the service log.
    for key in ('error', 'ecode', 'code', 'suc_msg', 'error_msg'):
        value = data.get(key)
        if type(value) is int or (isinstance(value, str) and
                (value in KNOWN_MESSAGES or re.fullmatch(r'E[0-9]{3,8}', value))):
            details.append(key + '=' + str(value))
    return AuthResult(status, ', '.join(details))


def build_login_params(settings: Settings, credentials: Credentials, ip: str, token: str) -> dict:
    username = credentials.username + settings.domain
    info = json.dumps({
        'username': username, 'password': credentials.password, 'ip': ip,
        'acid': settings.ac_id, 'enc_ver': 'srun_bx1',
    }, ensure_ascii=False, separators=(',', ':'))
    encoded = '{SRBX1}' + get_base64(get_xencode(info, token))
    md5 = get_md5(credentials.password, token)
    checksum = get_sha1(''.join(token + value for value in (
        username, md5, settings.ac_id, ip, '200', '1', encoded,
    )))
    return {
        'callback': LOGIN_CALLBACK, 'action': 'login', 'username': username,
        'password': '{MD5}' + md5, 'ac_id': settings.ac_id, 'ip': ip,
        'chksum': checksum, 'info': encoded, 'n': '200', 'type': '1',
        'os': 'Windows 10', 'name': 'Windows', 'double_stack': 0,
    }


class AuthClient:
    def __init__(self, settings: Settings, credentials: Credentials):
        self.settings = settings
        self._credentials = credentials

    def _archive(self, request, response=None, error=None):
        if not self.settings.archive_enabled:
            return
        try:
            save_exchange(self.settings.response_dir, request, response, error)
        except Exception as exc:
            # Archive errors are reported independently of authentication results.
            LOGGER.error('Authentication archive failed: %s', type(exc).__name__)

    def _get(self, path, params=None):
        request = {
            'method': 'GET',
            'url': requests.Request('GET', self.settings.gateway + path,
                                    params=params).prepare().url,
            'params': dict(params or {}),
            'headers': dict(HEADERS),
        }
        try:
            # Each request uses a direct session.
            with requests.Session() as session:
                session.trust_env = False
                response = session.get(
                    self.settings.gateway + path, params=params, headers=HEADERS,
                    timeout=(self.settings.connect_timeout, self.settings.read_timeout),
                    allow_redirects=False,
                )
            prepared = getattr(response, 'request', None)
            if prepared is not None:
                request['url'] = prepared.url
                request['headers'] = dict(prepared.headers)
            # Save all three auth endpoints before validation, never ping.
            self._archive(request, response)
            response.raise_for_status()
            if 300 <= response.status_code < 400:
                raise AuthError('Unexpected authentication HTTP redirect')
            return response.text
        except requests.RequestException as exc:
            if getattr(exc, 'response', None) is None:
                self._archive(request, error=type(exc).__name__)
            status = getattr(getattr(exc, 'response', None), 'status_code', None)
            detail = 'HTTP ' + str(status) if status is not None else type(exc).__name__
            raise AuthError('Authentication request failed: ' + detail) from None

    def login(self) -> AuthResult:
        LOGGER.info('Authentication: fetching login page')
        page = self._get('/srun_portal_pc?' + urlencode({'ac_id': self.settings.ac_id, 'theme': 'pro'}))
        ip = extract_ip(page)
        LOGGER.info('Authentication: page IP parsed; requesting challenge')
        data = parse_response(self._get('/cgi-bin/get_challenge', {
            'callback': CHALLENGE_CALLBACK,
            'username': self._credentials.username + self.settings.domain, 'ip': ip,
        }), CHALLENGE_CALLBACK)
        token = data.get('challenge')
        if response_status(data) != 'success' or not isinstance(token, str) or not token.strip():
            raise AuthError('Challenge response is unsuccessful or has no valid token')
        LOGGER.info('Authentication: challenge parsed; submitting login')
        params = build_login_params(self.settings, self._credentials, ip, token)
        result = classify_result(parse_response(self._get('/cgi-bin/srun_portal', params), LOGIN_CALLBACK))
        LOGGER.info('Authentication result: %s (%s)', result.status, result.details)
        return result

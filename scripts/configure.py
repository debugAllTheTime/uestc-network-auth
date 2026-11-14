"""Create the local credential file. Run from the repository directory."""
import getpass
import json
import os
from pathlib import Path
import sys


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run with sudo: sudo python3 -I scripts/configure.py')
    path = Path.cwd() / 'secrets' / 'credentials.json'
    if path.exists() or path.is_symlink():
        raise SystemExit('secrets/credentials.json already exists.')
    username = input('学号（不带域后缀）: ').strip()
    password = getpass.getpass('密码: ')
    if not username or '@' in username or not password:
        raise SystemExit('学号和密码不能为空，学号不带域后缀。')
    if not username.isascii() or not password.isascii():
        raise SystemExit('当前编码器支持 ASCII 账号密码。')
    path.parent.mkdir(mode=0o700, exist_ok=True)
    path.parent.chmod(0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump({'id': username, 'passwd': password}, stream)
        stream.write('\n')
    print('已创建 secrets/credentials.json。')


if __name__ == '__main__':
    main()

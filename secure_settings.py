"""Encrypted settings. Windows uses DPAPI, macOS keeps the key in the login Keychain. No plaintext credential fallback."""
import ctypes
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading

PATH = Path(__file__).resolve().parent / 'data/settings.dpapi'
_lock = threading.RLock()

# macOS: a random 256-bit key lives in the login Keychain (one item per install folder);
# settings are encrypted with it in data/, using HMAC-SHA256 as keystream and as an integrity tag.
MAC_PATH = Path(__file__).resolve().parent / 'data/settings.mac'
SECURITY = '/usr/bin/security'
SERVICE = 'DreadOS AI'
ACCOUNT = 'settings-key-' + hashlib.sha256(str(Path(__file__).resolve().parent).encode()).hexdigest()[:16]
MAGIC = b'DOS1'


def _mac():
    return sys.platform == 'darwin'


def crypt(raw, decrypt=False):
    if os.name != 'nt': raise ValueError('Saved credentials require Windows or macOS encryption.')
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

    buf = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    api = ctypes.windll.crypt32
    fn = api.CryptUnprotectData if decrypt else api.CryptProtectData
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ValueError('Could not unlock saved settings for this Windows account. Original file was preserved.')
    try: return ctypes.string_at(output.data, output.size)
    finally: ctypes.windll.kernel32.LocalFree(output.data)


def _keychain_key(create=False):
    result = subprocess.run([SECURITY, 'find-generic-password', '-s', SERVICE, '-a', ACCOUNT, '-w'],
                            capture_output=True, text=True, timeout=30)
    if result.returncode == 0:
        return bytes.fromhex(result.stdout.strip())
    if result.returncode != 44 or not create:  # 44 = no such item
        raise ValueError('Could not unlock saved settings with your macOS Keychain. The original file was preserved.')
    key = secrets.token_bytes(32)
    # `security -i` reads the command from stdin, so the key never appears in the process list.
    command = f'add-generic-password -s "{SERVICE}" -a "{ACCOUNT}" -w {key.hex()}\n'
    added = subprocess.run([SECURITY, '-i'], input=command, capture_output=True, text=True, timeout=30)
    if added.returncode or 'error' in added.stderr.lower():
        raise ValueError('Could not save a settings key to your macOS Keychain.')
    return key


def _stream(key, nonce, length):
    out = bytearray()
    for counter in range(0, length // 32 + 1):
        out += hmac.new(key, nonce + counter.to_bytes(8, 'big'), hashlib.sha256).digest()
    return bytes(out[:length])


def mac_seal(key, raw):
    enc, auth = (hmac.new(key, label, hashlib.sha256).digest() for label in (b'encrypt', b'authenticate'))
    nonce = secrets.token_bytes(16)
    body = bytes(a ^ b for a, b in zip(raw, _stream(enc, nonce, len(raw))))
    return MAGIC + nonce + body + hmac.new(auth, MAGIC + nonce + body, hashlib.sha256).digest()


def mac_open(key, blob):
    enc, auth = (hmac.new(key, label, hashlib.sha256).digest() for label in (b'encrypt', b'authenticate'))
    if len(blob) < 52 or blob[:4] != MAGIC or not hmac.compare_digest(blob[-32:], hmac.new(auth, blob[:-32], hashlib.sha256).digest()):
        raise ValueError('Saved settings could not be verified. The original file was preserved.')
    nonce, body = blob[4:20], blob[20:-32]
    return bytes(a ^ b for a, b in zip(body, _stream(enc, nonce, len(body))))


def read():
    with _lock:
        if _mac():
            if not MAC_PATH.exists(): return {}
            return json.loads(mac_open(_keychain_key(), MAC_PATH.read_bytes()))
        if not PATH.exists(): return {}
        return json.loads(crypt(PATH.read_bytes(), True))


def save(section, value):
    with _lock:
        data = read(); data[section] = value
        if _mac():
            target, encrypted = MAC_PATH, mac_seal(_keychain_key(create=True), json.dumps(data).encode())
        else:
            target, encrypted = PATH, crypt(json.dumps(data).encode())
        target.parent.mkdir(exist_ok=True)
        temp = target.with_suffix('.tmp')
        temp.write_bytes(encrypted)
        temp.replace(target)

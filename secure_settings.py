"""Windows-user encrypted settings. No plaintext credential fallback."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import threading

PATH = Path(__file__).resolve().parent / 'data/settings.dpapi'
_lock = threading.RLock()
class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

def crypt(raw, decrypt=False):
    if os.name != 'nt': raise ValueError('Saved credentials require Windows encryption.')
    buf = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    api = ctypes.windll.crypt32
    fn = api.CryptUnprotectData if decrypt else api.CryptProtectData
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ValueError('Could not unlock saved settings for this Windows account. Original file was preserved.')
    try: return ctypes.string_at(output.data, output.size)
    finally: ctypes.windll.kernel32.LocalFree(output.data)

def read():
    with _lock:
        if not PATH.exists(): return {}
        return json.loads(crypt(PATH.read_bytes(), True))

def save(section, value):
    with _lock:
        data = read(); data[section] = value
        encrypted = crypt(json.dumps(data).encode())
        PATH.parent.mkdir(exist_ok=True)
        temp = PATH.with_suffix('.tmp')
        temp.write_bytes(encrypted)
        temp.replace(PATH)

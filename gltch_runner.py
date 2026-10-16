"""Pinned GLTCH stdio transport. No user-supplied commands are executed."""
import atexit
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time

URL = 'https://api.gltch.app'
ROOT = Path(__file__).resolve().parent
_live = set()

class Runner:
    def __init__(self, key):
        script = ROOT / '.gltch-runtime/node_modules/gltch-runner-mcp/dist/index.js'
        node = shutil.which('node')
        if not node or not script.is_file():
            raise ValueError('GLTCH runtime is missing. Install gltch-runner-mcp@1.0.0 in .gltch-runtime.')
        env = {k:v for k,v in os.environ.items() if k.upper() in ('PATH','SYSTEMROOT','WINDIR','TEMP','TMP','USERPROFILE','LOCALAPPDATA','APPDATA')}
        env.update(GLTCH_API_KEY=key, GLTCH_API_BASE=URL, NODE_USE_SYSTEM_CA='1')
        self.process = subprocess.Popen([node, str(script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, cwd=ROOT, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.responses = queue.Queue(maxsize=64)
        _live.add(self)
        threading.Thread(target=self._read, daemon=True).start()
    def _read(self):
        try:
            while True:
                line = self.process.stdout.readline(16*1024*1024+1)
                if not line or len(line)>16*1024*1024: break
                value=json.loads(line)
                if 'id' in value: self.responses.put_nowait(value)
        except (ValueError,OSError,queue.Full): pass
        finally:
            try: self.responses.put_nowait(None)
            except queue.Full: pass
    def rpc(self, method, params, ident, notification=False):
        body={'jsonrpc':'2.0','method':method,'params':params}
        if not notification: body['id']=ident
        try:
            self.process.stdin.write((json.dumps(body)+'\n').encode());self.process.stdin.flush()
            if notification: return {}
            deadline=time.monotonic()+(660 if method=='tools/call' else 20)
            while True:
                response=self.responses.get(timeout=max(.01,deadline-time.monotonic()))
                if response is None: raise ValueError('GLTCH process stopped. Reconnect the service.')
                if response.get('id')==ident: return response
        except queue.Empty:
            self.close()
            raise ValueError('GLTCH timed out. A media job may still be running: use check_job before generating again.') from None
        except (OSError,AttributeError):
            raise ValueError('GLTCH connection closed. Reconnect the service.') from None
    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=3)
            except subprocess.TimeoutExpired: self.process.kill()
        for stream in (self.process.stdin,self.process.stdout):
            if stream: stream.close()
        _live.discard(self)

@atexit.register
def shutdown():
    for runner in list(_live): runner.close()

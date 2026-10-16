"""Best-effort foreground requests for explicitly launched, allowlisted Windows apps."""
import ctypes
from ctypes import wintypes as W
import os
from pathlib import PureWindowsPath
import threading
import time

PROCESSES={
    'notepad':{'notepad.exe'},'calculator':{'calculatorapp.exe','calculator.exe','calc.exe'},
    'paint':{'mspaint.exe'},'file explorer':{'explorer.exe'},
    'sublime':{'sublime_text.exe'},'sticky notes':{'microsoft.notes.exe','stickynotes.exe'},
}
_lock=threading.Lock()
_request=0

class Windows:
    def __init__(self):
        self.user=ctypes.WinDLL('user32',use_last_error=True)
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.callback=ctypes.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
        for name,args,result in [
            ('EnumWindows',[self.callback,W.LPARAM],W.BOOL),
            ('EnumChildWindows',[W.HWND,self.callback,W.LPARAM],W.BOOL),
            ('IsWindowVisible',[W.HWND],W.BOOL),('IsIconic',[W.HWND],W.BOOL),
            ('GetClassNameW',[W.HWND,W.LPWSTR,ctypes.c_int],ctypes.c_int),
            ('GetWindowThreadProcessId',[W.HWND,ctypes.POINTER(W.DWORD)],W.DWORD),
            ('ShowWindowAsync',[W.HWND,ctypes.c_int],W.BOOL),
            ('SetForegroundWindow',[W.HWND],W.BOOL),('FlashWindow',[W.HWND,W.BOOL],W.BOOL)]:
            fn=getattr(self.user,name);fn.argtypes=args;fn.restype=result
        self.kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];self.kernel.OpenProcess.restype=W.HANDLE
        self.kernel.QueryFullProcessImageNameW.argtypes=[W.HANDLE,W.DWORD,W.LPWSTR,ctypes.POINTER(W.DWORD)]
        self.kernel.QueryFullProcessImageNameW.restype=W.BOOL
        self.kernel.CloseHandle.argtypes=[W.HANDLE];self.kernel.CloseHandle.restype=W.BOOL

    def executable(self,hwnd):
        pid=W.DWORD();self.user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        handle=self.kernel.OpenProcess(0x1000,False,pid.value)
        if not handle:return ''
        try:
            size=W.DWORD(32768);path=ctypes.create_unicode_buffer(size.value)
            if self.kernel.QueryFullProcessImageNameW(handle,0,path,ctypes.byref(size)):
                return PureWindowsPath(path.value).name.lower()
            return ''
        finally:self.kernel.CloseHandle(handle)

    def find(self,app):
        found=[]
        @self.callback
        def visit(hwnd,_):
            if not self.user.IsWindowVisible(hwnd):return True
            cls=ctypes.create_unicode_buffer(256);self.user.GetClassNameW(hwnd,cls,256)
            if app=='file explorer' and cls.value not in ('CabinetWClass','ExploreWClass'):return True
            matches=self.executable(hwnd) in PROCESSES[app]
            # Older packaged apps put the application inside an ApplicationFrameHost window.
            if not matches and cls.value=='ApplicationFrameWindow':
                @self.callback
                def child(handle,_):
                    if self.executable(handle) in PROCESSES[app]:found.append(hwnd);return False
                    return True
                self.user.EnumChildWindows(hwnd,child,0)
            elif matches:found.append(hwnd)
            return not bool(found)
        self.user.EnumWindows(visit,0)
        return found[0] if found else None

    def activate(self,hwnd):
        if self.user.IsIconic(hwnd):self.user.ShowWindowAsync(hwnd,9) # SW_RESTORE
        if not self.user.SetForegroundWindow(hwnd):
            self.user.FlashWindow(hwnd,True)


def _focus(app,request):
    try:
        windows=Windows()
        for _ in range(24):
            with _lock:
                if request!=_request:return
            hwnd=windows.find(app)
            if hwnd:
                with _lock:
                    if request==_request:windows.activate(hwnd)
                return
            time.sleep(.25)
    except (OSError,AttributeError):
        # Focusing must never turn a successful app launch into a failed command.
        return


def after_launch(app,pid):
    global _request
    if os.name!='nt' or app not in PROCESSES or type(pid) is not int:return
    with _lock:
        _request+=1;request=_request
    threading.Thread(target=_focus,args=(app,request),daemon=True).start()

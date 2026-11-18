"""Bounded pipe transport for legacy media tools; not a decoder sandbox."""
import contextlib
import os
import queue
import signal
import subprocess
import threading
import time
from . import cancellation
from .core import Invalid

CHUNK = 65536
DIAGNOSTIC_LIMIT = 65536


def bounded_run(argv, cap, timeout, sink=None):
    """Drain both pipes with bounded memory; kill/reap on every exit.

    POSIX owns a process group. Windows owns the direct child only (no Job
    Object guarantee). Reader threads own their pipe handles; Windows escaped
    descendants may retain handles after bounded cleanup, see documentation.
    """
    output = bytearray()
    count = diagnostics = 0
    events = queue.Queue(maxsize=8)
    stopping = threading.Event()
    readers = []
    owned_pipes = set()
    process = None
    deadline = time.monotonic() + timeout

    def emit(event):
        while not stopping.is_set():
            try:
                events.put(event, timeout=.05)
                return
            except queue.Full:
                pass

    def drain(pipe, label):
        try:
            while not stopping.is_set():
                data = os.read(pipe.fileno(), CHUNK)
                if not data:
                    break
                emit((label, data))
        except OSError:
            if not stopping.is_set():emit(('error', b''))
        finally:
            pipe.close()
            emit((label, None))

    def kill():
        if process is None:return
        try:
            if os.name == 'posix':os.killpg(process.pid, signal.SIGKILL)
            elif process.poll() is None:process.kill()
        except ProcessLookupError:
            pass

    # Background callers retain bounded transport without installing handlers.
    class WorkerScope:
        defer = staticmethod(contextlib.nullcontext)
    scope = cancellation.scope() if threading.current_thread() is threading.main_thread() else contextlib.nullcontext(WorkerScope())
    with scope as cancelled:
        try:
            with cancelled.defer():
                process = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    **({'start_new_session':True, 'umask':0o077} if os.name=='posix' else {}))
                for pipe,label in ((process.stdout,'out'),(process.stderr,'err')):
                    thread = threading.Thread(target=drain,args=(pipe,label),daemon=True)
                    thread.start();readers.append(thread);owned_pipes.add(pipe)
            ended = 0
            while ended < 2 or process.poll() is None:
                if time.monotonic() >= deadline:raise Invalid('Media tool failed or timed out.')
                # A parent that exits without closing inherited pipes must not
                # leave its process group running until the full deadline.
                if process.poll() is not None:kill()
                try:label,data = events.get(timeout=min(.05,max(0,deadline-time.monotonic())))
                except queue.Empty:continue
                if label=='error':raise Invalid('Media tool pipe read failed.')
                if data is None:ended+=1;continue
                if label=='err':
                    diagnostics+=len(data)
                    if diagnostics>DIAGNOSTIC_LIMIT:raise Invalid('Media processing failed or output exceeded bounds.')
                else:
                    count+=len(data)
                    if count>cap:raise Invalid('Media processing failed or output exceeded bounds.')
                    if sink is not None:sink(data)
                    else:output.extend(data)
            if process.returncode or diagnostics:raise Invalid('Media processing failed or output exceeded bounds.')
            return bytes(output)
        except OSError:
            raise Invalid('Media tool failed or timed out.') from None
        finally:
            with cancelled.defer():
                stopping.set()
                if process is not None:
                    kill()
                    try:process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        raise Invalid('Media process cleanup deadline exceeded.') from None
                    finally:
                        end=time.monotonic()+2
                        for thread in readers:thread.join(max(0,end-time.monotonic()))
                        # If starting a reader failed, no other thread owns its pipe.
                        for pipe in (process.stdout,process.stderr):
                            if pipe not in owned_pipes:pipe.close()

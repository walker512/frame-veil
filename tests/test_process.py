"""Finite synthetic subprocess probes; no private media."""
import os,signal,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from frame_veil import core,cancellation
from frame_veil.process import bounded_run

class Transport(unittest.TestCase):
    def invoke(self,code,cap=1024,timeout=2,sink=None):
        return bounded_run([sys.executable,'-c',code],cap,timeout,sink)
    def test_exact_limit(self):
        self.assertEqual(self.invoke('import os;os.write(1,b"x"*1024)'),b'x'*1024)
    def test_empty_stdout(self):self.assertEqual(self.invoke('pass',cap=0),b'')
    def test_stdout_overflow_is_rejected_before_sink(self):
        chunks=[]
        with self.assertRaises(core.Invalid):
            self.invoke('import os;os.write(1,b"x"*4194304)',cap=8,sink=chunks.append)
        self.assertEqual(chunks,[])
    def test_finite_diagnostic_flood(self):
        with self.assertRaises(core.Invalid) as e:
            self.invoke('import os;os.write(2,b"PRIVATE"*200000)')
        self.assertNotIn('PRIVATE',str(e.exception))
    def test_success_stderr_rejected(self):
        with self.assertRaises(core.Invalid):self.invoke('import os;os.write(2,b"x")')
    def test_nonzero_exit(self):
        with self.assertRaises(core.Invalid):self.invoke('raise SystemExit(7)')
    def test_pipe_eof_does_not_disable_timeout(self):
        start=time.monotonic()
        with self.assertRaises(core.Invalid):
            self.invoke('import os,time;os.close(1);os.close(2);time.sleep(5)',timeout=.1)
        self.assertLess(time.monotonic()-start,3)
    def test_sink_exception_preserved(self):
        def sink(chunk):raise core.MaskMismatch(1,2,3)
        with self.assertRaises(core.MaskMismatch) as e:self.invoke('print("x")',sink=sink)
        self.assertEqual(e.exception.location,{'frame_index':1,'mask_index':2,'pixel_row':3})
    def test_background_thread_transport_preserved(self):
        result=[]
        thread=threading.Thread(target=lambda:result.append(self.invoke('print("ok",end="")')))
        thread.start();thread.join(3)
        self.assertFalse(thread.is_alive());self.assertEqual(result,[b'ok'])
    def test_windows_branch_direct_child(self):
        # Simulated branch only, NOT native Windows process-tree verification.
        with patch('frame_veil.process.os.name','nt'):
            self.assertEqual(self.invoke('print("ok",end="")'),b'ok')

@unittest.skipUnless(sys.platform=='linux','Linux /proc lifecycle verification')
class Lifecycle(unittest.TestCase):
    def assert_stopped(self,pid):
        for _ in range(100):
            try:state=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[0]
            except FileNotFoundError:return
            if state=='Z':return
            time.sleep(.01)
        self.fail(f'synthetic child still running: {pid}')
    def test_group_timeout_and_parent_exit(self):
        for exit_parent in (False,True):
            with self.subTest(exit_parent=exit_parent),tempfile.TemporaryDirectory() as td:
                mark=Path(td)/'pid'
                code=f'''import subprocess,sys,time
from pathlib import Path
p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(5)'])
Path({str(mark)!r}).write_text(str(p.pid))
{'' if exit_parent else 'time.sleep(5)'}
'''
                try:
                    if exit_parent:bounded_run([sys.executable,'-c',code],100,1)
                    else:
                        with self.assertRaises(core.Invalid):bounded_run([sys.executable,'-c',code],100,.3)
                    self.assert_stopped(int(mark.read_text()))
                finally:
                    if mark.exists():
                        try:os.kill(int(mark.read_text()),signal.SIGKILL)
                        except ProcessLookupError:pass
    def test_signal_during_spawn_owned_and_reaped(self):
        original=subprocess.Popen;pids=[]
        def spawn(*args,**kwargs):
            p=original(*args,**kwargs);pids.append(p.pid)
            os.kill(os.getpid(),signal.SIGTERM)
            return p
        with patch('frame_veil.process.subprocess.Popen',side_effect=spawn):
            with self.assertRaises(cancellation.Cancelled):
                bounded_run([sys.executable,'-c','import time;time.sleep(5)'],100,2)
        for pid in pids:self.assert_stopped(pid)
    def test_legacy_render_cancellation_removes_scratch(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);scratch=root/'scratch';scratch.mkdir()
            marker=root/'pid';source=root/'fictional.mp4';source.write_bytes(b'fictional-only')
            plan=root/'plan.json';plan.write_text('{}')
            script=r'''
import os,sys,tempfile
from pathlib import Path
from frame_veil import core
root=Path(sys.argv[1]);tempfile.tempdir=str(root/'scratch')
code='import os,time;from pathlib import Path;Path('+repr(str(root/'pid'))+').write_text(str(os.getpid()));time.sleep(10)'
core.probe=lambda *args:core.run('synthetic',['-c',code])
core.executable=lambda name:sys.executable
try:core.render(root/'fictional.mp4',root/'plan.json',root/'out')
except core.Invalid:sys.exit(2)
'''
            proc=subprocess.Popen([sys.executable,'-c',script,str(root)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                deadline=time.monotonic()+3
                while not marker.exists() and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(marker.exists())
                os.kill(proc.pid,signal.SIGTERM)
                out,err=proc.communicate(timeout=5)
                self.assertEqual(proc.returncode,2,(out,err))
                self.assertEqual(list(scratch.iterdir()),[])
                self.assert_stopped(int(marker.read_text()))
                self.assertFalse((root/'out').exists())
            finally:
                if proc.poll() is None:proc.kill();proc.wait()
                if marker.exists():
                    try:os.kill(int(marker.read_text()),signal.SIGKILL)
                    except ProcessLookupError:pass
                proc.stdout.close();proc.stderr.close()

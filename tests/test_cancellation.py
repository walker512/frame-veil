"""Actual process cancellation and sensitive scratch cleanup, fictional inputs only."""
import json,os,shutil,signal,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
from frame_veil import cancellation,core,batch_ocr as batch
from examples.batch_text_synthetic import generate
from examples.ocr_synthetic import FONT
ROOT=Path(__file__).resolve().parents[1]

def running(pid):
    try:
        state=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[0]
        return state!='Z'
    except FileNotFoundError:return False

@unittest.skipUnless(os.name=='posix','POSIX signal handling')
class ScopeTests(unittest.TestCase):
    def test_nested_restores_handlers_on_error(self):
        prior={s:signal.getsignal(s) for s in (signal.SIGINT,signal.SIGTERM)}
        with self.assertRaises(RuntimeError):
            with cancellation.scope() as a:
                with cancellation.scope() as b:
                    self.assertIs(a,b);raise RuntimeError('controlled')
        for s,h in prior.items():self.assertEqual(signal.getsignal(s),h)
    def test_worker_thread_rejected(self):
        errors=[]
        def worker():
            try:
                with cancellation.scope():pass
            except core.Invalid:errors.append(True)
        t=threading.Thread(target=worker);t.start();t.join();self.assertEqual(errors,[True])
    def test_deferred_signal_raises_after_owned_resource(self):
        seen=[]
        with self.assertRaises(cancellation.Cancelled):
            with cancellation.scope() as state:
                with state.defer():
                    os.kill(os.getpid(),signal.SIGTERM)
                    seen.append('resource ownership established')
        self.assertEqual(seen,['resource ownership established'])

@unittest.skipUnless(sys.platform=='linux' and all(shutil.which(t) for t in ('ffmpeg','ffprobe','tesseract')) and Path(FONT).is_file(),'Linux live-process observation and real media tools required; skip is not pass.')
class LiveCancellation(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.scratch=self.root/'scratch';self.scratch.mkdir(mode=0o700);self.marker=self.root/'active.json'
    def launch_and_cancel(self,script,args,sig):
        proc=subprocess.Popen([sys.executable,'-c',script,*map(str,args)],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        pids=[]
        try:
            deadline=time.monotonic()+40
            while proc.poll() is None and time.monotonic()<deadline:
                try:
                    pids=json.loads(self.marker.read_text())
                    break
                except (FileNotFoundError,json.JSONDecodeError):
                    time.sleep(.01)
            self.assertTrue(pids,'worker did not reach active tool')
            self.assertTrue(all(running(pid) for pid in pids),'tools must be active before cancellation')
            os.kill(proc.pid,sig);stdout,stderr=proc.communicate(timeout=10)
            self.assertEqual(proc.returncode,2,(stdout,stderr))
            self.assertNotIn(b'Traceback',stderr)
            deadline=time.monotonic()+5
            while any(running(pid) for pid in pids) and time.monotonic()<deadline:time.sleep(.02)
            self.assertFalse(any(running(pid) for pid in pids),'tool/process-group members survived')
            self.assertEqual(list(self.scratch.iterdir()),[],'sensitive scratch survived catchable cancellation')
        finally:
            if proc.poll() is None:proc.kill();proc.wait()
            for pid in pids:
                if running(pid):
                    try:os.killpg(pid,signal.SIGKILL)
                    except ProcessLookupError:pass
            proc.stdout.close();proc.stderr.close()
    def test_real_ffmpeg_active_sigterm_and_tesseract_active_sigint(self):
        script=r"""
import json,os,random,subprocess,sys,tempfile
from pathlib import Path
from frame_veil import ocr,core,cancellation
marker=Path(sys.argv[1]);scratch=sys.argv[2];tool=sys.argv[3]
old=subprocess.Popen
def popen(*a,**kw):
    p=old(*a,**kw)
    if p.poll() is not None:raise RuntimeError('tool already stopped')
    marker.write_text(json.dumps([p.pid]))
    return p
subprocess.Popen=popen
@cancellation.cancellable
def work():
    with tempfile.TemporaryDirectory(dir=scratch) as td:
        image=Path(td)/'fictional.ppm'
        ocr.private_write(image,bytes([10]).join([b'P6',b'1920 1080',b'255',b''])+random.Random(3).randbytes(1920*1080*3))
        if tool=='ffmpeg':
            args=['-v','error','-nostdin','-re','-f','lavfi','-i','testsrc=size=640x360:rate=30','-t','60','-f','null','-']
        else:args=[str(image),'stdout','-l','eng','--psm','6','tsv']
        ocr.bounded_tool(tool,args,ocr.TSV_LIMIT,60)
try:work()
except core.Invalid:sys.exit(2)
sys.exit(3)
"""
        for tool,sig in [('ffmpeg',signal.SIGTERM),('tesseract',signal.SIGINT)]:
            with self.subTest(tool=tool):
                self.launch_and_cancel(script,[self.marker,self.scratch,tool],sig)
                self.marker.unlink()
    def test_batch_cancel_active_tool_group_cleans_scratch_and_resumes(self):
        media=generate(self.root/'fixture');folder=self.root/'batch'
        batch.initialize(media/'synthetic.mp4',media/'terms.json',media/'regions.json',0,16,folder)
        batch.run(media/'synthetic.mp4',folder,1)
        script=r"""
import json,sys,tempfile
from pathlib import Path
from frame_veil import batch_ocr as b,ocr,core
source,folder,marker,scratch=sys.argv[1:];tempfile.tempdir=scratch
old=ocr.bounded_tool;exe=core.executable
core.executable=lambda name: sys.executable if name=='controlled' else exe(name)
child="import json,os,subprocess,sys,time;from pathlib import Path;p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);Path(sys.argv[1]).write_text(json.dumps([os.getpid(),p.pid]));time.sleep(60)"
def tool(name,args,*a,**kw):
    if name=='tesseract' and 'tsv' in args:
        return old('controlled',['-c',child,marker],100,60)
    return old(name,args,*a,**kw)
ocr.bounded_tool=tool
try:b.run(source,folder,1)
except core.Invalid:sys.exit(2)
sys.exit(3)
"""
        self.launch_and_cancel(script,[media/'synthetic.mp4',folder,self.marker,self.scratch],signal.SIGTERM)
        status=batch.inspect(folder)
        self.assertEqual(status['verified_completed_ranges'],[[0,8]])
        self.assertEqual(status['pending_ranges'],[[8,16]])
        self.assertEqual(status['abandoned_attempts'],0)
        self.assertTrue(batch.run(media/'synthetic.mp4',folder,1)['all_requested_frames_scanned'])

if __name__=='__main__':unittest.main()

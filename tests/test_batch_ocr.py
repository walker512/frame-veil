"""Real bounded resumable scans using only original fictional media."""
import os,shutil,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from frame_veil import core,ocr,region_ocr as reg,batch_ocr as batch
from examples.ocr_synthetic import FONT
from examples.batch_text_synthetic import generate
ROOT=Path(__file__).resolve().parents[1]

class BatchSchema(unittest.TestCase):
    def test_ranges_bounds(self):
        self.assertEqual(batch.ranges(1,30,8),[[1,9],[9,17],[17,25],[25,30]])
        for args in [(0,1800,1),(0,1801,8),(0,10,25),(0,0,8),(True,10,8),(0,10,0)]:
            with self.assertRaises(ValueError):batch.ranges(*args)

@unittest.skipUnless(os.name=='posix' and all(shutil.which(t) for t in ('ffmpeg','ffprobe','tesseract')) and Path(FONT).is_file(),'Local POSIX OCR/media/font required; skip is not pass.')
class BatchReal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        media=generate(cls.root/'fixture')
        cls.source=media/'synthetic.mp4';cls.terms=media/'terms.json';cls.regions=media/'regions.json'
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name);self.folder=self.p/'batch'
    def init(self,end=32,**kwargs):
        return batch.initialize(self.source,self.terms,self.regions,0,end,self.folder,**kwargs)
    def test_real_32_frames_resume_without_repeating_completed(self):
        initialized=self.init();self.assertEqual(initialized['batches'],4)
        first=batch.run(self.source,self.folder,2)
        self.assertEqual(first['verified_completed_ranges'],[[0,8],[8,16]])
        self.assertEqual(first['pending_ranges'],[[16,24],[24,32]])
        original=reg.scan_interval;calls=[]
        def scan(*args,**kw):
            calls.append((args[2],args[3]));return original(*args,**kw)
        with patch.object(reg,'scan_interval',side_effect=scan):
            final=batch.run(self.source,self.folder,8)
        self.assertEqual(calls,[(16,24),(24,32)])
        self.assertTrue(final['all_requested_frames_scanned']);self.assertFalse(final['privacy_complete'])
        self.assertFalse(final['mask_plans_merged']);self.assertEqual(final['pending_ranges'],[])
        hits=set()
        for directory in (self.folder/'chunks').iterdir():
            _,_,found=reg.load_scan(directory);hits.update(c['frame_index'] for c in found)
        self.assertEqual(hits,{1,25})
        with patch.object(reg,'scan_interval',side_effect=AssertionError('no re-scan')):
            self.assertEqual(batch.run(self.source,self.folder,1)['batches_completed_this_run'],0)
    def test_failure_keeps_completed_chunk_and_resume_retries_missing(self):
        self.init(16);original=reg.scan_interval
        def fail(*args,**kw):
            if args[2]==8:raise core.Invalid('controlled interruption')
            return original(*args,**kw)
        with patch.object(reg,'scan_interval',side_effect=fail):
            with self.assertRaises(ValueError):batch.run(self.source,self.folder,2)
        status=batch.inspect(self.folder);self.assertEqual(status['verified_completed_ranges'],[[0,8]])
        self.assertEqual(status['pending_ranges'],[[8,16]])
        self.assertTrue(batch.run(self.source,self.folder,1)['all_requested_frames_scanned'])
    def test_real_process_termination_releases_lock_and_resumes(self):
        self.init(16);marker=self.p/'second-started'
        script="""import sys,time
from pathlib import Path
from frame_veil import batch_ocr as b,region_ocr as r,ocr
old=r.scan_interval
def scan(*a,**kw):
    if a[2]==8:
        ocr.private_write(Path(sys.argv[3]),b'fictional')
        time.sleep(60)
    return old(*a,**kw)
r.scan_interval=scan
b.run(sys.argv[1],sys.argv[2],2)
"""
        proc=subprocess.Popen([sys.executable,'-c',script,str(self.source),str(self.folder),str(marker)],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            deadline=time.monotonic()+30
            while not marker.exists() and proc.poll() is None and time.monotonic()<deadline:time.sleep(.05)
            self.assertTrue(marker.exists())
            proc.terminate();proc.wait(timeout=5)
        finally:
            if proc.poll() is None:proc.kill();proc.wait()
        status=batch.inspect(self.folder)
        self.assertEqual(status['verified_completed_ranges'],[[0,8]])
        self.assertEqual(status['pending_ranges'],[[8,16]])
        self.assertEqual(status['abandoned_attempts'],0)
        self.assertTrue(batch.run(self.source,self.folder,1)['all_requested_frames_scanned'])
    def test_source_config_and_completed_evidence_tampering_fail_closed(self):
        self.init(1);batch.run(self.source,self.folder)
        other=self.p/'changed.mp4';other.write_bytes(self.source.read_bytes()+b' ')
        with self.assertRaises(ValueError):batch.run(other,self.folder)
        config=self.folder/'terms.json';saved=config.read_bytes();config.write_bytes(b'["OTHER"]')
        with self.assertRaises(ValueError):batch.inspect(self.folder)
        config.write_bytes(saved);evidence=self.folder/'chunks/chunk-0000/base-frame-0000.ppm';evidence.write_bytes(evidence.read_bytes()+b'x')
        with self.assertRaises(ValueError):batch.run(self.source,self.folder)
    def test_init_disk_and_region_budgets_before_publication(self):
        with self.assertRaises(ValueError):self.init(max_disk_bytes=1)
        self.assertFalse(self.folder.exists())
        with self.assertRaises(ValueError):self.init(33)
        self.assertFalse(self.folder.exists())
        bad=self.p/'regions';bad.write_bytes(core.canonical([{'id':'r','x':0,'y':0,'width':640,'height':360,'scale':3,'threshold':None}]))
        with self.assertRaises(ValueError):batch.initialize(self.source,self.terms,bad,0,32,self.folder,chunk_size=24)
        self.assertFalse(self.folder.exists())
    def test_active_lock_and_leftover_attempt_are_explicit(self):
        self.init(1)
        with batch.lock(self.folder):
            with self.assertRaises(ValueError):batch.run(self.source,self.folder)
        attempt=self.folder/'.attempt-synthetic';attempt.mkdir(mode=0o700);ocr.private_write(attempt/'partial',b'fictional')
        self.assertEqual(batch.inspect(self.folder)['abandoned_attempts'],1)
        self.assertTrue(batch.run(self.source,self.folder)['all_requested_frames_scanned'])
        self.assertTrue((attempt/'partial').exists())
    def test_cli_private_modes_and_status_no_tools(self):
        args=[sys.executable,'-m','frame_veil.batch_ocr']
        result=subprocess.run(args+['init',str(self.source),'--terms',str(self.terms),'--regions',str(self.regions),'--start','0','--end','1','--out',str(self.folder)],cwd=ROOT,capture_output=True,umask=0)
        self.assertEqual(result.returncode,0,result.stderr)
        result=subprocess.run(args+['run',str(self.source),str(self.folder),'--max-chunks','1'],cwd=ROOT,capture_output=True,umask=0)
        self.assertEqual(result.returncode,0,result.stderr)
        with patch.object(ocr,'bounded_tool',side_effect=AssertionError('offline')):
            self.assertTrue(batch.inspect(self.folder)['all_requested_frames_scanned'])
        for p in [self.folder,*self.folder.rglob('*')]:
            self.assertEqual(p.stat().st_mode&0o777,0o700 if p.is_dir() else 0o600)
        self.assertNotIn(b'NOTICE',result.stdout)
        result=subprocess.run(args+['run',str(self.source),str(self.folder),'--max-chunks','9'],cwd=ROOT,capture_output=True)
        self.assertEqual(result.returncode,2);self.assertNotIn(b'Traceback',result.stderr)
    def test_estimate_is_readonly_and_reports_insufficient_budget(self):
        result=batch.initialize(self.source,self.terms,self.regions,0,32,None,max_disk_bytes=1,estimate_only=True)
        self.assertFalse(result['within_requested_budget']);self.assertFalse(result['scan_started'])
        self.assertFalse(result['initialized']);self.assertGreater(result['estimated_upper_bytes'],1)
        self.assertFalse(self.folder.exists())
        args=[sys.executable,'-m','frame_veil.batch_ocr','estimate',str(self.source),'--terms',str(self.terms),'--regions',str(self.regions),'--start','0','--end','32','--max-disk-bytes','1']
        result=subprocess.run(args,cwd=ROOT,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
    def test_remaining_budget_rejects_abandoned_bytes_without_deleting(self):
        self.init(1)
        plan=core.parse((self.folder/'batch.json').read_bytes())
        attempt=self.folder/'.attempt-synthetic';attempt.mkdir(mode=0o700)
        # Sparse file represents retained storage logically, without allocating a GiB.
        fd=os.open(attempt/'partial',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'wb') as f:f.truncate(plan['max_disk_bytes'])
        with self.assertRaises(ValueError):batch.run(self.source,self.folder)
        self.assertTrue((attempt/'partial').exists())
        self.assertEqual(batch.inspect(self.folder)['verified_completed_ranges'],[])

if __name__=='__main__':unittest.main()

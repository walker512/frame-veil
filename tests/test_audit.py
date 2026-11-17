"""Independent output audit tests using original synthetic media only."""
import hashlib,json,shutil,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from frame_veil.core import audit_masks,verify,render,read,Invalid,canonical,run,input_options
ROOT=Path(__file__).resolve().parents[1]
@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg/ffprobe unavailable; media audit not executed')
class Audit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from examples.synthetic import generate
        cls.tmp=tempfile.TemporaryDirectory();cls.p=Path(cls.tmp.name);generate(cls.p/'source');cls.out=cls.p/'rendered';render(cls.p/'source'/'synthetic.mp4',cls.p/'source'/'plan.json',cls.out)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def copy(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);p=Path(t.name)/'copy';shutil.copytree(self.out,p);return p
    def changed_video(self,x,y,frame=2):
        p=self.copy();out=p.parent/'changed.mkv';run('ffmpeg',['-hide_banner','-loglevel','error','-nostdin',*input_options('matroska'),'-i',str(p/'redacted.mkv'),'-map','0:v:0','-an','-vf',f"drawbox=x={x}:y={y}:w=1:h=1:color=blue:t=fill:enable='eq(n,{frame})'",'-c:v','ffv1','-pix_fmt','bgr0','-threads','1','-fps_mode','passthrough','-f','matroska',str(out)]);(p/'redacted.mkv').write_bytes(out.read_bytes());r=json.loads((p/'receipt.json').read_bytes());r['output_sha256']=hashlib.sha256(out.read_bytes()).hexdigest();(p/'receipt.json').write_bytes(canonical(r));return p
    def test_real_all_declared_pixels_pass(self):
        r=audit_masks(self.out);p=json.loads((self.out/'plan.json').read_bytes());expected=sum((m['end_frame']-m['start_frame'])*m['width']*m['height'] for m in p['masks']);self.assertTrue(r['declared_masks_opaque']);self.assertTrue(r['all_audio_absent']);self.assertEqual(r['decoded_frames'],10);self.assertEqual(r['rectangle_pixel_checks_including_overlap'],expected)
    def test_nonblack_pixel_fails_even_rehashed_receipt(self):
        p=self.changed_video(8,8);self.assertTrue(verify(p)['consistent'])
        with self.assertRaises(Invalid):audit_masks(p)
    def test_wrong_rectangle_plan_fails_even_rehashed_receipt(self):
        p=self.copy();plan=json.loads((p/'plan.json').read_bytes());plan['masks'][0]['x']=70;plan['masks'][0]['width']=10;raw=canonical(plan);(p/'plan.json').write_bytes(raw);r=json.loads((p/'receipt.json').read_bytes());r['plan_sha256']=hashlib.sha256(raw).hexdigest();(p/'receipt.json').write_bytes(canonical(r));self.assertTrue(verify(p)['consistent'])
        with self.assertRaises(Invalid):audit_masks(p)
    def test_outside_changes_not_certified(self):
        p=self.changed_video(0,0);self.assertTrue(audit_masks(p)['declared_masks_opaque'])
    def test_end_exclusive_unmasked_frame_not_rejected(self):
        # First mask ends at 6; its top-left pixel is unmasked on frame 6.
        p=self.changed_video(8,8,6);self.assertTrue(audit_masks(p)['declared_masks_opaque'])
    def test_read_race_plan_rejected(self):
        verified=verify(self.out);real_read=read
        def changed(path,*a,**kw):
            raw=real_read(path,*a,**kw)
            return raw+b' ' if str(path).endswith('plan.json') else raw
        with patch('frame_veil.core.verify',return_value=verified),patch('frame_veil.core.read',side_effect=changed):
            with self.assertRaises(Invalid):audit_masks(self.out)
    def test_real_process_watchdog(self):
        verified=verify(self.out);original=subprocess.Popen
        def sleeper(*a,**kw):return original([sys.executable,'-c','import time;time.sleep(5)'],**kw)
        start=time.monotonic()
        with patch('frame_veil.core.verify',return_value=verified),patch('frame_veil.core.TIMEOUT',0.05),patch('frame_veil.core.subprocess.Popen',side_effect=sleeper):
            with self.assertRaises(Invalid):audit_masks(self.out)
        self.assertLess(time.monotonic()-start,3)
    def test_decoder_short_extra_and_stderr_rejected(self):
        verified=verify(self.out);original=subprocess.Popen;size=96*64*3*10
        for length,diagnostic in ((size-1,''),(size+1,''),(size,'PRIVATE_DIAGNOSTIC')):
            def fake(*a,**kw):return original([sys.executable,'-c',f'import sys;sys.stdout.buffer.write(bytes({length}));sys.stderr.write({diagnostic!r})'],**kw)
            with patch('frame_veil.core.verify',return_value=verified),patch('frame_veil.core.subprocess.Popen',side_effect=fake):
                with self.assertRaises(Invalid) as e:audit_masks(self.out)
                self.assertNotIn('PRIVATE_DIAGNOSTIC',str(e.exception))
    def test_cli_success_and_failure(self):
        for p,code in ((self.out,0),(self.changed_video(8,8),3)):
            r=subprocess.run([sys.executable,'-m','frame_veil','audit-masks',str(p)],cwd=ROOT,capture_output=True,text=True,timeout=15);self.assertEqual(r.returncode,code,r.stderr)
            if code==0:self.assertTrue(json.loads(r.stdout)['declared_masks_opaque'])
            else:
                self.assertNotIn('Traceback',r.stderr);self.assertEqual(json.loads(r.stdout)['first_failure'],{'frame_index':2,'mask_index':0,'pixel_row':8});self.assertFalse(json.loads(r.stdout)['audit_completed'])
if __name__=='__main__':unittest.main()

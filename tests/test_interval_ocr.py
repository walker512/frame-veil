"""Bounded dense sampling of original moving text, not a tracking/recall claim."""
import json,os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from frame_veil import core,ocr,region_ocr as reg,review
from examples.moving_text_synthetic import generate
from examples.ocr_synthetic import FONT
ROOT=Path(__file__).resolve().parents[1]

class IntervalSchema(unittest.TestCase):
    def test_interval_bounds(self):
        self.assertEqual(ocr.interval_indices(0,1),[0])
        self.assertEqual(ocr.interval_indices(1776,1800),list(range(1776,1800)))
        for start,end in [(0,0),(5,4),(-1,2),(0,25),(1799,1801),(True,2),(0,False),(1.0,2)]:
            with self.subTest(start=start,end=end),self.assertRaises(ValueError):ocr.interval_indices(start,end)
    def test_overlarge_interval_rejected_before_read_or_tool(self):
        with patch.object(core,'read',side_effect=AssertionError('no input read')),patch.object(ocr,'bounded_tool',side_effect=AssertionError('no tool')):
            with self.assertRaises(ValueError):ocr.scan_interval('source','terms',0,25,'out')
            with self.assertRaises(ValueError):reg.scan_interval('source','terms',0,25,'regions','out')

@unittest.skipUnless(os.name=='posix' and all(shutil.which(t) for t in ('ffmpeg','ffprobe','tesseract')) and Path(FONT).is_file(),'Local English OCR/media/font required; skip is not pass.')
class MovingText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name);cls.media=generate(cls.root/'fixture')
        cls.source=cls.media/'synthetic.mp4';cls.terms=cls.media/'terms.json';cls.regions=cls.media/'regions.json'
        cls.sparse=cls.root/'sparse';cls.dense=cls.root/'dense'
        reg.scan(cls.source,cls.terms,cls.media/'frames.json',cls.regions,cls.sparse)
        reg.scan_interval(cls.source,cls.terms,0,6,cls.regions,cls.dense)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name)
    def test_true_unsampled_moving_text_recovered(self):
        _,_,sparse=reg.load_scan(self.sparse);self.assertEqual(sparse,[])
        files,m,dense=reg.load_scan(self.dense)
        self.assertEqual(m['indexes'],list(range(6)))
        hits=[c for c in dense if c['origin']=='region']
        self.assertEqual({c['frame_index'] for c in hits},{1,2,4})
        self.assertEqual(len({c['box']['x'] for c in hits}),3)
        for i in range(6):self.assertIn('base-'+ocr.names(i)[0],files)
        report=reg.coverage(self.dense);self.assertEqual(report['unsampled_frame_ranges'],[])
        self.assertEqual(report['terms'][0]['sampled_frames_without_exact_match'],[0,3,5])
        self.assertFalse(report['privacy_complete']);self.assertTrue(report['manual_full_output_review_required'])
    def test_prepare_decide_render_audit_still_pending_review(self):
        decision=self.p/'decisions.json';reg.prepare(self.dense,decision)
        data=core.parse(decision.read_bytes());self.assertTrue(all(r['decision']=='pending' for r in data['decisions']))
        _,_,found=reg.load_scan(self.dense)
        for row,c in zip(data['decisions'],found):
            row.update(decision='accept',note='Synthetic observed frame only, no tracking inference.',mask={'start_frame':c['frame_index'],'end_frame':c['frame_index']+1,**c['box']})
        decision.write_bytes(core.canonical(data));reg.plan(self.source,self.dense,decision,self.p/'plan')
        core.render(self.source,self.p/'plan/plan.json',self.p/'render')
        audit=core.audit_masks(self.p/'render');self.assertTrue(audit['declared_masks_opaque']);self.assertEqual(audit['marked_frames'],3)
        review.prepare(self.p/'render','silent',self.p/'review.json')
        self.assertEqual(core.parse((self.p/'review.json').read_bytes())['items'][0]['checks']['names_and_text'],'pending')
    def test_both_real_cli_interval_entries_and_exclusivity(self):
        for module in ('frame_veil.ocr','frame_veil.region_ocr'):
            args=[sys.executable,'-m',module,'scan',str(self.source),'--terms',str(self.terms),'--frame-range','1','3','--out',str(self.p/module)]
            if module.endswith('region_ocr'):args+=['--regions',str(self.regions),'--pair-unthresholded']
            result=subprocess.run(args,cwd=ROOT,capture_output=True,umask=0)
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout)['sampled_frames'],2)
            self.assertEqual((self.p/module).stat().st_mode&0o777,0o700)
            for p in (self.p/module).iterdir():self.assertEqual(p.stat().st_mode&0o777,0o600)
            result=subprocess.run(args+['--frames',str(self.media/'frames.json')],cwd=ROOT,capture_output=True)
            self.assertEqual(result.returncode,2)
    def test_execution_and_source_bounds_no_partial_output(self):
        r=core.parse(self.regions.read_bytes());r[0]['threshold']=110
        config=self.p/'regions';config.write_bytes(core.canonical(r))
        with patch.object(ocr,'bounded_tool',side_effect=AssertionError('no tool')):
            with self.assertRaises(ValueError):reg.scan_interval(self.source,self.terms,0,24,config,self.p/'too-many',True)
        self.assertFalse((self.p/'too-many').exists())
        with self.assertRaises(ValueError):reg.scan_interval(self.source,self.terms,4,8,self.regions,self.p/'past-end')
        self.assertFalse((self.p/'past-end').exists())

if __name__=='__main__':unittest.main()

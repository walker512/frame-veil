"""Original synthetic moving notice; real OCR, composed plans and rendered pixels."""
import copy,os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from frame_veil import core,ocr,region_ocr as reg,batch_ocr as batch,merge_plans as merge
from examples.batch_text_synthetic import generate
from examples.ocr_synthetic import FONT
ROOT=Path(__file__).resolve().parents[1]

class SelectionTests(unittest.TestCase):
    def test_missing_ranges(self):
        self.assertEqual(merge.missing_ranges({0,1,3,5},7),[[2,3],[4,5],[6,7]])
        self.assertEqual(merge.missing_ranges(set(),3),[[0,3]])
    def test_selection_schema(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'selection'
            for data in ([],{},[{'scan':'x'}],[{'scan':'x','plan':''}],[{'scan':'x','plan':'\n'}],[{'scan':'x','plan':True}],[{'scan':'x','plan':'y'}]*17):
                p.write_bytes(core.canonical(data))
                with self.assertRaises(ValueError):merge.selection(p)

@unittest.skipUnless(os.name=='posix' and all(shutil.which(t) for t in ('ffmpeg','ffprobe','tesseract')) and Path(FONT).is_file(),'Local POSIX OCR/media/font required; skipped is not passed.')
class MergeReal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        fixture=generate(cls.root/'fixture');cls.source=fixture/'synthetic.mp4';cls.batch=cls.root/'batch'
        batch.initialize(cls.source,fixture/'terms.json',fixture/'regions.json',0,32,cls.batch)
        batch.run(cls.source,cls.batch,8)
        cls.pairs=[]
        for index in (0,3):
            scan=cls.batch/'chunks'/f'chunk-{index:04d}';files,m,found=reg.load_scan(scan)
            decisions={'schema':1,'scan_manifest_sha256':ocr.sha(files['manifest.json']),'source_sha256':m['source_sha256'],'decisions':[]}
            for candidate in found:
                decisions['decisions'].append({'id':candidate['id'],'decision':'accept','note':'Synthetic fixture, explicitly accepted for test.','mask':{'start_frame':candidate['frame_index'],'end_frame':candidate['frame_index']+1,**candidate['box']}})
            dp=cls.root/f'decisions-{index}.json';dp.write_bytes(core.canonical(decisions));plan=cls.root/f'plan-{index}'
            reg.plan(cls.source,scan,dp,plan);cls.pairs.append({'scan':str(scan),'plan':str(plan)})
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name)
        self.selection=self.p/'selection.json';self.selection.write_bytes(core.canonical(self.pairs));self.out=self.p/'merged'
    def test_real_merge_render_and_pixel_audit(self):
        result=merge.merge(self.source,self.selection,self.out)
        self.assertFalse(result['privacy_complete']);self.assertEqual(result['unobserved_by_selected_scans_ranges'],[[8,24]])
        self.assertEqual(result['frames_without_any_declared_mask_ranges'],[[0,1],[2,25],[26,32]])
        plan=core.parse((self.out/'plan.json').read_bytes());self.assertEqual({m['start_frame'] for m in plan['masks']},{1,25})
        rendered=self.p/'rendered';core.render(self.source,self.out/'plan.json',rendered)
        audit=core.audit_masks(rendered);self.assertTrue(audit['declared_masks_opaque']);self.assertEqual(audit['marked_frames'],2)
        self.assertTrue(merge.verify(self.source,self.selection,self.out)['composition_revalidated'])
    def test_missing_batch_never_privacy_clearance(self):
        self.selection.write_bytes(core.canonical(self.pairs[:1]));r=merge.merge(self.source,self.selection,self.out)
        self.assertEqual(r['unobserved_by_selected_scans_ranges'],[[8,32]])
        self.assertFalse(r['privacy_complete']);self.assertTrue(r['manual_full_output_review_required'])
    def test_tampered_plan_receipt_or_decision_rejected(self):
        for name in ('plan.json','receipt.json','decisions.json'):
            with self.subTest(name=name):
                plan=self.p/name.replace('.json','');shutil.copytree(self.pairs[0]['plan'],plan)
                path=plan/name;value=core.parse(path.read_bytes())
                if name=='plan.json':value['masks'][0]['x']=0
                elif name=='receipt.json':value['scope']='tampered'
                else:value['decisions'][0]['decision']='pending'
                path.write_bytes(core.canonical(value));self.selection.write_bytes(core.canonical([{'scan':self.pairs[0]['scan'],'plan':str(plan)}]))
                with self.assertRaises(ValueError):merge.merge(self.source,self.selection,self.out)
                self.assertFalse(self.out.exists())
    def test_source_mismatch_and_duplicate_scan_rejected(self):
        changed=self.p/'changed.mp4';changed.write_bytes(self.source.read_bytes()+b'x')
        with self.assertRaises(ValueError):merge.merge(changed,self.selection,self.out)
        self.selection.write_bytes(core.canonical(self.pairs[:1]*2))
        with self.assertRaises(ValueError):merge.merge(self.source,self.selection,self.out)
        self.assertFalse(self.out.exists())
    def test_merge_bundle_tampering(self):
        merge.merge(self.source,self.selection,self.out)
        for name in ('plan.json','merge-receipt.json','input-0000-decisions.json'):
            p=self.out/name;original=p.read_bytes();p.write_bytes(original+b' ')
            with self.assertRaises(ValueError):merge.verify(self.source,self.selection,self.out)
            p.write_bytes(original)
        (self.out/'unexpected').write_bytes(b'')
        with self.assertRaises(ValueError):merge.verify(self.source,self.selection,self.out)
    def test_private_outputs_and_existing_destination(self):
        for mask in (0o022,0o000):
            out=self.p/str(mask);old=os.umask(mask)
            try:merge.merge(self.source,self.selection,out)
            finally:os.umask(old)
            self.assertEqual(out.stat().st_mode&0o777,0o700)
            for f in out.iterdir():self.assertEqual(f.stat().st_mode&0o777,0o600)
            with self.assertRaises(ValueError):merge.merge(self.source,self.selection,out)
    def test_offline_verify_calls_no_tools(self):
        merge.merge(self.source,self.selection,self.out)
        with patch.object(ocr,'bounded_tool',side_effect=AssertionError('must not invoke OCR or media tools')):
            self.assertTrue(merge.verify(self.source,self.selection,self.out)['composition_revalidated'])
    def test_relative_selection_and_cli(self):
        self.selection.write_bytes(core.canonical([{'scan':os.path.relpath(row['scan'],self.p),'plan':os.path.relpath(row['plan'],self.p)} for row in self.pairs]))
        p=subprocess.run([sys.executable,'-m','frame_veil.merge_plans','create',str(self.source),str(self.selection),'--out',str(self.out)],cwd=ROOT,capture_output=True)
        self.assertEqual(p.returncode,0,p.stderr);self.assertNotIn(b'NOTICE',p.stdout)
        p=subprocess.run([sys.executable,'-m','frame_veil.merge_plans','verify',str(self.source),str(self.selection),str(self.out)],cwd=ROOT,capture_output=True)
        self.assertEqual(p.returncode,0,p.stderr)

    def test_mask_limit_fails_before_output(self):
        original=core.load_plan
        def expanded(raw,info):
            value=original(raw,info)
            return {**value,'masks':value['masks']*51}
        with patch.object(core,'load_plan',side_effect=expanded):
            with self.assertRaises(ValueError):merge.merge(self.source,self.selection,self.out)
        self.assertFalse(self.out.exists())

    def test_selected_plan_symlink_rejected(self):
        plan=self.p/'linked-plan';shutil.copytree(self.pairs[0]['plan'],plan)
        target=plan/'plan.json';target.unlink();target.symlink_to(Path(self.pairs[0]['plan'])/'plan.json')
        self.selection.write_bytes(core.canonical([{'scan':self.pairs[0]['scan'],'plan':str(plan)}]))
        with self.assertRaises(ValueError):merge.merge(self.source,self.selection,self.out)
        self.assertFalse(self.out.exists())

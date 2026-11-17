"""Synthetic-only actual media review/export checks; no claim a human watched it."""
import copy,json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from frame_veil import review,core,audio
ROOT=Path(__file__).resolve().parents[1]
@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg unavailable: media workflow not executed')
class ReviewMedia(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from examples.selective_audio import generate_audio as generate
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name);generate(cls.root/'demo')
        # Public generator writes only source and plans, not a rendered bundle.
        cls.bundle=cls.root/'bundle'
        audio.render_audio(cls.root/'demo'/'synthetic.mp4',cls.root/'demo'/'plan.json',cls.root/'demo'/'audio-plan.json',cls.bundle)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name);self.record=self.p/'record.json'
        review.prepare(self.bundle,'audio',self.record);self.value=json.loads(self.record.read_bytes())
    def full(self):
        value=copy.deepcopy(self.value)
        for i in value['items']:
            for k in i['checks']:i['checks'][k]='reviewed'
        self.record.write_bytes(core.canonical(value));return value
    def test_generated_coverage_exact_all_pending(self):
        for kind,total in [('video',self.value['video_frames']),('audio',self.value['audio']['samples'])]:
            items=[i for i in self.value['items'] if i['kind']==kind]
            self.assertEqual(items[0]['start'],0);self.assertEqual(items[-1]['end'],total)
            self.assertTrue(all(a['end']==b['start'] for a,b in zip(items,items[1:])))
            self.assertTrue(all(v=='pending' for i in items for v in i['checks'].values()))
    def test_pending_and_blocked_no_output(self):
        for state in ('pending','blocked'):
            value=self.full();value['items'][0]['checks']['names_and_text']=state;self.record.write_bytes(core.canonical(value))
            with self.assertRaises(core.Invalid):review.export(self.bundle,self.record,self.p/'export',True)
            self.assertFalse((self.p/'export').exists())
    def test_actual_export_same_media_and_scope(self):
        self.full();result=review.export(self.bundle,self.record,self.p/'export',True)
        self.assertEqual((self.p/'export'/'reviewed.mkv').read_bytes(),(self.bundle/'review.mkv').read_bytes())
        self.assertFalse(result['privacy_certified']);self.assertFalse(result['publication_authorized'])
        self.assertEqual(set(p.name for p in (self.p/'export').iterdir()),{'reviewed.mkv','human-review.json','SCOPE.txt'})
    def test_ack_exact_true_and_no_overwrite(self):
        self.full()
        for ack in (False,1,'true'):
            with self.assertRaises(core.Invalid):review.export(self.bundle,self.record,self.p/'export',ack)
        (self.p/'export').mkdir();(self.p/'export'/'keep').write_text('keep')
        with self.assertRaises(FileExistsError):review.export(self.bundle,self.record,self.p/'export',True)
        self.assertEqual((self.p/'export'/'keep').read_text(),'keep')
    def test_decision_new_file_not_bulk_confirmation(self):
        out=self.p/'next.json';review.decide(self.bundle,self.record,'video-0','names_and_text','reviewed',out)
        value=json.loads(out.read_bytes());self.assertEqual(value['items'][0]['checks']['names_and_text'],'reviewed');self.assertEqual(json.loads(self.record.read_bytes()),self.value)
        with self.assertRaises(core.Invalid):review.export(self.bundle,out,self.p/'export',True)
    def test_missing_reordered_range_and_type_tampering(self):
        for mutate in (lambda x:x['items'].pop(),lambda x:x['items'].reverse(),lambda x:x['items'][0].update(start=True),lambda x:x.update(schema=True),lambda x:x['items'][0]['checks'].pop('names_and_text')):
            value=self.full();mutate(value);self.record.write_bytes(core.canonical(value))
            with self.assertRaises(core.Invalid):review.export(self.bundle,self.record,self.p/'export',True)
    def test_changed_plan_bytes_even_same_meaning_invalidate(self):
        self.full();bundle=self.p/'bundle';shutil.copytree(self.bundle,bundle)
        plan=bundle/'audio-plan.json';plan.write_bytes(plan.read_bytes()+b'\n');receipt=json.loads((bundle/'receipt.json').read_bytes());receipt['audio_plan_sha256']=audio.sha(plan.read_bytes());(bundle/'receipt.json').write_bytes(core.canonical(receipt))
        with self.assertRaises(core.Invalid):review.export(bundle,self.record,self.p/'export',True)
        self.assertFalse((self.p/'export').exists())
    def test_invalid_media_does_not_get_review(self):
        bundle=self.p/'bundle';shutil.copytree(self.bundle,bundle);(bundle/'review.mkv').write_bytes(b'bad')
        with self.assertRaises(core.Invalid):review.prepare(bundle,'audio',self.p/'bad.json')
        self.assertFalse((self.p/'bad.json').exists())
    def test_silent_workflow_real(self):
        record=self.p/'silent.json';review.prepare(self.bundle/'video','silent',record);value=json.loads(record.read_bytes());self.assertIsNone(value['audio']);self.assertTrue(all(i['kind']=='video' for i in value['items']))
        for i in value['items']:
            for k in i['checks']:i['checks'][k]='reviewed'
        record.write_bytes(core.canonical(value));review.export(self.bundle/'video',record,self.p/'silent',True)
        self.assertEqual((self.p/'silent'/'reviewed.mkv').read_bytes(),(self.bundle/'video'/'redacted.mkv').read_bytes())
    def test_non_object_and_unknown_decision(self):
        self.record.write_bytes(b'[]')
        with self.assertRaises(core.Invalid):review.decide(self.bundle,self.record,'video-0','names_and_text','reviewed',self.p/'out')
        self.record.write_bytes(core.canonical(self.value))
        with self.assertRaises(core.Invalid):review.decide(self.bundle,self.record,'video-0','names_and_text','yes',self.p/'out')
    def test_real_cli_pending_controlled(self):
        p=subprocess.run([sys.executable,'-m','frame_veil','review-export',str(self.bundle),str(self.record),'--acknowledge-human-review','--out',str(self.p/'export')],cwd=ROOT,capture_output=True)
        self.assertEqual(p.returncode,2);self.assertNotIn(b'Traceback',p.stderr);self.assertFalse((self.p/'export').exists())

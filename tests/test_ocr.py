"""Original fictional text video and real local English OCR; no private media/network."""
import copy,json,os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from frame_veil import ocr,core,review
from examples.ocr_synthetic import generate,FONT
ROOT=Path(__file__).resolve().parents[1]
HEADER='level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
def tsv(words):return (HEADER+''.join('\t'.join(map(str,[5,1,1,1,line,word,x,10,20,10,conf,text]))+'\n' for line,word,x,conf,text in words)).encode()
@unittest.skipUnless(os.name=='posix' and shutil.which('ffmpeg') and shutil.which('ffprobe') and shutil.which('tesseract') and Path(FONT).is_file(),'Local English OCR media tools/font required; skip is not pass.')
class RealOCRTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name);cls.media=generate(cls.root/'fixture');cls.scan=cls.root/'scan';ocr.scan(cls.media/'synthetic.mp4',cls.media/'terms.json',cls.media/'frames.json',cls.scan)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name);self.source=self.media/'synthetic.mp4'
    def decisions(self):
        f=self.p/'decisions.json';ocr.prepare(self.scan,f);d=core.parse(f.read_bytes());_,m,c=ocr.load_scan(self.scan)
        for row,item in zip(d['decisions'],c):row.update(decision='accept',note='Synthetic explicit one-frame interval, not a claim of viewing.',mask={'start_frame':item['frame_index'],'end_frame':item['frame_index']+1,**item['box']})
        f.write_bytes(core.canonical(d));return f
    def test_legacy_cli_artifacts_private_under_permissive_umasks(self):
        args=[sys.executable,'-m','frame_veil.ocr']
        for mask in (0o022,0):
            base=self.p/str(mask);base.mkdir();scan=base/'scan';decision=base/'decisions.json';plan=base/'plan'
            def run(argv):
                result=subprocess.run(args+argv,cwd=ROOT,capture_output=True,umask=mask)
                self.assertEqual(result.returncode,0,result.stderr)
            run(['scan',str(self.source),'--terms',str(self.media/'terms.json'),'--frames',str(self.media/'frames.json'),'--out',str(scan)])
            run(['prepare',str(scan),'--out',str(decision)])
            d=core.parse(decision.read_bytes());_,_,found=ocr.load_scan(scan)
            for row,c in zip(d['decisions'],found):
                row.update(decision='accept',note='Fictional private review note',mask={'start_frame':c['frame_index'],'end_frame':c['frame_index']+1,**c['box']})
            decision.write_bytes(core.canonical(d))
            run(['plan',str(self.source),str(scan),str(decision),'--out',str(plan)])
            for directory in (scan,plan):
                self.assertEqual(directory.stat().st_mode&0o777,0o700)
                for artifact in directory.iterdir():self.assertEqual(artifact.stat().st_mode&0o777,0o600,artifact.name)
            self.assertEqual(decision.stat().st_mode&0o777,0o600)
            before=decision.read_bytes()
            result=subprocess.run(args+['prepare',str(scan),'--out',str(decision)],cwd=ROOT,capture_output=True,umask=mask)
            self.assertEqual(result.returncode,2);self.assertEqual(decision.read_bytes(),before)
    def test_actual_ocr_candidates(self):
        files,m,c=ocr.load_scan(self.scan);self.assertEqual(m['indexes'],[0,3]);self.assertEqual(m['info']['frames'],6);self.assertTrue(c);self.assertEqual({x['frame_index'] for x in c},{0,3});self.assertTrue(any(x['term_index']==0 for x in c));self.assertFalse(m['privacy_complete']);self.assertTrue(all(x['words'] for x in c))
    def test_render_audit_and_human_review(self):
        f=self.decisions();ocr.plan(self.source,self.scan,f,self.p/'plan');core.render(self.source,self.p/'plan'/'plan.json',self.p/'render');r=core.audit_masks(self.p/'render');self.assertTrue(r['declared_masks_opaque']);self.assertEqual(r['marked_frames'],2);review.prepare(self.p/'render','silent',self.p/'human.json');self.assertTrue((self.p/'human.json').exists());self.assertEqual(core.parse((self.p/'human.json').read_bytes())['items'][0]['checks']['names_and_text'],'pending')
    def test_sample_pixels_and_unselected_frame_preserved(self):
        def rgb(path,fmt):return ocr.bounded_tool('ffmpeg',['-v','error','-nostdin',*core.input_options(fmt),'-i',str(path),'-an','-sn','-dn','-threads','1','-pix_fmt','rgb24','-f','rawvideo','pipe:1'],6*640*360*3,30,strict_stderr=True)[0]
        original=rgb(self.source,'mov');files,m,c=ocr.load_scan(self.scan);size=640*360*3
        self.assertEqual(files['frame-0003.ppm'].split(b'\n',3)[3],original[3*size:4*size])
        ocr.plan(self.source,self.scan,self.decisions(),self.p/'plan');core.render(self.source,self.p/'plan'/'plan.json',self.p/'render');out=rgb(self.p/'render'/'redacted.mkv','matroska');self.assertEqual(original[size:2*size],out[size:2*size]);self.assertEqual(original[4*size:5*size],out[4*size:5*size])
    def test_all_files_tamper_and_extra(self):
        scan=self.p/'scan';shutil.copytree(self.scan,scan)
        for f in scan.iterdir():
            b=f.read_bytes();f.write_bytes(b+b' ')
            with self.assertRaises(ValueError):ocr.load_scan(scan)
            f.write_bytes(b)
        (scan/'extra').write_text('unexpected')
        with self.assertRaises(ValueError):ocr.load_scan(scan)
    def test_candidate_rehash_does_not_hide_tsv_mismatch(self):
        scan=self.p/'scan';shutil.copytree(self.scan,scan);p=scan/'candidates.json';c=core.parse(p.read_bytes());c[0]['box']['x']+=1;p.write_bytes(core.canonical(c));m=core.parse((scan/'manifest.json').read_bytes());m['files']['candidates.json']=ocr.sha(p.read_bytes());(scan/'manifest.json').write_bytes(core.canonical(m))
        with self.assertRaises(ValueError):ocr.load_scan(scan)
    def test_pending_missing_dismiss_all(self):
        f=self.p/'d.json';ocr.prepare(self.scan,f)
        with self.assertRaises(ValueError):ocr.plan(self.source,self.scan,f,self.p/'plan')
        d=core.parse(f.read_bytes());d['decisions']=[];f.write_bytes(core.canonical(d))
        with self.assertRaises(ValueError):ocr.plan(self.source,self.scan,f,self.p/'plan')
        f.unlink();ocr.prepare(self.scan,f);d=core.parse(f.read_bytes())
        for row in d['decisions']:row.update(decision='dismiss',note='Synthetic false positive')
        f.write_bytes(core.canonical(d))
        with self.assertRaises(ValueError):ocr.plan(self.source,self.scan,f,self.p/'plan')
    def test_mask_cannot_skip_hit_or_shrink_box(self):
        f=self.decisions();original=f.read_bytes()
        for k,v in (('width',1),('start_frame',1),('x',True)):
            d=core.parse(original);d['decisions'][0]['mask'][k]=v;f.write_bytes(core.canonical(d))
            with self.assertRaises(ValueError):ocr.plan(self.source,self.scan,f,self.p/'plan')
    def test_binding_changed_source_or_manifest(self):
        f=self.decisions();copy=self.p/'source.mp4';copy.write_bytes(self.source.read_bytes()+b' ')
        with self.assertRaises(ValueError):ocr.plan(copy,self.scan,f,self.p/'plan')
        d=core.parse(f.read_bytes());d['scan_manifest_sha256']='0'*64;f.write_bytes(core.canonical(d))
        with self.assertRaises(ValueError):ocr.plan(self.source,self.scan,f,self.p/'plan')
    def test_failure_does_not_publish_completed_scan(self):
        with patch.object(ocr,'bounded_tool',side_effect=core.Invalid('synthetic failure')):
            with self.assertRaises(ValueError):ocr.scan(self.source,self.media/'terms.json',self.media/'frames.json',self.p/'failed')
        self.assertFalse((self.p/'failed').exists())
    def test_zero_hits_not_clearance(self):
        t=self.p/'terms.json';t.write_bytes(core.canonical(['UNLIKELYTOKENXYZ']));r=ocr.scan(self.source,t,self.media/'frames.json',self.p/'zero');self.assertEqual(r['candidate_count'],0);self.assertFalse(r['privacy_complete']);ocr.prepare(self.p/'zero',self.p/'d.json')
        with self.assertRaises(ValueError):ocr.plan(self.source,self.p/'zero',self.p/'d.json',self.p/'plan')
    def test_real_cli(self):
        args=[sys.executable,'-m','frame_veil.ocr'];p=subprocess.run(args+['verify',str(self.scan)],cwd=ROOT,capture_output=True);self.assertEqual(p.returncode,0)
        p=subprocess.run(args+['prepare',str(self.scan),'--out',str(self.p/'d.json')],cwd=ROOT,capture_output=True);self.assertEqual(p.returncode,0)
        p=subprocess.run(args+['plan',str(self.source),str(self.scan),str(self.p/'d.json'),'--out',str(self.p/'plan')],cwd=ROOT,capture_output=True);self.assertEqual(p.returncode,2)
    def test_special_files_and_existing_output(self):
        f=self.p/'link';f.symlink_to(self.media/'terms.json')
        with self.assertRaises(ValueError):ocr.scan(self.source,f,self.media/'frames.json',self.p/'scan')
        with self.assertRaises(ValueError):ocr.scan(self.source,self.media/'terms.json',self.media/'frames.json',self.scan)
        if hasattr(os,'mkfifo'):
            f.unlink();os.mkfifo(f)
            with self.assertRaises(ValueError):ocr.scan(self.source,f,self.media/'frames.json',self.p/'scan')
    def test_nonobject_manifest_cli_controlled(self):
        scan=self.p/'bad';scan.mkdir()
        for d in ([],None,'text'):
            (scan/'manifest.json').write_bytes(core.canonical(d))
            p=subprocess.run([sys.executable,'-m','frame_veil.ocr','verify',str(scan)],cwd=ROOT,capture_output=True)
            self.assertEqual(p.returncode,2);self.assertNotIn(b'Traceback',p.stderr)
    def test_selected_rgb_budget_precedes_decode_ocr(self):
        f=self.p/'frames.json';f.write_bytes(core.canonical(list(range(24))))
        with patch.object(ocr,'probe',return_value={'width':1920,'height':1080,'frames':24,'codec':'h264'}),patch.object(ocr,'bounded_tool',side_effect=AssertionError('no tool after budget rejection')):
            with self.assertRaises(ValueError):ocr.scan(self.source,self.media/'terms.json',f,self.p/'scan')
        self.assertFalse((self.p/'scan').exists())
    def test_truncated_selected_decode_not_completed(self):
        original=ocr.bounded_tool
        def tool(name,args,*a,**kw):
            if name=='ffmpeg' and '-f' in args:return b'',{'stderr_bytes':0,'stderr_sha256':ocr.sha(b'')}
            return original(name,args,*a,**kw)
        with patch.object(ocr,'bounded_tool',side_effect=tool):
            with self.assertRaises(ValueError):ocr.scan(self.source,self.media/'terms.json',self.media/'frames.json',self.p/'scan')
        self.assertFalse((self.p/'scan').exists())
    def test_explicit_longer_interval_is_human_not_inferred(self):
        f=self.decisions();d=core.parse(f.read_bytes())
        for row in d['decisions']:row['mask'].update(start_frame=0,end_frame=6)
        f.write_bytes(core.canonical(d));ocr.plan(self.source,self.scan,f,self.p/'plan')
        p=core.parse((self.p/'plan'/'plan.json').read_bytes());self.assertTrue(all(m['end_frame']==6 for m in p['masks']));self.assertEqual(core.parse((self.p/'plan'/'receipt.json').read_bytes())['manual_interval_declarations'],True)
    def test_verify_no_external_process(self):
        with patch.object(subprocess,'Popen',side_effect=AssertionError('must not launch')):ocr.load_scan(self.scan)

class OCRSchemaTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='posix','POSIX mode semantics')
    def test_private_writer_exclusive_and_symlink_safe(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'artifact';old=os.umask(0)
            try:ocr.private_write(path,b'fictional')
            finally:os.umask(old)
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            with self.assertRaises(FileExistsError):ocr.private_write(path,b'changed')
            link=Path(td)/'link';link.symlink_to(path)
            with self.assertRaises(FileExistsError):ocr.private_write(link,b'changed')
            self.assertEqual(path.read_bytes(),b'fictional')
    def test_contiguous_same_line_only(self):
        raw=tsv([(1,1,0,'90','Alice'),(1,2,25,'80','Sample')]);c=ocr.candidates(raw,['ALICE SAMPLE'],0,100,100);self.assertEqual(len(c),1);self.assertEqual(c[0]['box'],{'x':0,'y':10,'width':45,'height':10})
        self.assertEqual(ocr.candidates(tsv([(1,1,0,'90','Alice'),(2,1,25,'80','Sample')]),['Alice Sample'],0,100,100),[])
        self.assertEqual(ocr.candidates(tsv([(1,1,0,'90','Alice'),(1,3,25,'80','Sample')]),['Alice Sample'],0,100,100),[])
    def test_no_substring_fuzzy_or_confidence_filter(self):
        raw=tsv([(1,1,0,'0.1','Alice')]);self.assertEqual(len(ocr.candidates(raw,['alice'],0,100,100)),1);self.assertEqual(ocr.candidates(raw,['Ali'],0,100,100),[])
    def test_malformed_tsv(self):
        for raw in (b'bad',tsv([(1,1,90,'90','Alice')]),tsv([(1,1,0,'NaN','Alice')]),tsv([(1,1,0,'Infinity','Alice')]),tsv([(1,1,0,'101','Alice')]),tsv([(1,1,0,'-1','Alice')]),tsv([(1,1,0,'90','Alice'),(1,1,25,'90','Sample')]),b'x'*(ocr.TSV_LIMIT+1), (HEADER+'x'*200000).encode()):
            with self.assertRaises(ValueError):ocr.candidates(raw,['Alice'],0,100,100)
    def test_terms_indices(self):
        for d in ([],['Alice','alice'],['a\nb'],['x'*201],['a']*21):
            with self.assertRaises(ValueError):ocr.terms(core.canonical(d))
        for d in ([],[True],[0,0],[3,0],[1800],list(range(25))):
            with self.assertRaises(ValueError):ocr.indices(core.canonical(d))
        self.assertEqual(ocr.terms(core.canonical(['Straße'])),['Straße'])
    def test_ppm_exact_layout(self):
        ocr.ppm(b'P6\n2 2\n255\n'+b'\0'*12,2,2)
        for b in (b'P6\n2 2\n255\n'+b'\0'*11,b'P3\n2 2\n255\n'+b'\0'*12):
            with self.assertRaises(ValueError):ocr.ppm(b,2,2)
    @unittest.skipUnless(os.name=='posix','POSIX runner')
    def test_real_runner_timeout_output_and_error(self):
        with patch.object(core,'executable',return_value=sys.executable):
            for args,cap,timeout in ((['-c','import time;time.sleep(5)'],100,.1),(['-c',"print('x'*1000)"],10,2),(['-c','raise RuntimeError("synthetic")'],100,2),(['-c',"import sys;sys.stderr.write('x'*70000)"],100,2)):
                with self.assertRaises(ValueError):ocr.bounded_tool('test',args,cap,timeout)
    def test_strict_json(self):
        for raw in (b'[NaN]',b'[1.5]',b'["\\ud800"]',b'{"x":1,"x":2}'):
            with self.assertRaises(ValueError):core.parse(raw)
if __name__=='__main__':unittest.main()

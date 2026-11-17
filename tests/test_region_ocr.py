"""Real synthetic OCR and deterministic region evidence regressions, never private video."""
import copy, json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from frame_veil import core, ocr, region_ocr as reg, review
from examples.region_ocr_synthetic import generate
from examples.ocr_synthetic import FONT
ROOT = Path(__file__).resolve().parents[1]
R = {'id':'notice','x':20,'y':180,'width':600,'height':70,'scale':2,'threshold':None}
HEADER = b'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'

def rehash(files):
    m=core.parse(files['manifest.json']);m['files']={n:ocr.sha(b) for n,b in files.items() if n!='manifest.json'};files['manifest.json']=core.canonical(m)

class RegionSchemaTests(unittest.TestCase):
    def test_paired_config_preserves_and_deduplicates_controls(self):
        request=[{**R,'id':'control-1','threshold':180},{**R,'id':'other','threshold':110}]
        result=reg.paired_regions(core.canonical(request))
        self.assertEqual(result[:2],request);self.assertEqual(len(result),3)
        self.assertEqual(result[2],{**R,'id':'control-2','threshold':None})
        self.assertEqual(reg.paired_regions(core.canonical(result)),result)
        self.assertEqual(reg.paired_regions(core.canonical([R])),[R])
    def test_pair_expansion_bound_rejects_without_tools(self):
        request=[{**R,'id':'r'+str(i),'x':i,'width':10,'threshold':180} for i in range(5)]
        with self.assertRaises(ValueError):reg.paired_regions(core.canonical(request))
    def test_strict_regions(self):
        for k,v in [('x',True),('y',-1),('width',0),('height',1081),('scale',4),('scale',True),('threshold',True),('threshold',256),('id','../x')]:
            r={**R,k:v}
            with self.subTest(k=k,v=v),self.assertRaises(ValueError):reg.regions(core.canonical([r]))
        for d in [[],[R]*2,[{**R,'extra':0}],None,[{k:v for k,v in R.items() if k!='threshold'}]]:
            with self.assertRaises(ValueError):reg.regions(core.canonical(d))
        with self.assertRaises(ValueError):reg.regions(core.canonical([R]),{'width':600,'height':200})
    def test_pixel_oracle_and_threshold_boundaries(self):
        rgb=bytes([10,20,30, 100,100,100, 255,255,255, 0,0,0]);raw=b'P6\n2 2\n255\n'+rgb
        r={'id':'a','x':1,'y':0,'width':1,'height':2,'scale':2,'threshold':100}
        self.assertEqual(reg.preprocess(raw,2,2,r),b'P6\n2 4\n255\n'+b'\xff'*12+b'\0'*12)
        r.update(x=0,y=0,width=2,height=2,scale=1,threshold=None)
        self.assertEqual(reg.preprocess(raw,2,2,r),raw)
        r['threshold']=0;self.assertEqual(reg.preprocess(raw,2,2,r).split(b'\n',3)[3],b'\xff'*12)
        r['threshold']=255;self.assertEqual(reg.preprocess(raw,2,2,r).split(b'\n',3)[3],b'\0'*6+b'\xff'*3+b'\0'*3)
    def test_coordinate_rounding_and_word_union(self):
        raw=HEADER+b'5\t1\t1\t1\t1\t1\t1\t3\t5\t7\t99\tAlice\n5\t1\t1\t1\t1\t2\t7\t3\t5\t7\t90\tSample\n'
        r={'id':'a','x':10,'y':20,'width':10,'height':10,'scale':3,'threshold':None}
        c=reg.matches(raw,['Alice Sample'],0,r)[0]
        self.assertEqual(c['box'],{'x':10,'y':21,'width':4,'height':3});self.assertEqual(c['region_id'],'a')
        self.assertEqual(c['words'][0]['box'],{'x':10,'y':21,'width':2,'height':3})
        self.assertEqual(c['words'][1]['box'],{'x':12,'y':21,'width':2,'height':3})
    def test_budget(self):
        with self.assertRaises(ValueError):reg.budget([R]*8,list(range(24)),{'width':640,'height':360})
        with self.assertRaises(ValueError):reg.budget([{**R,'width':1920,'height':1080,'scale':3}],list(range(2)),{'width':1920,'height':1080})
    def test_count_rejected_before_tools(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);(p/'r').write_bytes(core.canonical([{**R,'id':f'a{i}'} for i in range(8)]));(p/'f').write_bytes(core.canonical(list(range(24))))
            with patch.object(ocr,'scan',side_effect=AssertionError('must not launch')):
                with self.assertRaises(ValueError):reg.scan('unused','unused',p/'f',p/'r',p/'out')
            self.assertFalse((p/'out').exists())

@unittest.skipUnless(os.name=='posix' and all(shutil.which(x) for x in ('ffmpeg','ffprobe','tesseract')) and Path(FONT).is_file(),'Local English OCR tools/font needed; skip is not pass.')
class RealRegionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name);cls.media=generate(cls.root/'media');cls.scan=cls.root/'scan'
        reg.scan(cls.media/'synthetic.mp4',cls.media/'terms.json',cls.media/'frames.json',cls.media/'regions.json',cls.scan)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name)
    def runscan(self,rs,out='new',terms=None):
        (self.p/'regions').write_bytes(core.canonical(rs));tp=self.media/'terms.json'
        if terms is not None:tp=self.p/'terms';tp.write_bytes(core.canonical(terms))
        return reg.scan(self.media/'synthetic.mp4',tp,self.media/'frames.json',self.p/'regions',self.p/out)
    def decisions(self):
        d=self.p/'d';reg.prepare(self.scan,d);data=core.parse(d.read_bytes());_,_,found=reg.load_scan(self.scan)
        for row,c in zip(data['decisions'],found):
            row.update(decision='accept',note='Synthetic test interval, not a declaration of viewing.',mask={'start_frame':c['frame_index'],'end_frame':c['frame_index']+1,**c['box']})
        d.write_bytes(core.canonical(data));return d
    def test_paired_real_destructive_threshold_recovers_notice(self):
        request=[{**R,'threshold':180}]
        self.runscan(request,'single');_,_,single=reg.load_scan(self.p/'single')
        self.assertEqual([c for c in single if c['origin']=='region'],[])
        original=(self.p/'regions').read_bytes()
        result=reg.scan_paired(self.media/'synthetic.mp4',self.media/'terms.json',self.media/'frames.json',self.p/'regions',self.p/'paired')
        self.assertEqual((self.p/'regions').read_bytes(),original)
        files,m,found=reg.load_scan(self.p/'paired')
        self.assertEqual(core.parse(files['regions.json'])[0],request[0])
        self.assertEqual(len(core.parse(files['regions.json'])),2)
        self.assertEqual([(c['frame_index'],c['term_index']) for c in found if c['origin']=='full-frame'],[(c['frame_index'],c['term_index']) for c in single])
        self.assertEqual({(c['frame_index'],c['term_index']) for c in found if c['origin']=='region'},{(0,1),(3,1)})
        self.assertFalse(result['privacy_complete']);self.assertTrue(result['manual_review_required'])
        coverage=reg.coverage(self.p/'paired')
        self.assertEqual(coverage['unsampled_frame_ranges'],[[1,3],[4,6]])
        self.assertEqual(coverage['regions'][0]['terms'][1]['matched_sampled_frames'],[])
        self.assertEqual(coverage['regions'][1]['terms'][1]['matched_sampled_frames'],[0,3])
        self.assertFalse(coverage['privacy_complete'])
        for i in (0,3):
            self.assertIn(reg.names(i,0)[0],files);self.assertIn(reg.names(i,1)[0],files)
        # Offline verification replays retained pixels and TSV, not another OCR run.
        with patch.object(ocr,'bounded_tool',side_effect=AssertionError('offline only')):
            reg.load_scan(self.p/'paired')
    def test_paired_cli_and_early_budget(self):
        config=self.p/'regions';config.write_bytes(core.canonical([{**R,'threshold':180}]))
        args=[sys.executable,'-m','frame_veil.region_ocr','scan',str(self.media/'synthetic.mp4'),'--terms',str(self.media/'terms.json'),'--frames',str(self.media/'frames.json'),'--regions',str(config),'--out',str(self.p/'paired'),'--pair-unthresholded']
        result=subprocess.run(args,cwd=ROOT,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout)['regions'],2)
        many=self.p/'frames';many.write_bytes(core.canonical(list(range(24))))
        with patch.object(ocr,'bounded_tool',side_effect=AssertionError('must fail before tools')):
            with self.assertRaises(ValueError):reg.scan_paired(self.media/'synthetic.mp4',self.media/'terms.json',many,config,self.p/'too-many')
        self.assertFalse((self.p/'too-many').exists())
    def test_actual_notice_recovered_baseline_preserved(self):
        files,m,c=reg.load_scan(self.scan);_,bc=ocr.validate_files({n[5:]:b for n,b in files.items() if n.startswith('base-')})
        self.assertIn(0,{x['term_index'] for x in bc})
        self.assertEqual({(x['frame_index'],x['term_index']) for x in c if x['origin']=='region'},{(0,1),(3,1)})
        self.assertEqual([x['id'][5:] for x in c if x['origin']=='full-frame'],[x['id'] for x in bc]);self.assertFalse(m['privacy_complete'])
    def test_threshold_positive_and_known_negative(self):
        for threshold in (64,110,180):
            self.runscan([{**R,'threshold':threshold}],str(threshold));_,m,c=reg.load_scan(self.p/str(threshold))
            hits=[x for x in c if x['origin']=='region']
            if threshold==180:self.assertEqual(hits,[])
            else:self.assertEqual(len(hits),2)
            self.assertFalse(m['privacy_complete']);self.assertTrue(any(x['origin']=='full-frame' for x in c))
    def test_other_layouts_and_contrast_with_real_tools(self):
        # Two unrelated placements; threshold is optional and can destroy contrast.
        for label,bg,fg,x,y,threshold,expected in (
            ('right','gray','black',260,40,None,True),
            ('dark','black','white',40,120,None,True),
            ('pale','0xdddddd','0x777777',100,250,110,False),
            ('pale_raw','0xdddddd','0x777777',100,250,None,True)):
            path=self.p/(label+'.mp4')
            vf=f"drawbox=x={x}:y={y}:w=360:h=60:color={bg}:t=fill,drawtext=fontfile={FONT}:text='NOTICE DEMO ONLY':fontcolor={fg}:fontsize=28:x={x+10}:y={y+12}"
            ocr.bounded_tool('ffmpeg',['-v','error','-nostdin','-n','-f','lavfi','-i','color=white:s=640x360:r=1:d=1','-vf',vf,'-an','-c:v','libx264','-pix_fmt','yuv420p','-threads','1',str(path)],16384,30,strict_stderr=True)
            (self.p/'f').write_bytes(core.canonical([0]));(self.p/'r').write_bytes(core.canonical([{'id':'area','x':x,'y':y,'width':360,'height':60,'scale':2,'threshold':threshold}]))
            reg.scan(path,self.media/'terms.json',self.p/'f',self.p/'r',self.p/label)
            _,m,c=reg.load_scan(self.p/label)
            self.assertEqual(any(z['term_index']==1 and z['origin']=='region' for z in c),expected,label)
            if label=='pale':
                reg.scan_paired(path,self.media/'terms.json',self.p/'f',self.p/'r',self.p/'pale-paired')
                _,_,paired=reg.load_scan(self.p/'pale-paired')
                self.assertTrue(any(z['term_index']==1 and z['origin']=='region' for z in paired))
            self.assertFalse(m['privacy_complete'])
    def test_zero_hits_pending_not_clearance(self):
        result=self.runscan([R],terms=['DOESNOTEXISTZZZ']);self.assertEqual(result['candidate_count'],0);self.assertFalse(result['privacy_complete'])
        reg.prepare(self.p/'new',self.p/'d')
        with self.assertRaises(ValueError):reg.plan(self.media/'synthetic.mp4',self.p/'new',self.p/'d',self.p/'plan')
    def test_all_artifacts_tamper(self):
        files,_,_=reg.load_scan(self.scan)
        for n in files:
            bad=dict(files);bad[n]+=b' '
            with self.subTest(n=n),self.assertRaises((ValueError,KeyError)):reg.validate_files(bad)
    def test_rehash_pixels_candidates_or_config_cannot_hide(self):
        files,_,_=reg.load_scan(self.scan)
        for name in ('region-00-frame-0000.ppm','candidates.json','regions.json'):
            bad=dict(files)
            if name.endswith('.ppm'):bad[name]=bad[name][:-1]+bytes([bad[name][-1]^1])
            elif name=='regions.json':d=core.parse(bad[name]);d[0]['x']+=1;d[0]['width']-=1;bad[name]=core.canonical(d)
            else:d=core.parse(bad[name]);d[-1]['box']['x']+=1;bad[name]=core.canonical(d)
            rehash(bad)
            with self.subTest(name=name),self.assertRaises(ValueError):reg.validate_files(bad)
    def test_duplicate_regions_retained_for_manual_decisions(self):
        self.runscan([R,{**R,'id':'other'}]);_,_,c=reg.load_scan(self.p/'new');self.assertEqual(len({x['id'] for x in c}),len(c));self.assertEqual(len([x for x in c if x['origin']=='region']),4)
    def test_pending_dismissed_and_changed_source(self):
        reg.prepare(self.scan,self.p/'pending')
        with self.assertRaises(ValueError):reg.plan(self.media/'synthetic.mp4',self.scan,self.p/'pending',self.p/'plan')
        self.assertFalse((self.p/'plan').exists())
        d=self.decisions();(self.p/'source').write_bytes((self.media/'synthetic.mp4').read_bytes()+b'x')
        with self.assertRaises(ValueError):reg.plan(self.p/'source',self.scan,d,self.p/'plan')
        data=core.parse(d.read_bytes())
        for row in data['decisions']:row.update(decision='dismiss',mask=None)
        d.write_bytes(core.canonical(data))
        with self.assertRaises(ValueError):reg.plan(self.media/'synthetic.mp4',self.scan,d,self.p/'plan')
    def test_decision_manifest_and_candidate_order_binding(self):
        d=self.decisions();orig=d.read_bytes()
        for kind in ('hash','order','missing','shortmask'):
            data=core.parse(orig)
            if kind=='hash':data['scan_manifest_sha256']='0'*64
            elif kind=='order':data['decisions'].reverse()
            elif kind=='missing':data['decisions'].pop()
            else:data['decisions'][-1]['mask']['width']=1
            d.write_bytes(core.canonical(data))
            with self.assertRaises(ValueError):reg.plan(self.media/'synthetic.mp4',self.scan,d,self.p/'plan')
    def test_real_render_mask_audit_and_pending_human(self):
        reg.plan(self.media/'synthetic.mp4',self.scan,self.decisions(),self.p/'plan');core.render(self.media/'synthetic.mp4',self.p/'plan'/'plan.json',self.p/'render')
        self.assertTrue(core.audit_masks(self.p/'render')['declared_masks_opaque']);review.prepare(self.p/'render','silent',self.p/'human')
        self.assertEqual(core.parse((self.p/'human').read_bytes())['items'][0]['checks']['names_and_text'],'pending')
        self.assertEqual((self.p/'plan').stat().st_mode&0o777,0o700)
    def test_offline_verify_no_tool(self):
        with patch.object(subprocess,'Popen',side_effect=AssertionError('no process')):reg.load_scan(self.scan)
    def test_failure_no_output(self):
        old=ocr.bounded_tool
        def fail(tool,args,*a,**kw):
            if tool=='tesseract' and args[0].endswith('region-00-frame-0000.ppm'):raise core.Invalid('injected local tool failure')
            return old(tool,args,*a,**kw)
        with patch.object(ocr,'bounded_tool',side_effect=fail):
            with self.assertRaises(ValueError):self.runscan([R])
        self.assertFalse((self.p/'new').exists())
    def test_exact_directory_and_leaf(self):
        shutil.copytree(self.scan,self.p/'scan');(self.p/'scan'/'extra').write_bytes(b'x')
        with self.assertRaises(ValueError):reg.load_scan(self.p/'scan')
        (self.p/'scan'/'extra').unlink();f=self.p/'scan'/'regions.json';f.unlink();f.symlink_to(self.scan/'regions.json')
        with self.assertRaises(ValueError):reg.load_scan(self.p/'scan')
    def test_output_private_under_umask(self):
        old=os.umask(0o022)
        try:
            self.runscan([R]);reg.prepare(self.p/'new',self.p/'private-decisions')
            reg.plan(self.media/'synthetic.mp4',self.scan,self.decisions(),self.p/'private-plan')
        finally:os.umask(old)
        self.assertEqual((self.p/'new').stat().st_mode&0o777,0o700)
        for artifact in (self.p/'new').iterdir():self.assertEqual(artifact.stat().st_mode&0o777,0o600,artifact.name)
        self.assertEqual((self.p/'private-decisions').stat().st_mode&0o777,0o600)
        self.assertEqual((self.p/'private-plan').stat().st_mode&0o777,0o700)
        for artifact in (self.p/'private-plan').iterdir():self.assertEqual(artifact.stat().st_mode&0o777,0o600,artifact.name)
    def test_cli_verify_pending_error(self):
        args=[sys.executable,'-m','frame_veil.region_ocr'];p=subprocess.run(args+['verify',str(self.scan)],cwd=ROOT,capture_output=True);self.assertEqual(p.returncode,0)
        p=subprocess.run(args+['prepare',str(self.scan),'--out',str(self.p/'d')],cwd=ROOT,capture_output=True);self.assertEqual(p.returncode,0)
        p=subprocess.run(args+['plan',str(self.media/'synthetic.mp4'),str(self.scan),str(self.p/'d'),'--out',str(self.p/'plan')],cwd=ROOT,capture_output=True);self.assertEqual(p.returncode,2);self.assertNotIn(b'Traceback',p.stderr)

if __name__=='__main__':unittest.main()

"""Only original synthetic red video and tone; no private recordings."""
import copy,hashlib,json,os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from frame_veil.core import *
ROOT=Path(__file__).resolve().parents[1]
INFO={'width':96,'height':64,'frames':10,'codec':'h264'}
def plan():return {'schema':1,'source_sha256':'a'*64,'width':96,'height':64,'frames':10,'masks':[dict(start_frame=2,end_frame=6,x=8,y=8,width=24,height=16)]}
class Validation(unittest.TestCase):
    def test_valid_half_open_plan(self):self.assertEqual(load_plan(canonical(plan()),INFO),plan())
    def test_frame_bounds_and_bool(self):
        for key,value in [('start_frame',True),('start_frame',-1),('start_frame',10),('end_frame',2),('end_frame',11),('width',False),('x',1.5)]:
            p=plan();p['masks'][0][key]=value
            with self.assertRaises(Invalid):load_plan(canonical(p),INFO)
    def test_rectangle_bounds(self):
        for key,value in [('x',96),('y',64),('width',0),('height',0),('width',89),('height',57),('x',10**500)]:
            p=plan();p['masks'][0][key]=value
            with self.assertRaises(Invalid):load_plan(canonical(p),INFO)
    def test_edge_pixel_allowed(self):
        p=plan();p['masks'][0].update(x=95,y=63,width=1,height=1);self.assertEqual(load_plan(canonical(p),INFO),p)
    def test_hash_dimensions_schema(self):
        for key,value in [('schema',True),('source_sha256','oops'),('width',95),('height',True),('frames',9)]:
            p=plan();p[key]=value
            with self.assertRaises(Invalid):load_plan(canonical(p),INFO)
    def test_unknown_empty_and_excess_masks(self):
        for change in [lambda p:p.update(extra='private'),lambda p:p.update(masks=[]),lambda p:p.update(masks=p['masks']*101),lambda p:p['masks'][0].update(filter='movie=http://example.invalid')]:
            p=plan();change(p)
            with self.assertRaises(Invalid):load_plan(canonical(p),INFO)
    def test_json_adversarial(self):
        for raw in [b'{"x":1,"x":2}',b'['*20000+b'0'+b']'*20000,b'{"x":1e999}',b'"\\ud800"','{}'.encode('utf-16')]:
            with self.assertRaises(Invalid):load_plan(raw,INFO)
    def test_binary_read_bounds(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'x';p.write_bytes(b'\xff'*10);self.assertEqual(read(p,10,utf8=False),b'\xff'*10)
            with self.assertRaises(Invalid):read(p,9,utf8=False)
            with self.assertRaises(Invalid):read(p)
    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'link'
            try:p.symlink_to(ROOT/'README.md')
            except OSError:self.skipTest('OS disallows symlink creation')
            with self.assertRaises(Invalid):read(p,utf8=False)
    @unittest.skipUnless(hasattr(os,'mkfifo'),'POSIX FIFO unavailable')
    def test_fifo_cli_bounded_no_private_echo(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'PRIVATE_SENTINEL';os.mkfifo(p)
            r=subprocess.run([sys.executable,'-m','frame_veil','inspect',str(p)],cwd=ROOT,capture_output=True,text=True,timeout=2)
            self.assertEqual(r.returncode,2);self.assertNotIn('PRIVATE_SENTINEL',r.stderr);self.assertNotIn('Traceback',r.stderr)
    def test_media_timeout_and_error_sanitized(self):
        from frame_veil import core
        with patch.object(core,'executable',return_value=sys.executable),patch.object(core,'TIMEOUT',.05):
            with self.assertRaises(Invalid) as e:run('synthetic',['-c','import time;time.sleep(5)'])
            self.assertNotIn('PRIVATE',str(e.exception))
        for code in ['import sys;sys.exit(1)', 'import sys;sys.stderr.write("PRIVATE")']:
            with patch.object(core,'executable',return_value=sys.executable):
                with self.assertRaises(Invalid) as e:run('synthetic',['-c',code])
                self.assertNotIn('PRIVATE',str(e.exception))
    def test_input_protocol_and_external_reference_guards(self):
        opts=input_options('mov');self.assertEqual(opts[opts.index('-protocol_whitelist')+1],'file,pipe');self.assertEqual(opts[opts.index('-enable_drefs')+1],'0');self.assertEqual(opts[opts.index('-use_absolute_path')+1],'0')
    def test_probe_rejects_rotation_and_bad_dimensions(self):
        base={'streams':[dict(width=96,height=64,nb_read_frames='10',codec_name='h264',sample_aspect_ratio='1:1')]}
        for change in [lambda v:v.update(side_data_list=[{'rotation':90}]),lambda v:v.update(width=1921),lambda v:v.update(nb_read_frames='1801'),lambda v:v.update(sample_aspect_ratio='2:1'),lambda v:v.update(codec_name='hevc')]:
            d=copy.deepcopy(base);change(d['streams'][0])
            with patch('frame_veil.core.run',return_value=canonical(d)),self.assertRaises(Invalid):probe('unused','mov')

@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg/ffprobe missing: real media tests not executed')
class Media(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from examples.synthetic import generate
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name);generate(cls.root/'demo')
        cls.src=cls.root/'demo/synthetic.mp4';cls.plan=cls.root/'demo/plan.json';cls.out=cls.root/'rendered'
        cls.receipt=render(cls.src,cls.plan,cls.out)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def decode(self,path,fmt):
        return run('ffmpeg',['-v','error',*input_options(fmt),'-i',str(path),'-map','0:v:0','-an','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],limit=1024*1024)
    def test_every_decoded_pixel_every_frame_mask_and_preservation(self):
        before=self.decode(self.src,'mov');after=self.decode(self.out/'redacted.mkv','matroska');p=json.loads(self.plan.read_bytes())
        self.assertEqual(len(before),96*64*3*10);self.assertEqual(len(after),len(before))
        for f in range(10):
            for y in range(64):
                for x in range(96):
                    k=((f*64+y)*96+x)*3
                    mask=any(m['start_frame']<=f<m['end_frame'] and m['x']<=x<m['x']+m['width'] and m['y']<=y<m['y']+m['height'] for m in p['masks'])
                    expected=b'\0\0\0' if mask else before[k:k+3]
                    self.assertEqual(after[k:k+3],expected,(f,x,y))
    def test_actual_audio_removed(self):
        self.assertIn('audio',stream_types(self.src,'mov'));self.assertEqual(stream_types(self.out/'redacted.mkv','matroska'),['video'])
    def test_source_metadata_not_copied(self):
        raw=run('ffprobe',['-v','error','-show_format','-show_streams','-of','json',str(self.out/'redacted.mkv')])
        self.assertNotIn(b'PUBLIC_SYNTHETIC',raw)
    def test_verify_real_output(self):self.assertTrue(verify(self.out)['consistent'])
    def test_source_mismatch_does_not_create_destination(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);p=json.loads(self.plan.read_bytes());p['source_sha256']='b'*64;(root/'p').write_bytes(canonical(p))
            with self.assertRaises(Invalid):render(self.src,root/'p',root/'out')
            self.assertFalse((root/'out').exists())
    def test_review_frame_png_and_range(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);frame(self.out,4,root/'preview');self.assertTrue((root/'preview/review-frame.png').read_bytes().startswith(b'\x89PNG\r\n\x1a\n'))
            with self.assertRaises(Invalid):frame(self.out,10,root/'bad')
            self.assertFalse((root/'bad').exists())
    def test_tampered_output_plan_receipt_and_extra(self):
        for name in ['redacted.mkv','plan.json','receipt.json','extra']:
            with tempfile.TemporaryDirectory() as t:
                out=Path(t)/'copy';shutil.copytree(self.out,out);p=out/name
                if name=='receipt.json':d=json.loads(p.read_bytes());d['output']['frames']=True;p.write_bytes(canonical(d))
                else:p.write_bytes((p.read_bytes() if p.exists() else b'')+b'\n')
                with self.assertRaises(Invalid):verify(out)
    def test_no_overwrite(self):
        with self.assertRaises(FileExistsError):render(self.src,self.plan,self.out)
    def many_stream_source(self,root,audio_count):
        p=root/'many.mp4'
        args=['-hide_banner','-loglevel','error','-nostdin','-n','-f','lavfi','-i','color=red:s=16x16:r=2:d=1','-f','lavfi','-i','anullsrc=r=8000:cl=mono','-map','0:v:0']
        for _ in range(audio_count):args+=['-map','1:a:0']
        args+=['-t','1','-c:v','libx264','-threads','1','-c:a','aac',str(p)]
        run('ffmpeg',args)
        raw=read(p,MAX_SOURCE,utf8=False)
        plan={'schema':1,'source_sha256':hashlib.sha256(raw).hexdigest(),'width':16,'height':16,'frames':2,'masks':[dict(start_frame=0,end_frame=2,x=0,y=0,width=2,height=2)]}
        (root/'plan').write_bytes(canonical(plan));return p
    def test_real_64_total_stream_boundary_self_verifies(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);source=self.many_stream_source(root,63)
            self.assertEqual(inspect(source)['frames'],2)
            receipt=render(source,root/'plan',root/'out')
            self.assertEqual(len(receipt['source_stream_types']),64)
            self.assertTrue(verify(root/'out')['consistent'])
            self.assertEqual(stream_types(root/'out/redacted.mkv','matroska'),['video'])
    def test_real_65_stream_source_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);source=self.many_stream_source(root,64)
            with self.assertRaises(Invalid):inspect(source)
            with self.assertRaises(Invalid):render(source,root/'plan',root/'out')
            self.assertFalse((root/'out').exists())
    def test_cli_inspect_render_verify_and_frame(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            for args in [['inspect',str(self.src)],['render',str(self.src),str(self.plan),'--out',str(root/'out')],['verify',str(root/'out')],['frame',str(root/'out'),'--index','4','--out',str(root/'png')]]:
                r=subprocess.run([sys.executable,'-m','frame_veil',*args],cwd=ROOT,capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)
if __name__=='__main__':unittest.main()

"""Original synthetic tones/video only; no private speech recordings."""
import copy,hashlib,json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from frame_veil import core
from frame_veil import audio
ROOT=Path(__file__).resolve().parents[1]
class AudioValidation(unittest.TestCase):
    def plan(self):return {'schema':1,'source_sha256':'a'*64,'sample_rate':8000,'channels':1,'samples':16000,'mute_ranges':[{'start_sample':100,'end_sample':200}]}
    def test_bad_ranges_and_parameters(self):
        for change in (lambda p:p.update(schema=True),lambda p:p.update(channels=True),lambda p:p.update(samples=15999),lambda p:p.update(source_sha256='b'*64),lambda p:p['mute_ranges'][0].update(start_sample=True),lambda p:p['mute_ranges'][0].update(end_sample=16001),lambda p:p['mute_ranges'][0].update(end_sample=100),lambda p:p.update(mute_ranges=[]),lambda p:p.update(extra=1)):
            p=self.plan();change(p)
            with self.assertRaises(core.Invalid):audio.load_audio_plan(core.canonical(p),'a'*64,{'sample_rate':8000,'channels':1,'samples':16000})
    def test_discontinuous_source_timestamp_rejected(self):
        meta={'streams':[{'codec_name':'aac','sample_rate':'8000','channels':1,'start_time':'0.000000','time_base':'1/8000'}]}
        for frames in ([{'pts':1,'nb_samples':1024}],[{'pts':0,'nb_samples':1024},{'pts':2048,'nb_samples':1024}],[]):
            with patch('frame_veil.core.run',side_effect=[core.canonical(meta),core.canonical({'frames':frames})]):
                with self.assertRaises(core.Invalid):audio._audio_meta('ignored','mov',True)
    def test_wrong_wav_rejected(self):
        with self.assertRaises(core.Invalid):audio._read_wav(b'not wave')

@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg unavailable: actual audio tests not executed')
class AudioMedia(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from examples.synthetic import generate
        cls.tmp=tempfile.TemporaryDirectory();cls.p=Path(cls.tmp.name);generate(cls.p/'source');cls.src=cls.p/'source'/'synthetic.mp4';cls.vplan=cls.p/'source'/'plan.json';cls.info=audio.inspect_audio(cls.src);cls.plan={'schema':1,'source_sha256':cls.info['source_sha256'],**{k:cls.info['audio'][k] for k in ('sample_rate','channels','samples')},'mute_ranges':[{'start_sample':2000,'end_sample':4000},{'start_sample':3000,'end_sample':5000}]};cls.aplan=cls.p/'audio-plan.json';cls.aplan.write_bytes(core.canonical(cls.plan));cls.out=cls.p/'review';audio.render_audio(cls.src,cls.vplan,cls.aplan,cls.out)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def copy(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);p=Path(t.name)/'bundle';shutil.copytree(self.out,p);return p
    def remux(self,p):
        out=p.parent/'new.mkv';core.run('ffmpeg',['-v','error','-nostdin','-n',*core.input_options('matroska'),'-i',str(p/'video'/'redacted.mkv'),*core.input_options('wav'),'-i',str(p/'redacted.wav'),'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','pcm_s16le','-f','matroska',str(out)]);(p/'review.mkv').write_bytes(out.read_bytes());r=json.loads((p/'receipt.json').read_bytes());r['review_sha256']=audio.sha(out.read_bytes());r['wav_sha256']=audio.sha((p/'redacted.wav').read_bytes());(p/'receipt.json').write_bytes(core.canonical(r))
    def mutate_sample(self,sample):
        p=self.copy();a,pcm=audio._read_wav((p/'redacted.wav').read_bytes());buf=bytearray(pcm);buf[sample*2:sample*2+2]=b'\1\0';(p/'redacted.wav').write_bytes(audio._wav(buf,a));self.remux(p);return p
    def test_real_inspect_bound(self):
        self.assertEqual(self.info['audio']['sample_rate'],8000);self.assertGreaterEqual(self.info['audio']['samples'],16000);self.assertEqual(self.info['audio']['channels'],1)
    def test_every_pcm_sample_preserved_or_muted(self):
        with tempfile.TemporaryDirectory() as t:
            _,_,_,a,before=audio._source(self.src,Path(t));_,after=audio._read_wav((self.out/'redacted.wav').read_bytes());self.assertEqual(len(before),len(after));self.assertTrue(any(before[2000*2:5000*2]));self.assertTrue(any(after[100:1000]));self.assertTrue(any(after[10000:12000]))
            for i in range(a['samples']):self.assertEqual(after[i*2:i*2+2],b'\0\0' if 2000<=i<5000 else before[i*2:i*2+2],i)
    def test_real_final_audio_and_video_audit(self):
        r=audio.verify_audio(self.out);self.assertTrue(r['declared_mutes_silent']);self.assertTrue(r['declared_video_masks_opaque']);self.assertEqual(r['sample_frame_checks_including_overlap'],4000)
    def test_muted_sample_rehashed_still_fails(self):
        with self.assertRaises(audio.AudioMismatch) as e:audio.verify_audio(self.mutate_sample(2000))
        self.assertEqual(e.exception.location,{'mute_index':0,'sample_index':2000})
    def test_end_exclusive_not_muted_and_no_source_preservation_certificate(self):
        self.assertTrue(audio.verify_audio(self.mutate_sample(5000))['declared_mutes_silent'])
    def test_combined_video_not_only_fallback_audited(self):
        p=self.copy();out=p.parent/'changed.mkv';core.run('ffmpeg',['-v','error','-nostdin','-n',*core.input_options('matroska'),'-i',str(p/'review.mkv'),'-map','0:v:0','-map','0:a:0','-vf',"drawbox=x=8:y=8:w=1:h=1:color=blue:t=fill:enable='eq(n,2)'",'-c:v','ffv1','-pix_fmt','bgr0','-threads','1','-c:a','copy','-f','matroska',str(out)]);(p/'review.mkv').write_bytes(out.read_bytes());r=json.loads((p/'receipt.json').read_bytes());r['review_sha256']=audio.sha(out.read_bytes());(p/'receipt.json').write_bytes(core.canonical(r))
        with self.assertRaises(core.MaskMismatch):audio.verify_audio(p)
    def test_hash_tamper_rejected(self):
        p=self.copy();(p/'redacted.wav').write_bytes((p/'redacted.wav').read_bytes()+b'extra')
        with self.assertRaises(core.Invalid):audio.verify_audio(p)
    def test_rehashed_extra_wav_data_rejected(self):
        p=self.copy();(p/'redacted.wav').write_bytes((p/'redacted.wav').read_bytes()+b'PRIVATE_TRAILING_DATA');r=json.loads((p/'receipt.json').read_bytes());r['wav_sha256']=audio.sha((p/'redacted.wav').read_bytes());(p/'receipt.json').write_bytes(core.canonical(r))
        with self.assertRaises(core.Invalid):audio.verify_audio(p)
    def test_source_tags_not_copied_to_review(self):
        data=core.run('ffprobe',['-v','error',*core.input_options('matroska'),'-show_format','-show_streams','-of','json',str(self.out/'review.mkv')])
        self.assertNotIn(b'PUBLIC_SYNTHETIC',data)
    def test_nonzero_source_audio_start_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'offset.mp4';core.run('ffmpeg',['-v','error','-nostdin','-n',*core.input_options('mov'),'-i',str(self.src),'-itsoffset','0.5',*core.input_options('mov'),'-i',str(self.src),'-map','0:v:0','-map','1:a:0','-c','copy',str(p)])
            with self.assertRaises(core.Invalid):audio.inspect_audio(p)
    def test_extra_file_rejected(self):
        p=self.copy();(p/'private.txt').write_text('not for sharing')
        with self.assertRaises(core.Invalid):audio.verify_audio(p)
    def test_wrong_source_plan_no_output(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);bad=copy.deepcopy(self.plan);bad['source_sha256']='b'*64;(p/'plan.json').write_bytes(core.canonical(bad))
            with self.assertRaises(core.Invalid):audio.render_audio(self.src,self.vplan,p/'plan.json',p/'out')
            self.assertFalse((p/'out').exists())
    def test_existing_output_not_overwritten(self):
        with self.assertRaises(FileExistsError):audio.render_audio(self.src,self.vplan,self.aplan,self.out)
        self.assertTrue(audio.verify_audio(self.out)['consistent'])
    def test_multiple_source_audio_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'multi.mp4';core.run('ffmpeg',['-v','error','-nostdin','-n',*core.input_options('mov'),'-i',str(self.src),'-map','0:v:0','-map','0:a:0','-map','0:a:0','-c','copy',str(p)])
            with self.assertRaises(core.Invalid):audio.inspect_audio(p)
    def test_missing_audio_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'silent.mp4';core.run('ffmpeg',['-v','error','-nostdin','-n',*core.input_options('mov'),'-i',str(self.src),'-map','0:v:0','-an','-c:v','copy',str(p)])
            with self.assertRaises(core.Invalid):audio.inspect_audio(p)
    def test_stereo_48k_real_roundtrip(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);src=p/'stereo.mp4';core.run('ffmpeg',['-v','error','-nostdin','-n',*core.input_options('mov'),'-i',str(self.src),'-f','lavfi','-i','sine=frequency=660:sample_rate=48000:duration=2','-map','0:v:0','-map','1:a:0','-ac','2','-c:v','copy','-c:a','aac',str(src)]);a=audio.inspect_audio(src);v=json.loads(self.vplan.read_bytes());v['source_sha256']=a['source_sha256'];(p/'v.json').write_bytes(core.canonical(v));q={'schema':1,'source_sha256':a['source_sha256'],**{k:a['audio'][k] for k in ('sample_rate','channels','samples')},'mute_ranges':[{'start_sample':0,'end_sample':1},{'start_sample':a['audio']['samples']-1,'end_sample':a['audio']['samples']}]};(p/'a.json').write_bytes(core.canonical(q));audio.render_audio(src,p/'v.json',p/'a.json',p/'review');r=audio.verify_audio(p/'review');self.assertEqual(r['audio']['channels'],2);self.assertEqual(r['audio']['sample_rate'],48000)
    def test_cli(self):
        def cli(*args):return subprocess.run([sys.executable,'-m','frame_veil',*map(str,args)],cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(cli('audio-inspect',self.src).returncode,0);self.assertEqual(cli('audio-verify',self.out).returncode,0);r=cli('audio-verify',self.mutate_sample(2000));self.assertEqual(r.returncode,3);self.assertEqual(json.loads(r.stdout)['first_failure']['sample_index'],2000)
if __name__=='__main__':unittest.main()

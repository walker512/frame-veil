"""POSIX private creation throughout real synthetic media/review workflows."""
import json,os,shutil,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from frame_veil import core,audio,review
from examples.selective_audio import generate_audio

@unittest.skipUnless(os.name=='posix' and shutil.which('ffmpeg') and shutil.which('ffprobe'),'POSIX media tools required; skip is not pass.')
class MediaPermissions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.media=generate_audio(cls.root/'fixture')
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name)
    def assert_private(self,path):
        self.assertEqual(path.stat().st_mode&0o777,0o700 if path.is_dir() else 0o600,path.name)
        if path.is_dir():
            for child in path.rglob('*'):
                self.assertEqual(child.stat().st_mode&0o777,0o700 if child.is_dir() else 0o600,str(child.relative_to(path)))
    def test_all_actual_outputs_private_under_022_and_000(self):
        for mask in (0o022,0):
            base=self.p/str(mask);base.mkdir();original=core.run;tool_outputs=[]
            def checked_tool(name,args,*a,**kw):
                result=original(name,args,*a,**kw)
                if name=='ffmpeg' and '-n' in args and Path(args[-1]).is_file():
                    tool_outputs.append(args[-1]);self.assert_private(Path(args[-1]))
                return result
            old=os.umask(mask)
            try:
                with patch.object(core,'run',side_effect=checked_tool):
                    core.render(self.media/'synthetic.mp4',self.media/'plan.json',base/'silent')
                    core.frame(base/'silent',0,base/'preview')
                    audio.render_audio(self.media/'synthetic.mp4',self.media/'plan.json',self.media/'audio-plan.json',base/'audio')
                    review.prepare(base/'audio','audio',base/'human.json')
                    record=json.loads((base/'human.json').read_bytes())
                    item=record['items'][0];check=next(iter(item['checks']))
                    review.decide(base/'audio',base/'human.json',item['id'],check,'reviewed',base/'decision.json')
                    # Synthetic fixture declaration only, not a claim of real viewing.
                    for item in record['items']:
                        for key in item['checks']:item['checks'][key]='reviewed'
                    (base/'human.json').write_bytes(core.canonical(record))
                    result=review.export(base/'audio',base/'human.json',base/'export',True)
                    self.assertFalse(result['privacy_certified']);self.assertFalse(result['publication_authorized'])
            finally:os.umask(old)
            self.assertTrue(tool_outputs)
            for name in ('silent','preview','audio','human.json','decision.json','export'):self.assert_private(base/name)
            self.assertTrue(core.audit_masks(base/'silent')['declared_masks_opaque'])
            self.assertTrue(audio.verify_audio(base/'audio')['declared_mutes_silent'])
    def test_subprocess_private_umask_does_not_mutate_parent(self):
        out=self.p/'child-created';old=os.umask(0)
        try:
            with patch.object(core,'executable',return_value=sys.executable):
                core.run('controlled',['-c','import pathlib,sys;pathlib.Path(sys.argv[1]).write_bytes(b"fictional")',str(out)])
            self.assert_private(out)
            current=os.umask(0);self.assertEqual(current,0)
        finally:os.umask(old)
    def test_existing_review_file_and_symlink_not_overwritten(self):
        core.render(self.media/'synthetic.mp4',self.media/'plan.json',self.p/'silent')
        target=self.p/'keep';target.write_bytes(b'keep')
        with self.assertRaises(FileExistsError):review.prepare(self.p/'silent','silent',target)
        link=self.p/'link';link.symlink_to(target)
        with self.assertRaises(FileExistsError):review.prepare(self.p/'silent','silent',link)
        self.assertEqual(target.read_bytes(),b'keep')

if __name__=='__main__':unittest.main()

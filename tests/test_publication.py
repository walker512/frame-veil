"""Synthetic media; no user recordings or remote services."""
import errno
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from frame_veil import core, publication as pub

SUPPORTED = sys.platform.startswith('linux') or sys.platform == 'win32'

@unittest.skipUnless(SUPPORTED, 'No no-replace implementation for this platform')
class Publication(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
    def test_no_replace_empty_directory_file_and_link(self):
        for kind in ('directory','file','link'):
            source=self.root/('source-'+kind);source.mkdir();(source/'mine').write_bytes(b'ours')
            target=self.root/('target-'+kind)
            if kind=='directory':target.mkdir()
            elif kind=='file':target.write_bytes(b'user')
            else:
                try:target.symlink_to(source,target_is_directory=True)
                except OSError:continue
            with self.assertRaises(OSError):pub.rename_exclusive(source,target)
            self.assertEqual((source/'mine').read_bytes(),b'ours')
            if kind=='file':self.assertEqual(target.read_bytes(),b'user')
    def test_concurrent_publishers_one_wins(self):
        destination=self.root/'final'
        code='from frame_veil.publication import rename_exclusive; import sys; rename_exclusive(sys.argv[1],sys.argv[2])'
        sources=[];workers=[]
        for i in range(4):
            s=self.root/str(i);s.mkdir();(s/'owner').write_text(str(i));sources.append(s)
            workers.append(subprocess.Popen([sys.executable,'-c',code,str(s),str(destination)],stdout=subprocess.PIPE,stderr=subprocess.PIPE))
        for worker in workers:
            worker.communicate(timeout=10)
        self.assertEqual(sum(p.returncode==0 for p in workers),1)
        winner=(destination/'owner').read_text()
        self.assertFalse(sources[int(winner)].exists())
        self.assertEqual(sum(s.exists() for s in sources),3)
    def test_cross_device_error_has_no_copy_fallback(self):
        source=self.root/'source';source.mkdir();(source/'data').write_bytes(b'keep')
        with patch.object(pub,'rename_exclusive',side_effect=OSError(errno.EXDEV,'synthetic')),patch.object(core,'verify',return_value={}):
            with self.assertRaises(OSError):pub.publish_render(source,self.root/'out')
        self.assertEqual((source/'data').read_bytes(),b'keep');self.assertFalse((self.root/'out').exists())
    def test_unsupported_platform_fails_before_render(self):
        with patch.object(pub.sys,'platform','unsupported'),patch.object(core,'render') as render:
            with self.assertRaises(core.Invalid):pub.render_staged('source','plan',self.root/'out')
            render.assert_not_called()
        self.assertEqual(list(self.root.iterdir()),[])

@unittest.skipUnless(SUPPORTED and shutil.which('ffmpeg') and shutil.which('ffprobe'),'Real FFmpeg and supported no-replace platform required')
class MediaPublication(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        from examples.synthetic import generate
        generate(self.root/'demo');self.source=self.root/'demo/synthetic.mp4';self.plan=self.root/'demo/plan.json';self.out=self.root/'out'
    def test_real_media_cli_staged_and_legacy_verify(self):
        result=subprocess.run([sys.executable,'-m','frame_veil','render',str(self.source),str(self.plan),'--out',str(self.out),'--staged'],capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        core.verify(self.out);core.audit_masks(self.out)
        self.assertEqual(len(list(self.root.glob('.frame-veil-stage-*'))),1)
        legacy=self.root/'legacy';core.render(self.source,self.plan,legacy);core.verify(legacy)
    def test_partial_write_never_final_and_fresh_retry_succeeds(self):
        writer=core.private_write
        def failing(path,raw):
            if Path(path).name=='plan.json':raise OSError('injected disk failure')
            writer(path,raw)
        with patch.object(core,'private_write',side_effect=failing):
            with self.assertRaises(OSError):pub.render_staged(self.source,self.plan,self.out)
        self.assertFalse(self.out.exists())
        partial=next(self.root.glob('.frame-veil-stage-*/bundle'))
        self.assertEqual({p.name for p in partial.iterdir()},{'redacted.mkv'})
        with self.assertRaises(core.Invalid):pub.publish_render(partial,self.out)
        (partial/'foreign').write_bytes(b'never delete')
        pub.render_staged(self.source,self.plan,self.out);core.verify(self.out)
        self.assertEqual((partial/'foreign').read_bytes(),b'never delete')
    def test_complete_stage_resume_without_render(self):
        with patch.object(pub,'rename_exclusive',side_effect=OSError('injected publication failure')):
            with self.assertRaises(OSError):pub.render_staged(self.source,self.plan,self.out)
        staged=next(self.root.glob('.frame-veil-stage-*/bundle'));core.verify(staged)
        original=(staged/'redacted.mkv').read_bytes()
        with patch.object(core,'render',side_effect=AssertionError('must not re-render')):
            pub.publish_render(staged,self.out)
        self.assertEqual((self.out/'redacted.mkv').read_bytes(),original)
    def test_interrupt_retains_stage_not_final(self):
        writer=core.private_write
        def interrupt(path,raw):
            if Path(path).name=='receipt.json':raise KeyboardInterrupt()
            writer(path,raw)
        with patch.object(core,'private_write',side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):pub.render_staged(self.source,self.plan,self.out)
        self.assertFalse(self.out.exists());self.assertEqual(len(list(self.root.glob('.frame-veil-stage-*/bundle'))),1)
    def test_destination_race_preserves_users_directory_and_stage(self):
        rename=pub.rename_exclusive
        def concurrent(source,dest):
            Path(dest).mkdir();(Path(dest)/'user').write_bytes(b'keep')
            rename(source,dest)
        with patch.object(pub,'rename_exclusive',side_effect=concurrent):
            with self.assertRaises(OSError):pub.render_staged(self.source,self.plan,self.out)
        self.assertEqual((self.out/'user').read_bytes(),b'keep')
        staged=next(self.root.glob('.frame-veil-stage-*/bundle'));core.verify(staged)
    def test_existing_destination_rejects_before_media_work(self):
        self.out.mkdir()
        with patch.object(core,'render') as render:
            with self.assertRaises(FileExistsError):pub.render_staged(self.source,self.plan,self.out)
            render.assert_not_called()

if __name__=='__main__':unittest.main()

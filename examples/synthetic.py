"""Create only original synthetic color video and tone, never personal footage.
Run from source: python -m examples.synthetic NEW_DIRECTORY
"""
import sys
from pathlib import Path
from frame_veil.core import run,inspect,canonical

def generate(out):
    root=Path(out);root.mkdir(exist_ok=False);source=root/'synthetic.mp4'
    run('ffmpeg',['-hide_banner','-loglevel','error','-nostdin','-n','-f','lavfi','-i','color=c=red:s=96x64:r=5:d=2','-f','lavfi','-i','sine=frequency=440:sample_rate=8000:duration=2','-map','0:v:0','-map','1:a:0','-c:v','libx264','-pix_fmt','yuv420p','-threads','1','-c:a','aac','-metadata','title=PUBLIC_SYNTHETIC_TITLE','-metadata:s:v:0','title=PUBLIC_SYNTHETIC_STREAM','-metadata:s:v:0','comment=PUBLIC_SYNTHETIC_COMMENT','-shortest',str(source)])
    info=inspect(source)
    plan={'schema':1,'source_sha256':info['source_sha256'],'width':info['width'],'height':info['height'],'frames':info['frames'],'masks':[{'start_frame':2,'end_frame':6,'x':8,'y':8,'width':24,'height':16},{'start_frame':4,'end_frame':8,'x':24,'y':16,'width':24,'height':16}]}
    (root/'plan.json').write_bytes(canonical(plan));return root
if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Usage: python -m examples.synthetic NEW_DIRECTORY')
    generate(sys.argv[1])

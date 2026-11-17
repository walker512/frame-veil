"""Original six-frame fixture: fictional text appears only between sparse samples."""
import sys
from pathlib import Path
from frame_veil import core, ocr
from .ocr_synthetic import FONT

def generate(out):
    if not Path(FONT).is_file():
        raise ValueError('Existing DejaVu Sans font required; nothing is downloaded.')
    root=Path(out);root.mkdir(exist_ok=False)
    vf=f"drawtext=fontfile={FONT}:text='SECRET DEMO':fontcolor=black:fontsize=28:x=40+80*n:y=200:enable='eq(n,1)+eq(n,2)+eq(n,4)'"
    ocr.bounded_tool('ffmpeg',['-v','error','-nostdin','-n','-f','lavfi','-i','color=white:s=640x360:r=2:d=3','-vf',vf,'-an','-c:v','libx264','-pix_fmt','yuv420p','-threads','1',str(root/'synthetic.mp4')],16384,30,strict_stderr=True)
    (root/'terms.json').write_bytes(core.canonical(['SECRET DEMO']))
    (root/'frames.json').write_bytes(core.canonical([0,3]))
    (root/'regions.json').write_bytes(core.canonical([{'id':'notice-band','x':20,'y':180,'width':600,'height':70,'scale':2,'threshold':None}]))
    return root

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Usage: python -m examples.moving_text_synthetic NEW_DIRECTORY')
    generate(sys.argv[1])

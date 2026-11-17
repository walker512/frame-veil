"""Original synthetic red video/tone plus explicit mute plan; no speech detection."""
import sys
from pathlib import Path
from .synthetic import generate
from frame_veil.audio import inspect_audio
from frame_veil.core import canonical

def generate_audio(out):
    root=generate(out);info=inspect_audio(root/'synthetic.mp4');a=info['audio']
    plan={'schema':1,'source_sha256':info['source_sha256'],**{k:a[k] for k in ('sample_rate','channels','samples')},'mute_ranges':[{'start_sample':2000,'end_sample':4000},{'start_sample':3000,'end_sample':5000}]}
    (root/'audio-plan.json').write_bytes(canonical(plan));return root
if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Usage: python -m examples.selective_audio NEW_DIRECTORY')
    generate_audio(sys.argv[1])

import argparse,json,sys
from .core import Invalid,MaskMismatch,inspect,render,verify,frame,audit_masks
from .audio import AudioMismatch,inspect_audio,render_audio,verify_audio

def main():
    p=argparse.ArgumentParser(description='Manual frame masks; default render removes ALL audio, optional explicit sample muting. Trusted FFmpeg required.')
    sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('inspect');a.add_argument('source')
    a=sub.add_parser('render');a.add_argument('source');a.add_argument('plan');a.add_argument('--out',required=True)
    a=sub.add_parser('verify');a.add_argument('folder')
    a=sub.add_parser('audit-masks');a.add_argument('folder')
    a=sub.add_parser('frame');a.add_argument('folder');a.add_argument('--index',type=int,required=True);a.add_argument('--out',required=True)
    a=sub.add_parser('audio-inspect');a.add_argument('source')
    a=sub.add_parser('audio-render');a.add_argument('source');a.add_argument('video_plan');a.add_argument('audio_plan');a.add_argument('--out',required=True)
    a=sub.add_parser('audio-verify');a.add_argument('folder')
    args=p.parse_args()
    try:
        if args.command=='inspect':r=inspect(args.source)
        elif args.command=='render':r=render(args.source,args.plan,args.out)
        elif args.command=='verify':r=verify(args.folder)
        elif args.command=='audit-masks':r=audit_masks(args.folder)
        elif args.command=='audio-inspect':r=inspect_audio(args.source)
        elif args.command=='audio-render':r=render_audio(args.source,args.video_plan,args.audio_plan,args.out)
        elif args.command=='audio-verify':r=verify_audio(args.folder)
        else:r=frame(args.folder,args.index,args.out)
        print(json.dumps(r));return 0
    except AudioMismatch as e:
        print(json.dumps({'declared_mutes_silent':False,'first_failure':e.location,'audit_completed':False,'manual_review_required':True}));return 3
    except MaskMismatch as e:
        print(json.dumps({'declared_masks_opaque':False,'first_failure':e.location,'audit_completed':False,'manual_review_required':True}));return 3
    except (Invalid,OSError,ValueError,RecursionError):
        print('Cannot process media or plan: unsupported input, mismatch, bounds, missing FFmpeg, timeout or filesystem failure. Media contents and tool diagnostics are not echoed.',file=sys.stderr);return 2
if __name__=='__main__':sys.exit(main())

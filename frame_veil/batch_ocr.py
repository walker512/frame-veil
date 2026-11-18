"""Resumable bounded region-OCR batches. No mask merging or privacy clearance."""
import argparse, contextlib, os, re, stat, subprocess, sys, tempfile
if os.name == "posix":
    import fcntl
from pathlib import Path
from . import core, ocr, region_ocr as reg, cancellation

MAX_DISK = 32 * 1024**3
DEFAULT_DISK = 1024**3
Invalid = core.Invalid

def ranges(start, end, size):
    core.integer(start,0,1799);core.integer(end,1,1800);core.integer(size,1,24)
    if start >= end: raise Invalid('Nonempty explicit interval required.')
    result=[[i,min(i+size,end)] for i in range(start,end,size)]
    if len(result)>256: raise Invalid('At most 256 batches; increase chunk size within limits.')
    return result

def upper_bytes(info, regions, count):
    # Retained RGB images + worst-case TSV + bounded JSON and PPM headers.
    rgb=info['width']*info['height']*3
    derived=sum(r['width']*r['height']*r['scale']**2*3 for r in regions)
    return count*(rgb+derived+(1+len(regions))*(ocr.TSV_LIMIT+100))+8*core.INPUT_LIMIT

def validate_plan(plan, terms_raw, regions_raw):
    core.fields(plan,('schema','source_sha256','info','start','end','chunk_size','max_disk_bytes','terms_sha256','regions_sha256','ranges','estimated_upper_bytes','privacy_complete'))
    core.integer(plan['schema'],1,1)
    if plan['privacy_complete'] is not False: raise Invalid('Privacy status invalid.')
    for key in ('source_sha256','terms_sha256','regions_sha256'):
        if type(plan[key]) is not str or not re.fullmatch('[0-9a-f]{64}',plan[key]):raise Invalid('Hash invalid.')
    if ocr.sha(terms_raw)!=plan['terms_sha256'] or ocr.sha(regions_raw)!=plan['regions_sha256']:raise Invalid('Configuration binding mismatch.')
    ocr.terms(terms_raw)
    info=plan['info'];core.fields(info,('width','height','frames','codec'))
    core.integer(info['width'],2,1920);core.integer(info['height'],2,1080);core.integer(info['frames'],1,1800)
    if info['codec']!='h264':raise Invalid('Unsupported source codec.')
    rs=reg.regions(regions_raw,info);chunks=ranges(plan['start'],plan['end'],plan['chunk_size'])
    if plan['end']>info['frames'] or core.canonical(chunks)!=core.canonical(plan['ranges']):raise Invalid('Source or interval mismatch.')
    for start,end in chunks:reg.budget(rs,list(range(start,end)),info)
    core.integer(plan['max_disk_bytes'],1,MAX_DISK)
    total=sum(upper_bytes(info,rs,end-start) for start,end in chunks)+len(terms_raw)+len(regions_raw)+core.INPUT_LIMIT
    core.integer(plan['estimated_upper_bytes'],1,MAX_DISK)
    if plan['estimated_upper_bytes']!=total or total>plan['max_disk_bytes']:raise Invalid('Explicit disk budget too small.')
    return rs

@cancellation.cancellable
def initialize(source,terms_path,regions_path,start,end,out,chunk_size=8,max_disk_bytes=DEFAULT_DISK,pair_unthresholded=False,estimate_only=False):
    chunks=ranges(start,end,chunk_size)
    if not estimate_only and (Path(out).exists() or Path(out).is_symlink()):raise Invalid('New output required.')
    tr=core.read(terms_path);ocr.terms(tr);rr=core.read(regions_path)
    if pair_unthresholded:rr=core.canonical(reg.paired_regions(rr))
    rs=reg.regions(rr)
    source_bytes=core.read(source,core.MAX_SOURCE,False)
    with tempfile.TemporaryDirectory(prefix='frame-batch-probe-') as td:
        path=Path(td)/'source.mp4';ocr.private_write(path,source_bytes);info=ocr.probe(path)
    plan={'schema':1,'source_sha256':ocr.sha(source_bytes),'info':info,'start':start,'end':end,'chunk_size':chunk_size,
          'max_disk_bytes':max_disk_bytes,'terms_sha256':ocr.sha(tr),'regions_sha256':ocr.sha(rr),'ranges':chunks,
          'estimated_upper_bytes':sum(upper_bytes(info,rs,b-a) for a,b in chunks)+len(tr)+len(rr)+core.INPUT_LIMIT,
          'privacy_complete':False}
    core.integer(max_disk_bytes,1,MAX_DISK)
    validate_plan({**plan,'max_disk_bytes':MAX_DISK} if estimate_only else plan,tr,rr)
    if estimate_only:
        return {'initialized':False,'batches':len(chunks),'requested_frames':end-start,'estimated_upper_bytes':plan['estimated_upper_bytes'],'max_disk_bytes':max_disk_bytes,'within_requested_budget':plan['estimated_upper_bytes']<=max_disk_bytes,'privacy_complete':False,'scan_started':False}
    root=Path(out);root.mkdir(mode=0o700);(root/'chunks').mkdir(mode=0o700)
    for name,raw in {'terms.json':tr,'regions.json':rr,'batch.json':core.canonical(plan)}.items():ocr.private_write(root/name,raw)
    return {'initialized':True,'batches':len(chunks),'requested_frames':end-start,'estimated_upper_bytes':plan['estimated_upper_bytes'],'max_disk_bytes':max_disk_bytes,'privacy_complete':False,'scan_started':False}

def load(folder):
    root=Path(folder)
    if root.is_symlink() or not root.is_dir():raise Invalid('Regular batch directory required.')
    raw=core.read(root/'batch.json');plan=core.parse(raw)
    if raw!=core.canonical(plan):raise Invalid('Canonical batch plan required.')
    tr=core.read(root/'terms.json');rr=core.read(root/'regions.json');rs=validate_plan(plan,tr,rr)
    members={p.name for p in root.iterdir()}
    if not {'batch.json','terms.json','regions.json','chunks'}<=members:raise Invalid('Missing batch members.')
    for name in members-{'batch.json','terms.json','regions.json','chunks','.lock'}:
        p=root/name
        if not name.startswith('.attempt-') or p.is_symlink() or not p.is_dir():raise Invalid('Unexpected batch member.')
    chunks=root/'chunks'
    if chunks.is_symlink() or not chunks.is_dir():raise Invalid('Regular chunks directory required.')
    expected={f'chunk-{i:04d}' for i in range(len(plan['ranges']))}
    if not {p.name for p in chunks.iterdir()}<=expected:raise Invalid('Unexpected chunk name.')
    return root,plan,tr,rr,rs

def inspect(folder):
    root,plan,tr,rr,rs=load(folder);complete=[];pending=[]
    for i,(start,end) in enumerate(plan['ranges']):
        path=root/'chunks'/f'chunk-{i:04d}'
        if not path.exists() and not path.is_symlink():pending.append([start,end]);continue
        files,m,_=reg.load_scan(path)
        if m['source_sha256']!=plan['source_sha256'] or m['info']!=plan['info'] or m['indexes']!=list(range(start,end)) or files['base-terms.json']!=tr or files['regions.json']!=rr:
            raise Invalid('Stored chunk does not match batch/source/configuration.')
        complete.append([start,end])
    return {'verified_completed_ranges':complete,'pending_ranges':pending,'all_requested_frames_scanned':not pending,
            'requested_range':[plan['start'],plan['end']],
            'outside_requested_ranges':([[0,plan['start']]] if plan['start'] else [])+([[plan['end'],plan['info']['frames']]] if plan['end']<plan['info']['frames'] else []),
            'abandoned_attempts':sum(p.name.startswith('.attempt-') for p in root.iterdir()),
            'privacy_complete':False,'mask_plans_merged':False,'manual_full_output_review_required':True,
            'warning':'Completed means stored OCR evidence verifies, not that all private content was found. Pending/outside frames remain unscanned by this batch.'}

def disk_usage(root):
    total=0;count=0
    for parent,dirs,files in os.walk(root,followlinks=False):
        for name in dirs+files:
            path=Path(parent)/name;st=path.lstat();count+=1
            if count>200000 or not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode)):raise Invalid('Unexpected filesystem object or excessive files.')
            if stat.S_ISREG(st.st_mode):total+=st.st_size
            if total>MAX_DISK:raise Invalid('Stored evidence exceeds maximum disk budget.')
    return total

@contextlib.contextmanager
def lock(root):
    if os.name!='posix':raise Invalid('Batch runner requires POSIX.')
    fd=os.open(root/'.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):raise Invalid('Regular lock required.')
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise Invalid('Another batch runner is active.') from None
        yield
    finally:os.close(fd)

@cancellation.cancellable
def run(source,folder,max_chunks=1):
    core.integer(max_chunks,1,8)
    root,plan,tr,rr,rs=load(folder)
    with lock(root):
        status=inspect(root)
        if ocr.sha(core.read(source,core.MAX_SOURCE,False))!=plan['source_sha256']:raise Invalid('Source changed; refusing resume.')
        completed=0
        for i,(start,end) in enumerate(plan['ranges']):
            if [start,end] in status['verified_completed_ranges']:continue
            if completed>=max_chunks:break
            if disk_usage(root)+upper_bytes(plan['info'],rs,end-start)>plan['max_disk_bytes']:raise Invalid('Insufficient remaining explicit disk budget; inspect abandoned attempts.')
            with tempfile.TemporaryDirectory(prefix='.attempt-',dir=root) as td:
                staged=Path(td)/'scan'
                reg.scan_interval(source,root/'terms.json',start,end,root/'regions.json',staged)
                files,m,_=reg.load_scan(staged)
                if m['source_sha256']!=plan['source_sha256'] or m['info']!=plan['info'] or m['indexes']!=list(range(start,end)) or files['base-terms.json']!=tr or files['regions.json']!=rr:
                    raise Invalid('Source/config changed during execution.')
                # Same filesystem, exclusive runner. Only verified complete chunks
                # become visible under a final name; no partial chunk is resumed.
                destination=root/'chunks'/f'chunk-{i:04d}'
                if destination.exists() or destination.is_symlink():raise Invalid('Chunk destination already exists.')
                os.rename(staged,destination)
            completed+=1
        result=inspect(root);result['batches_completed_this_run']=completed;return result

def main():
    p=argparse.ArgumentParser(description=__doc__);subs=p.add_subparsers(dest='command',required=True)
    for command in ('init','estimate'):
        a=subs.add_parser(command);a.add_argument('source')
        for name in ('terms','regions'):a.add_argument('--'+name,required=True)
        if command=='init':a.add_argument('--out',required=True)
        a.add_argument('--start',type=int,required=True);a.add_argument('--end',type=int,required=True)
        a.add_argument('--chunk-size',type=int,default=8);a.add_argument('--max-disk-bytes',type=int,default=DEFAULT_DISK);a.add_argument('--pair-unthresholded',action='store_true')
    a=subs.add_parser('run');a.add_argument('source');a.add_argument('batch');a.add_argument('--max-chunks',type=int,default=1)
    a=subs.add_parser('status');a.add_argument('batch');args=p.parse_args()
    try:
        if args.command in ('init','estimate'):result=initialize(args.source,args.terms,args.regions,args.start,args.end,getattr(args,'out',None),args.chunk_size,args.max_disk_bytes,args.pair_unthresholded,args.command=='estimate')
        elif args.command=='run':result=run(args.source,args.batch,args.max_chunks)
        else:result=inspect(args.batch)
        print(core.canonical(result).decode());return 0
    except (ValueError,TypeError,KeyError,OSError,UnicodeError,RecursionError,subprocess.SubprocessError):
        print('Batch OCR failed: check bounds, evidence, source/config binding, remaining budget and active runner. No private paths or text echoed.',file=sys.stderr);return 2

if __name__=='__main__':sys.exit(main())

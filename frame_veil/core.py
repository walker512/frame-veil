"""Manual opaque frame masks; all audio removed. Not automatic anonymization."""
import hashlib,io,json,os,re,stat
from pathlib import Path
INPUT_LIMIT=1024*1024
OUTPUT_LIMIT=2*1024*1024
class Invalid(ValueError):pass
class MaskMismatch(Invalid):
    def __init__(self,frame,mask,row):
        super().__init__('A declared mask contains nonzero decoded RGB pixels.')
        self.location={'frame_index':frame,'mask_index':mask,'pixel_row':row}


def read(path,limit=INPUT_LIMIT,utf8=True):
    try:
        if not stat.S_ISREG(Path(path).lstat().st_mode):raise Invalid('Regular non-symlink file required.')
        fd=os.open(path,os.O_RDONLY|getattr(os,'O_NONBLOCK',0)|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0))
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size>limit:raise Invalid('File type or size limit exceeded.')
            with os.fdopen(fd,'rb') as f:fd=None;raw=f.read(limit+1)
        finally:
            if fd is not None:os.close(fd)
        if len(raw)>limit:raise Invalid('File size limit exceeded.')
        if utf8:raw.decode('utf8')
        return raw
    except (OSError,UnicodeError):raise Invalid('Cannot safely read bounded UTF-8 file.') from None

def parse(raw):
    def pairs(items):
        result={}
        for k,v in items:
            if k in result:raise Invalid('Duplicate JSON keys.')
            k.encode('utf8');result[k]=v
        return result
    def bad(x):raise Invalid('Non-finite number.')
    try:
        if len(raw)>INPUT_LIMIT:raise Invalid('Input exceeds 1 MiB.')
        result=json.loads(raw.decode('utf8'),object_pairs_hook=pairs,parse_constant=bad)
        queue=[(result,0)]
        while queue:
            value,depth=queue.pop()
            if isinstance(value,(list,dict)):
                if depth>=16:raise Invalid('JSON depth exceeded.')
                queue.extend((v,depth+1) for v in (value.values() if isinstance(value,dict) else value))
            elif isinstance(value,str):value.encode('utf8')
            elif isinstance(value,float):raise Invalid('Floating-point metadata is unsupported.')
        return result
    except (ValueError,UnicodeError,RecursionError):raise Invalid('Invalid bounded JSON.') from None

def fields(item,names):
    if not isinstance(item,dict) or set(item)!=set(names):raise Invalid('Unexpected or missing fields.')
def integer(value,lo,hi):
    if type(value) is not int or not lo<=value<=hi:raise Invalid('Integer outside declared bounds.')
import shutil,subprocess,tempfile
MAX_SOURCE=64*1024*1024
MAX_OUTPUT=256*1024*1024
TIMEOUT=120
MAX_STREAMS=64
STREAM_TYPES=('video','audio','subtitle','data','attachment','unknown')

def canonical(d):return (json.dumps(d,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False)+'\n').encode('utf8')
def executable(name):
    path=shutil.which(name)
    if path is None:raise Invalid('Required FFmpeg tool is not installed.')
    return path

def run(name,args,limit=2*1024*1024):
    try:
        p=subprocess.run([executable(name),*args],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=TIMEOUT,check=False)
    except (OSError,subprocess.TimeoutExpired):raise Invalid('Media tool failed or timed out.') from None
    if p.returncode or p.stderr or len(p.stdout)>limit:raise Invalid('Media processing failed or output exceeded bounds.')
    return p.stdout

# MOV external references are disabled. Network protocols and playlist formats
# are not accepted. A recent trusted FFmpeg installation is still required.
def input_options(fmt):
    args=['-protocol_whitelist','file,pipe','-f',fmt]
    if fmt=='mov':args+=['-enable_drefs','0','-use_absolute_path','0']
    return args

def probe(path,fmt):
    raw=run('ffprobe',['-v','error',*input_options(fmt),'-select_streams','v','-count_frames','-show_entries','stream=index,codec_name,width,height,nb_read_frames,sample_aspect_ratio:stream_side_data=rotation:stream_tags=rotate','-of','json',str(path)])
    try:
        data=json.loads(raw);streams=data['streams']
        if len(streams)!=1:raise Invalid('Exactly one video stream required.')
        v=streams[0];w,h,n=int(v['width']),int(v['height']),int(v['nb_read_frames'])
        if not(2<=w<=1920 and 2<=h<=1080 and 1<=n<=1800):raise Invalid('Video dimensions or frame count exceed bounds.')
        if v.get('sample_aspect_ratio','1:1') not in ('1:1','N/A'):raise Invalid('Only square-pixel video is supported.')
        rotations=[x.get('rotation',0) for x in v.get('side_data_list',[])]+[v.get('tags',{}).get('rotate',0)]
        if any(float(x)!=0 for x in rotations):raise Invalid('Rotated inputs must be normalized separately before masking.')
        if v['codec_name']!=('h264' if fmt=='mov' else 'ffv1'):raise Invalid('Unsupported video codec.')
        return {'width':w,'height':h,'frames':n,'codec':v['codec_name']}
    except (KeyError,TypeError,ValueError,OverflowError):raise Invalid('Unsupported or malformed video metadata.') from None

def stream_types(path,fmt):
    raw=run('ffprobe',['-v','error',*input_options(fmt),'-show_entries','stream=codec_type','-of','json',str(path)])
    try:types=[s['codec_type'] for s in json.loads(raw)['streams']]
    except (ValueError,KeyError,TypeError):raise Invalid('Malformed stream metadata.') from None
    validate_stream_types(types)
    return types

def validate_stream_types(types):
    if not isinstance(types,list) or not 1<=len(types)<=MAX_STREAMS or any(type(x) is not str or x not in STREAM_TYPES for x in types):raise Invalid('Unsupported stream types or count.')

def snapshot(source,dest):
    # Bound/read a leaf regular file once, then every media process consumes this
    # private snapshot rather than reopening a user-controlled source path.
    raw=read(source,MAX_SOURCE,utf8=False);dest.write_bytes(raw);return hashlib.sha256(raw).hexdigest()

def load_plan(raw,info):
    d=parse(raw);fields(d,['schema','source_sha256','width','height','frames','masks']);integer(d['schema'],1,1)
    if type(d['source_sha256']) is not str or not re.fullmatch('[0-9a-f]{64}',d['source_sha256']):raise Invalid('Plan needs exact source SHA-256.')
    for field in ('width','height','frames'):
        if type(d[field]) is not int or d[field]!=info[field]:raise Invalid('Plan dimensions/frame count differ from media.')
    if not isinstance(d['masks'],list) or not 1<=len(d['masks'])<=100:raise Invalid('Expected 1..100 explicit masks.')
    for m in d['masks']:
        fields(m,['start_frame','end_frame','x','y','width','height'])
        integer(m['start_frame'],0,info['frames']-1);integer(m['end_frame'],m['start_frame']+1,info['frames'])
        integer(m['x'],0,info['width']-1);integer(m['y'],0,info['height']-1)
        integer(m['width'],1,info['width']-m['x']);integer(m['height'],1,info['height']-m['y'])
    return d

def filters(plan):
    # All interpolated values passed strict integer validation. No user filter
    # syntax, file name, URL, free text or executable command is interpolated.
    parts=['setpts=PTS-STARTPTS','format=rgb24']
    for m in plan['masks']:
        parts.append(f"drawbox=x={m['x']}:y={m['y']}:w={m['width']}:h={m['height']}:color=black:t=fill:enable='gte(n,{m['start_frame']})*lt(n,{m['end_frame']})'")
    parts.append('format=bgr0');return ','.join(parts)

def inspect(source):
    with tempfile.TemporaryDirectory(prefix='frame-veil-') as t:
        p=Path(t)/'source.mp4';sha=snapshot(source,p);stream_types(p,'mov');info=probe(p,'mov')
    return {'source_sha256':sha,**info,'indexing':'Zero-based decoded video frames; end_frame is exclusive. Not seconds.'}

def render(source,plan_path,out):
    plan_raw=read(plan_path)
    with tempfile.TemporaryDirectory(prefix='frame-veil-') as t:
        temp=Path(t);src=temp/'source.mp4';sha=snapshot(source,src);info=probe(src,'mov');plan=load_plan(plan_raw,info)
        if plan['source_sha256']!=sha:raise Invalid('Plan is bound to a different source.')
        types=stream_types(src,'mov');video=temp/'redacted.mkv'
        run('ffmpeg',['-hide_banner','-loglevel','error','-nostdin','-n',*input_options('mov'),'-noautorotate','-i',str(src),'-map','0:v:0','-an','-sn','-dn','-map_metadata','-1','-map_metadata:s:v:0','-1','-map_chapters','-1','-vf',filters(plan),'-c:v','ffv1','-level','3','-pix_fmt','bgr0','-threads','1','-fps_mode','passthrough','-fs',str(MAX_OUTPUT),'-f','matroska',str(video)])
        rendered=probe(video,'matroska')
        if any(rendered[k]!=info[k] for k in ('width','height','frames')) or stream_types(video,'matroska')!=['video']:raise Invalid('Output stream/frame validation failed.')
        output_raw=read(video,MAX_OUTPUT,utf8=False)
        report={'schema':1,'source_sha256':sha,'plan_sha256':hashlib.sha256(plan_raw).hexdigest(),'output_sha256':hashlib.sha256(output_raw).hexdigest(),'input':info,'output':rendered,'source_stream_types':types,'all_audio_removed':True,'source_metadata_not_copied':True,'manual_review_required':True,'scope':'Only explicit opaque rectangles on specified decoded frames were applied. No automatic privacy detection, source authenticity or anonymization certification.'}
        files={'redacted.mkv':output_raw,'plan.json':plan_raw,'receipt.json':canonical(report)}
        root=Path(out);root.mkdir(exist_ok=False)
        for name,data in files.items():(root/name).write_bytes(data)
    return report

def verify(folder):
    root=Path(folder)
    if root.is_symlink() or not root.is_dir() or {p.name for p in root.iterdir()}!={'redacted.mkv','plan.json','receipt.json'}:raise Invalid('Unexpected output structure.')
    receipt=parse(read(root/'receipt.json'));fields(receipt,['schema','source_sha256','plan_sha256','output_sha256','input','output','source_stream_types','all_audio_removed','source_metadata_not_copied','manual_review_required','scope'])
    integer(receipt['schema'],1,1)
    for key in ('source_sha256','plan_sha256','output_sha256'):
        if type(receipt[key]) is not str or not re.fullmatch('[0-9a-f]{64}',receipt[key]):raise Invalid('Invalid receipt digest.')
    for key,codec in (('input','h264'),('output','ffv1')):
        fields(receipt[key],['width','height','frames','codec'])
        for field,hi in (('width',1920),('height',1080),('frames',1800)):integer(receipt[key][field],1,hi)
        if receipt[key]['codec']!=codec:raise Invalid('Invalid receipt codec.')
    if any(receipt['input'][k]!=receipt['output'][k] for k in ('width','height','frames')):raise Invalid('Receipt frame dimensions differ.')
    validate_stream_types(receipt['source_stream_types'])
    if receipt['source_metadata_not_copied'] is not True:raise Invalid('Invalid metadata declaration.')
    if receipt['scope']!='Only explicit opaque rectangles on specified decoded frames were applied. No automatic privacy detection, source authenticity or anonymization certification.':raise Invalid('Invalid receipt scope.')
    # Receipt comparison is structural and byte-bound, not authenticated proof
    # that the original source or all necessary mask regions were supplied.
    plan_raw=read(root/'plan.json');video_raw=read(root/'redacted.mkv',MAX_OUTPUT,utf8=False)
    if receipt['plan_sha256']!=hashlib.sha256(plan_raw).hexdigest() or receipt['output_sha256']!=hashlib.sha256(video_raw).hexdigest():raise Invalid('Output bytes differ from receipt.')
    with tempfile.TemporaryDirectory(prefix='frame-veil-') as t:
        p=Path(t)/'video.mkv';p.write_bytes(video_raw);info=probe(p,'matroska');types=stream_types(p,'matroska')
    if canonical(info)!=canonical(receipt['output']) or types!=['video']:raise Invalid('Output metadata/streams differ.')
    plan=load_plan(plan_raw,info)
    if plan['source_sha256']!=receipt['source_sha256'] or receipt['all_audio_removed'] is not True or receipt['manual_review_required'] is not True:raise Invalid('Receipt assertions differ.')
    return {'consistent':True,'output':info,'plan_sha256':receipt['plan_sha256'],'output_sha256':receipt['output_sha256'],'manual_review_required':True,'scope':'Hashes and output stream properties only, not source authenticity or completeness/correctness of privacy masking.'}

def frame(folder,index,out):
    result=verify(folder);integer(index,0,result['output']['frames']-1)
    raw=read(Path(folder)/'redacted.mkv',MAX_OUTPUT,utf8=False)
    if hashlib.sha256(raw).hexdigest()!=result['output_sha256']:raise Invalid('Video changed after verification.')
    with tempfile.TemporaryDirectory(prefix='frame-veil-') as t:
        p=Path(t)/'video.mkv';p.write_bytes(raw)
        png=run('ffmpeg',['-hide_banner','-loglevel','error','-nostdin',*input_options('matroska'),'-i',str(p),'-map','0:v:0','-vf',f"select=eq(n\\,{index})",'-frames:v','1','-f','image2pipe','-c:v','png','pipe:1'],limit=16*1024*1024)
        if not png.startswith(b'\x89PNG\r\n\x1a\n'):raise Invalid('Review frame could not be decoded.')
    root=Path(out);root.mkdir(exist_ok=False);(root/'review-frame.png').write_bytes(png)
    return {'frame':index,'manual_review_required':True}


def audit_masks(folder):
    """Independently inspect every planned output rectangle in decoded RGB frames.

    This does not inspect unmarked regions or authenticate the source/plan.
    """
    import threading
    checked=verify(folder)
    plan_raw=read(Path(folder)/'plan.json');video_raw=read(Path(folder)/'redacted.mkv',MAX_OUTPUT,utf8=False)
    if hashlib.sha256(plan_raw).hexdigest()!=checked['plan_sha256'] or hashlib.sha256(video_raw).hexdigest()!=checked['output_sha256']:raise Invalid('Bundle changed after structural verification.')
    info=checked['output'];plan=load_plan(plan_raw,info);frame_bytes=info['width']*info['height']*3;pixel_checks=0;marked_frames=0
    with tempfile.TemporaryDirectory(prefix='frame-veil-audit-') as t:
        p=Path(t)/'verified.mkv';p.write_bytes(video_raw)
        # One RGB frame at a time, not the full decoded recording in memory.
        with tempfile.TemporaryFile() as errors:
            process=None;timer=None;expired=threading.Event()
            try:
                process=subprocess.Popen([executable('ffmpeg'),'-hide_banner','-loglevel','error','-nostdin',*input_options('matroska'),'-i',str(p),'-map','0:v:0','-an','-sn','-dn','-threads','1','-fps_mode','passthrough','-frames:v',str(info['frames']+1),'-pix_fmt','rgb24','-f','rawvideo','pipe:1'],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=errors)
                def stop():
                    expired.set()
                    try:process.kill()
                    except OSError:pass
                timer=threading.Timer(TIMEOUT,stop);timer.daemon=True;timer.start()
                for index in range(info['frames']):
                    frame=process.stdout.read(frame_bytes)
                    if expired.is_set() or len(frame)!=frame_bytes:raise Invalid('Incomplete or timed-out RGB decode.')
                    masks=[(mi,m) for mi,m in enumerate(plan['masks']) if m['start_frame']<=index<m['end_frame']]
                    if masks:marked_frames+=1
                    for mi,m in masks:
                        for row in range(m['y'],m['y']+m['height']):
                            start=(row*info['width']+m['x'])*3;segment=frame[start:start+m['width']*3]
                            if segment.count(0)!=len(segment):raise MaskMismatch(index,mi,row)
                        pixel_checks+=m['width']*m['height']
                if process.stdout.read(1):raise Invalid('Unexpected extra decoded frames.')
                code=process.wait(timeout=2);errors.seek(0)
                if expired.is_set() or code or errors.read(1):raise Invalid('Decode reported an error or timeout.')
            except (OSError,subprocess.TimeoutExpired):raise Invalid('Mask audit decoder failed or timed out.') from None
            finally:
                if timer is not None:timer.cancel()
                if process is not None:
                    if process.poll() is None:
                        process.kill();process.wait()
                    if process.stdout is not None:process.stdout.close()
    return {'declared_masks_opaque':True,'all_audio_absent':True,'decoded_frames':info['frames'],'marked_frames':marked_frames,'rectangle_pixel_checks_including_overlap':pixel_checks,'output_sha256':checked['output_sha256'],'plan_sha256':checked['plan_sha256'],'manual_review_required':True,'scope':'Exact zero RGB checks of declared output rectangles only; unmarked privacy, source authenticity, source-to-output preservation and timing correctness are not certified.'}

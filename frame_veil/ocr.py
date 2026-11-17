"""Explicit English text candidates on selected decoded frames, not privacy detection. MIT walker512."""
import argparse,csv,hashlib,io,json,os,re,selectors,signal,subprocess,sys,tempfile,time
from decimal import Decimal,InvalidOperation
from pathlib import Path
from . import core
Invalid=core.Invalid
MAX_SAMPLES=64*1024*1024
TSV_LIMIT=1024*1024
SCOPE='Selected-frame text candidates only. Not complete privacy detection, proof of viewing or publication consent.'
def sha(b):return hashlib.sha256(b).hexdigest()
def dump(d):return core.canonical(d)
def bounded_tool(tool,args,cap,timeout=30,sink=None,strict_stderr=False):
    if os.name!='posix':raise Invalid('OCR subprocess workflow requires POSIX.')
    stdout=bytearray();stderr=bytearray();count=0;deadline=time.monotonic()+timeout
    try:p=subprocess.Popen([core.executable(tool),*args],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,env={'PATH':os.defpath,'LANG':'C.UTF-8','OMP_THREAD_LIMIT':'1'})
    except OSError:raise Invalid('Required local OCR/media tool could not start.') from None
    def kill():
        try:os.killpg(p.pid,signal.SIGKILL)
        except ProcessLookupError:pass
    try:
        with selectors.DefaultSelector() as sel:
            for f,label in ((p.stdout,'out'),(p.stderr,'err')):os.set_blocking(f.fileno(),False);sel.register(f,selectors.EVENT_READ,label)
            while sel.get_map() or p.poll() is None:
                if time.monotonic()>deadline:raise Invalid('OCR/media tool deadline exceeded.')
                if p.poll() is not None:kill()
                for k,_ in sel.select(.05):
                    chunk=os.read(k.fileobj.fileno(),65536)
                    if not chunk:sel.unregister(k.fileobj);continue
                    if k.data=='err':
                        if len(stderr)+len(chunk)>65536:raise Invalid('Tool diagnostics exceeded bounds.')
                        stderr.extend(chunk)
                    else:
                        count+=len(chunk)
                        if count>cap:raise Invalid('Tool output exceeded bounds.')
                        if sink:sink(chunk)
                        else:stdout.extend(chunk)
        if p.returncode or (strict_stderr and stderr):raise Invalid('Tool reported processing failure.')
        return bytes(stdout),{'stderr_bytes':len(stderr),'stderr_sha256':sha(stderr)}
    except OSError:raise Invalid('Bounded tool processing failed.') from None
    finally:
        kill()
        try:p.wait(timeout=2)
        finally:p.stdout.close();p.stderr.close()

def terms(raw):
    d=core.parse(raw)
    if type(d) is not list or not 1<=len(d)<=20:raise Invalid('Supply 1..20 explicit search phrases.')
    normalized=[]
    for t in d:
        if type(t) is not str or not t.strip() or len(t)>200 or any(ord(c)<32 for c in t):raise Invalid('Bounded plain-text phrases required.')
        tokens=t.casefold().split()
        if len(tokens)>20 or tokens in normalized:raise Invalid('Duplicate normalized phrase or too many tokens.')
        normalized.append(tokens)
    return d

def indices(raw,total=None):
    d=core.parse(raw)
    if type(d) is not list or not 1<=len(d)<=24:raise Invalid('Supply 1..24 explicit frame indexes.')
    for n in d:core.integer(n,0,(total-1) if total else 1799)
    if d!=sorted(set(d)):raise Invalid('Frame indexes must be sorted and unique.')
    return d

def probe(path):
    raw,_=bounded_tool('ffprobe',['-v','error',*core.input_options('mov'),'-count_frames','-show_entries','stream=codec_type,codec_name,width,height,nb_read_frames,sample_aspect_ratio:stream_side_data=rotation:stream_tags=rotate','-of','json',str(path)],262144,120,strict_stderr=True)
    try:
        d=json.loads(raw);ss=d['streams']
        if type(ss) is not list or not 1<=len(ss)<=64:raise Invalid('Stream count unsupported.')
        vs=[s for s in ss if s['codec_type']=='video']
        if len(vs)!=1 or vs[0]['codec_name']!='h264':raise Invalid('One H264 video required.')
        v=vs[0]
        if any(type(v[k]) is bool for k in ('width','height','nb_read_frames')):raise Invalid('Boolean media dimensions unsupported.')
        w,h,n=int(v['width']),int(v['height']),int(v['nb_read_frames'])
        core.integer(w,2,1920);core.integer(h,2,1080);core.integer(n,1,1800)
        if v.get('sample_aspect_ratio','1:1') not in ('1:1','N/A'):raise Invalid('Square pixels required.')
        rotations=[x.get('rotation',0) for x in v.get('side_data_list',[])]+[v.get('tags',{}).get('rotate',0)]
        if any(Decimal(str(x))!=0 for x in rotations):raise Invalid('Rotated input unsupported.')
        return {'width':w,'height':h,'frames':n,'codec':'h264'}
    except (ValueError,KeyError,TypeError,InvalidOperation):raise Invalid('Unsupported bounded video metadata.') from None

def ppm(raw,w,h):
    head=f'P6\n{w} {h}\n255\n'.encode()
    if len(raw)!=len(head)+w*h*3 or not raw.startswith(head):raise Invalid('Only exact generated RGB PPM layout accepted.')

def candidates(tsv,phrases,frame,w,h):
    if len(tsv)>TSV_LIMIT:raise Invalid('TSV exceeds bound.')
    try:text=tsv.decode('utf8')
    except UnicodeError:raise Invalid('TSV not UTF-8.') from None
    header='level page_num block_num par_num line_num word_num left top width height conf text'.split()
    try:rows=list(csv.reader(io.StringIO(text),delimiter='\t',quoting=csv.QUOTE_NONE))
    except csv.Error:raise Invalid('TSV field exceeds parser bounds.') from None
    if not rows or rows[0]!=header or len(rows)>10001:raise Invalid('Unexpected TSV structure.')
    lines={};seen=set()
    for row in rows[1:]:
        if len(row)!=12:raise Invalid('Malformed TSV row.')
        try:
            if any(not re.fullmatch('[0-9]{1,8}',x) for x in row[:10]):raise Invalid('Invalid TSV integer.')
            if len(row[10])>64:raise Invalid('Confidence representation exceeds bound.')
            ns=list(map(int,row[:10]));level,page,block,par,line,word,x,y,bw,bh=ns;conf=Decimal(row[10])
            if not conf.is_finite() or not -1<=conf<=100:raise Invalid('Invalid confidence.')
            if not 1<=level<=5 or page!=1 or x+bw>w or y+bh>h:raise Invalid('TSV coordinates exceed frame.')
            value=row[11]
            if len(value)>1000 or '\x00' in value:raise Invalid('TSV word exceeds bounds.')
            if level!=5:continue
            if not value.strip():continue
            if min(block,par,line,word,bw,bh)<1 or conf<0:raise Invalid('Invalid word row.')
            ident=(page,block,par,line,word)
            if ident in seen:raise Invalid('Duplicate word identity.')
            seen.add(ident);lines.setdefault(ident[:4],[]).append({'word':word,'text':value,'box':{'x':x,'y':y,'width':bw,'height':bh},'confidence':row[10]})
        except (ValueError,InvalidOperation):raise Invalid('Malformed TSV values.') from None
    out=[]
    for line_id,words in sorted(lines.items()):
        words.sort(key=lambda x:x['word'])
        for ti,t in enumerate(phrases):
            tokens=t.casefold().split()
            for start in range(len(words)-len(tokens)+1):
                chunk=words[start:start+len(tokens)]
                if [z['word'] for z in chunk]!=list(range(chunk[0]['word'],chunk[0]['word']+len(tokens))):continue
                if [z['text'].casefold() for z in chunk]!=tokens:continue
                x=min(z['box']['x'] for z in chunk);y=min(z['box']['y'] for z in chunk);right=max(z['box']['x']+z['box']['width'] for z in chunk);bottom=max(z['box']['y']+z['box']['height'] for z in chunk)
                out.append({'id':f'f{frame}-t{ti}-l'+'.'.join(map(str,line_id))+f'-w{chunk[0]["word"]}','frame_index':frame,'term_index':ti,'box':{'x':x,'y':y,'width':right-x,'height':bottom-y},'words':chunk})
    if len(out)>100:raise Invalid('Too many candidates; narrow explicit search.')
    return out

def names(i):return f'frame-{i:04d}.ppm',f'frame-{i:04d}.tsv'
def scan(source,terms_path,frames_path,out):
    if Path(out).exists() or Path(out).is_symlink():raise Invalid('Output must be new.')
    tr=core.read(terms_path);fr=core.read(frames_path);phrases=terms(tr);indexes=indices(fr);src=core.read(source,core.MAX_SOURCE,False)
    files={'terms.json':tr,'frames.json':fr};matches=[];versions={}
    with tempfile.TemporaryDirectory(prefix='frame-ocr-') as td:
        root=Path(td);video=root/'source.mp4';video.write_bytes(src);info=probe(video);indices(fr,info['frames']);w,h=info['width'],info['height'];size=w*h*3
        if size*len(indexes)>MAX_SAMPLES:raise Invalid('Selected RGB frames exceed 64 MiB aggregate budget.')
        for tool,args in (('ffmpeg',['-version']),('ffprobe',['-version']),('tesseract',['--version'])):
            raw,_=bounded_tool(tool,args,16384);lines=raw.decode('utf8').splitlines()
            if not lines:raise Invalid('Tool version unavailable.')
            first=lines[0]
            if not first or len(first)>1000:raise Invalid('Tool version unavailable.')
            versions[tool]=first
        raw,_=bounded_tool('tesseract',['--list-langs'],16384)
        if 'eng' not in raw.decode('utf8').splitlines():raise Invalid('Installed English OCR data required; nothing is downloaded.')
        pending=bytearray();position=0
        def receive(chunk):
            nonlocal position
            pending.extend(chunk)
            while len(pending)>=size:
                if position>=len(indexes):raise Invalid('Extra sampled decoded frame.')
                pn,_=names(indexes[position]);(root/pn).write_bytes(f'P6\n{w} {h}\n255\n'.encode()+bytes(pending[:size]));del pending[:size];position+=1
        select='+'.join('eq(n\\,'+str(i)+')' for i in indexes)
        bounded_tool('ffmpeg',['-v','error','-nostdin','-threads','1',*core.input_options('mov'),'-i',str(video),'-map','0:v:0','-an','-sn','-dn','-vf','select='+select,'-fps_mode','passthrough','-threads','1','-pix_fmt','rgb24','-f','rawvideo','pipe:1'],size*len(indexes),120,receive,True)
        if pending or position!=len(indexes):raise Invalid('Incomplete selected-frame decode.')
        diagnostics={}
        for i in indexes:
            pn,tn=names(i);image=core.read(root/pn,size+100,False);ppm(image,w,h)
            tsv,diag=bounded_tool('tesseract',[str(root/pn),'stdout','-l','eng','--oem','1','--psm','6','tsv'],TSV_LIMIT,30)
            matches.extend(candidates(tsv,phrases,i,w,h));files[pn]=image;files[tn]=tsv;diagnostics[str(i)]=diag
        if len(matches)>100:raise Invalid('More than 100 candidates; narrow search.')
    files['candidates.json']=dump(matches)
    if len(files['candidates.json'])>core.INPUT_LIMIT:raise Invalid('Candidates exceed record bound.')
    manifest={'schema':1,'source_sha256':sha(src),'info':info,'indexes':indexes,'tools':versions,'config':{'language':'eng','oem':1,'psm':6,'normalization':'casefold-whitespace-token-v1','confidence_threshold':None},'diagnostics':diagnostics,'files':{n:sha(b) for n,b in files.items()},'scan_completed':True,'privacy_complete':False,'scope':SCOPE}
    files['manifest.json']=dump(manifest)
    # Snapshot/TSV/metadata all validate before publishing any source-derived artifact.
    validate_files(files)
    Path(out).mkdir(exist_ok=False)
    for n,b in files.items():(Path(out)/n).write_bytes(b)
    return {'scan_completed':True,'sampled_frames':len(indexes),'total_frames':info['frames'],'candidate_count':len(matches),'privacy_complete':False,'manual_review_required':True}

def validate_files(files):
    m=core.parse(files['manifest.json'])
    if files['manifest.json']!=dump(m):raise Invalid('Manifest bytes are not canonical generated form.')
    core.fields(m,('schema','source_sha256','info','indexes','tools','config','diagnostics','files','scan_completed','privacy_complete','scope'));core.integer(m['schema'],1,1)
    if m['scan_completed'] is not True or m['privacy_complete'] is not False or m['scope']!=SCOPE:raise Invalid('Unexpected scan scope/status.')
    if type(m['source_sha256']) is not str or not re.fullmatch('[0-9a-f]{64}',m['source_sha256']):raise Invalid('Source hash invalid.')
    info=m['info'];core.fields(info,('width','height','frames','codec'));w,h=info['width'],info['height'];core.integer(w,2,1920);core.integer(h,2,1080);core.integer(info['frames'],1,1800)
    if info['codec']!='h264':raise Invalid('Unexpected source codec.')
    indexes=indices(files['frames.json'],info['frames']);phrases=terms(files['terms.json'])
    if dump(indexes)!=dump(m['indexes']) or w*h*3*len(indexes)>MAX_SAMPLES:raise Invalid('Frame coverage/budget mismatch.')
    expected={'manifest.json','terms.json','frames.json','candidates.json'}|{n for i in indexes for n in names(i)}
    if set(files)!=expected or type(m['files']) is not dict or set(m['files'])!=expected-{'manifest.json'}:raise Invalid('Exact manifest/file set required.')
    if m['config']!={'language':'eng','oem':1,'psm':6,'normalization':'casefold-whitespace-token-v1','confidence_threshold':None} or dump(m['config'])!=dump({'language':'eng','oem':1,'psm':6,'normalization':'casefold-whitespace-token-v1','confidence_threshold':None}):raise Invalid('OCR configuration mismatch.')
    core.fields(m['tools'],('ffmpeg','ffprobe','tesseract'))
    for v in m['tools'].values():
        if type(v) is not str or not 1<=len(v)<=1000:raise Invalid('Tool version record malformed.')
    if type(m['diagnostics']) is not dict or set(m['diagnostics'])!={str(i) for i in indexes}:raise Invalid('Diagnostic coverage mismatch.')
    for d in m['diagnostics'].values():
        core.fields(d,('stderr_bytes','stderr_sha256'));core.integer(d['stderr_bytes'],0,65536)
        if type(d['stderr_sha256']) is not str or not re.fullmatch('[0-9a-f]{64}',d['stderr_sha256']) or (d['stderr_bytes']==0 and d['stderr_sha256']!=sha(b'')):raise Invalid('Diagnostic hash invalid.')
    for n,b in files.items():
        if n!='manifest.json' and m['files'][n]!=sha(b):raise Invalid('Scan artifact hash mismatch.')
    found=[]
    for i in indexes:
        pn,tn=names(i);ppm(files[pn],w,h);found.extend(candidates(files[tn],phrases,i,w,h))
    if len(found)>100 or files['candidates.json']!=dump(found):raise Invalid('Candidate evidence does not match retained TSV.')
    return m,found

def load_scan(folder):
    p=Path(folder)
    if p.is_symlink() or not p.is_dir():raise Invalid('Regular scan directory required.')
    # Read only the exact bounded manifest-controlled layout; never follow arbitrary paths.
    mr=core.read(p/'manifest.json');m=core.parse(mr)
    if type(m) is not dict:raise Invalid('Scan manifest must be an object.')
    ix=indices(dump(m.get('indexes')))
    expected={'manifest.json','terms.json','frames.json','candidates.json'}|{n for i in ix for n in names(i)}
    if set(x.name for x in p.iterdir())!=expected:raise Invalid('Unexpected scan directory members.')
    files={}
    aggregate=0
    for n in sorted(expected):
        limit=1920*1080*3+100 if n.endswith('.ppm') else core.INPUT_LIMIT
        b=core.read(p/n,limit,False);aggregate+=len(b)
        if aggregate>MAX_SAMPLES+24*TSV_LIMIT+4*core.INPUT_LIMIT:raise Invalid('Scan bundle exceeds aggregate bounds.')
        files[n]=b
    m,found=validate_files(files)
    return files,m,found

def prepare(folder,out):
    files,m,found=load_scan(folder)
    d={'schema':1,'scan_manifest_sha256':sha(files['manifest.json']),'source_sha256':m['source_sha256'],'decisions':[{'id':c['id'],'decision':'pending','note':'','mask':None} for c in found]}
    with Path(out).open('xb') as f:f.write(dump(d))
    return {'candidates':len(found),'all_pending':True,'privacy_complete':False}

def plan(source,folder,decision_path,out):
    if Path(out).exists() or Path(out).is_symlink():raise Invalid('Output must be new.')
    files,m,found=load_scan(folder)
    return plan_from_evidence(source,files,m,found,decision_path,out)

def plan_from_evidence(source,files,m,found,decision_path,out,scope=SCOPE,mode=0o777):
    if Path(out).exists() or Path(out).is_symlink():raise Invalid('Output must be new.')
    dr=core.read(decision_path);d=core.parse(dr);core.fields(d,('schema','scan_manifest_sha256','source_sha256','decisions'));core.integer(d['schema'],1,1)
    if d['scan_manifest_sha256']!=sha(files['manifest.json']) or d['source_sha256']!=m['source_sha256'] or sha(core.read(source,core.MAX_SOURCE,False))!=m['source_sha256']:raise Invalid('Decisions/source/scan binding mismatch.')
    if type(d['decisions']) is not list or len(d['decisions'])!=len(found):raise Invalid('Every candidate needs an explicit decision.')
    masks=[];info=m['info']
    for row,c in zip(d['decisions'],found):
        core.fields(row,('id','decision','note','mask'))
        if row['id']!=c['id'] or row['decision'] not in ('accept','dismiss') or type(row['note']) is not str or not row['note'].strip() or len(row['note'])>2000:raise Invalid('Explicit ordered decisions and reason required.')
        if row['decision']=='dismiss':
            if row['mask'] is not None:raise Invalid('Dismissed candidate cannot carry a mask.')
            continue
        mask=row['mask'];test={'schema':1,'source_sha256':m['source_sha256'],**{k:info[k] for k in ('width','height','frames')},'masks':[mask]};core.load_plan(dump(test),info)
        box=c['box']
        if not mask['start_frame']<=c['frame_index']<mask['end_frame'] or mask['x']>box['x'] or mask['y']>box['y'] or mask['x']+mask['width']<box['x']+box['width'] or mask['y']+mask['height']<box['y']+box['height']:raise Invalid('Accepted interval/rectangle must include the observed frame and candidate box.')
        masks.append(mask)
    if not masks:raise Invalid('No accepted masks; zero candidates/accepts is not a privacy clearance. Use manual workflow.')
    p={'schema':1,'source_sha256':m['source_sha256'],**{k:info[k] for k in ('width','height','frames')},'masks':masks};pr=dump(p);core.load_plan(pr,info)
    receipt={'schema':1,'source_sha256':m['source_sha256'],'scan_manifest_sha256':sha(files['manifest.json']),'decisions_sha256':sha(dr),'plan_sha256':sha(pr),'scope':scope,'manual_interval_declarations':True}
    Path(out).mkdir(mode=mode,exist_ok=False)
    for n,b in {'plan.json':pr,'decisions.json':dr,'receipt.json':dump(receipt)}.items():(Path(out)/n).write_bytes(b)
    return {'plan_created':True,'masks':len(masks),'privacy_complete':False,'manual_full_output_review_required':True}

def main():
    p=argparse.ArgumentParser(description='Local explicit English OCR candidates on selected frames; never a privacy clearance.')
    sub=p.add_subparsers(dest='cmd',required=True);a=sub.add_parser('scan');a.add_argument('source');a.add_argument('--terms',required=True);a.add_argument('--frames',required=True);a.add_argument('--out',required=True)
    a=sub.add_parser('verify');a.add_argument('scan');a=sub.add_parser('prepare');a.add_argument('scan');a.add_argument('--out',required=True)
    a=sub.add_parser('plan');a.add_argument('source');a.add_argument('scan');a.add_argument('decisions');a.add_argument('--out',required=True)
    args=p.parse_args()
    try:
        if args.cmd=='scan':r=scan(args.source,args.terms,args.frames,args.out)
        elif args.cmd=='prepare':r=prepare(args.scan,args.out)
        elif args.cmd=='plan':r=plan(args.source,args.scan,args.decisions,args.out)
        else:_,m,c=load_scan(args.scan);r={'internally_consistent':True,'sampled_frames':len(m['indexes']),'candidates':len(c),'ocr_rerun':False,'privacy_complete':False}
        print(json.dumps(r));return 0
    except (ValueError,TypeError,KeyError,OSError,subprocess.SubprocessError,UnicodeError,RecursionError):
        print('OCR workflow failed. Check supported local source/tools, explicit sampling, exact artifact binding, decisions and limits. No private paths or OCR text echoed.',file=sys.stderr);return 2
if __name__=='__main__':sys.exit(main())

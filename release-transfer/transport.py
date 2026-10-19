"""One-time release transport. Never builds or executes downloaded source code."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse, base64, gzip, hashlib, http.client, io, json, os, shutil, subprocess, tarfile, tempfile, urllib.parse, urllib.request, zipfile
from functools import lru_cache

ROOT = Path(__file__).resolve().parent
REPO = 'huangchong-4806/Eggie-DocuFlow'
RELEASE = 416808990
DOC_HEAD = 'd2e209672f872e3b1f0a84c30d068783f4135c4a'
EXPECTED = {
 'EggieDocuFlow_V1.5.0_third-party-sources.zip': (766285303,'667a1b328f8d8442dd2cca8e266da62b871d4471e173b30627d3255747e14633'),
 'EggieDocuFlow_V1.5.0_project-source.zip': (7662436,'1d0ae3ec7f6cd3003985b68a5c95952a0fe8c2b32b0d73f4e7295fe8e0748d32'),
 'SHA256SUMS.txt': (427,'55f81b26eeac68b1145c0325f29c7506ba81e51fa0adb32c9dc5305f7eb865ec'),
 'EggieDocuFlow_V1.5.0_Windows_x64_Setup.exe': (62762288,'b21f7a3882027d2f6fa217085a085a244bb94bc08919522d6e239fc78172ade9'),
 'EggieDocuFlow_V1.5.0_mac_arm64.zip': (80493099,'442fd21aabaee538dfef65b4802f16bfe29627441cf30c5470dfb1a804af4854'),
}
REPLACE = {
 'EggieDocuFlow_V1.5.0_project-source.zip': (654982211,7661764,'83dd59732b00e3bd11c67d2da2afdbd11af226eb87a0d5d5e92d7be80da229d1'),
 'SHA256SUMS.txt': (654996340,427,'d169d91951b8f8a2dd97b6b9ba714cd02fff5846a6a1ae38e4004ac1b3a9414e'),
}
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def validate(path,size,digest):
    if path.stat().st_size!=size or sha(path)!=digest:raise ValueError('File mismatch: '+path.name)

def run(*args,**kwargs):
    return subprocess.run(args,check=True,timeout=600,**kwargs)

def metadata_bytes(name):
    parts=sorted((ROOT/'metadata-parts').glob(name+'.*'))
    if not parts:raise ValueError('Missing metadata segments: '+name)
    return b''.join(p.read_bytes() for p in parts)

@lru_cache(maxsize=1)
def tar_metadata():
    return json.loads(gzip.decompress(metadata_bytes('tar-metadata.json.gz')))

@lru_cache(maxsize=1)
def tar_seeds():
    return gzip.decompress(metadata_bytes('tar-seeds.bin.gz'))

def restore_tar_metadata(item,downloaded):
    meta=tar_metadata()[item['sha256']]
    with gzip.open(downloaded,'rb') as f:
        raw=f.read(meta['tar_bytes']*2+1)
    if len(raw)>meta['tar_bytes']*2:raise ValueError('Upstream tar exceeds bound')
    seed=memoryview(tar_seeds())[meta['seed_start']:meta['seed_start']+meta['seed_bytes']]
    normalized=downloaded.with_suffix('.normalized')
    h=hashlib.sha256();total=0
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as tar:
        members={}
        for member in tar:
            if member.name in members or member.sparse:raise ValueError('Duplicate or sparse tar entry')
            members[member.name]=member
        actual={n:[m.type.decode(),m.size,m.linkname] for n,m in members.items()}
        if actual!=meta['members']:raise ValueError('Upstream member set or structure changed')
        with normalized.open('wb') as dst:
            with gzip.GzipFile(filename='',mode='wb',fileobj=dst,mtime=0,compresslevel=6) as packed:
                for segment in meta['segments']:
                    if 'seed_offset' in segment:
                        block=seed[segment['seed_offset']:segment['seed_offset']+segment['bytes']]
                    else:
                        member=members[segment['name']]
                        if not member.isfile():raise ValueError('Expected regular tar entry')
                        with tar.extractfile(member) as src:block=src.read(segment['bytes']+1)
                    if len(block)!=segment['bytes']:raise ValueError('Tar segment size mismatch')
                    packed.write(block);h.update(block);total+=len(block)
    if total!=meta['tar_bytes'] or h.hexdigest()!=meta['tar_sha256']:raise ValueError('Original tar reconstruction mismatch')
    validate(normalized,item['bytes'],item['sha256'])
    normalized.replace(downloaded)
    print('ORIGINAL_TAR_BYTES_RESTORED '+item['path'],flush=True)

def download(item,cache):
    target=cache/item['sha256']
    if target.exists():
        validate(target,item['bytes'],item['sha256']);return target
    if item['method']=='git_archive_gzip':
        with tempfile.TemporaryDirectory() as temp:
            git=Path(temp)/'repo';git.mkdir()
            run('git','init','--bare',str(git),stdout=subprocess.DEVNULL)
            run('git','-C',str(git),'fetch','--depth=1',item['repo'],item['commit'])
            commit=subprocess.check_output(['git','-C',str(git),'rev-parse','FETCH_HEAD'],text=True).strip()
            if commit!=item['commit']:raise ValueError('Wrong upstream commit')
            tar=Path(temp)/'source.tar'
            with tar.open('wb') as f:run('git','-C',str(git),'archive',item['commit'],stdout=f)
            with tar.open('rb') as src,target.open('wb') as dst:
                with gzip.GzipFile(filename='',mode='wb',fileobj=dst,mtime=0,compresslevel=item['gzip_level']) as gz:
                    shutil.copyfileobj(src,gz,1024*1024)
    elif item['method']=='https':
        # Recorded, pinned upstream URLs only. No GitHub credentials on upstream requests.
        errors=[]
        for url in item['urls']:
            parsed=urllib.parse.urlparse(url)
            if parsed.scheme!='https' or parsed.username or parsed.password:raise ValueError('Invalid source URL')
            try:
                req=urllib.request.Request(url,headers={'User-Agent':'EggieDocuFlow-source-verification'})
                with urllib.request.urlopen(req,timeout=180) as response,target.open('wb') as dst:
                    size=0
                    while True:
                        block=response.read(1024*1024)
                        if not block:break
                        size+=len(block)
                        limit=item['bytes']*2+1048576 if item['sha256'] in tar_metadata() else item['bytes']
                        if size>limit:raise ValueError('Upstream file too large')
                        dst.write(block)
                try:validate(target,item['bytes'],item['sha256'])
                except ValueError:
                    if item['sha256'] not in tar_metadata():raise
                    restore_tar_metadata(item,target)
                break
            except Exception as e:
                errors.append(type(e).__name__+': '+str(e)[:300])
        else:raise RuntimeError(item['path']+'; '+'; '.join(errors))
    else:raise ValueError('Unknown source method')
    validate(target,item['bytes'],item['sha256'])
    print('SOURCE_VERIFIED '+item['path'],flush=True)
    return target

def assemble(recipe,seed,source_opener,writer):
    if hashlib.sha256(seed).hexdigest()!=recipe['seed_sha256']:raise ValueError('Seed mismatch')
    total=0;h=hashlib.sha256()
    for part in recipe['segments']:
        if 'seed_offset' in part:
            block=seed[part['seed_offset']:part['seed_offset']+part['bytes']]
            if len(block)!=part['bytes']:raise ValueError('Seed range mismatch')
            writer.write(block);h.update(block);total+=len(block)
        else:
            local=hashlib.sha256();n=0
            with source_opener(part['source_sha256']) as f:
                for block in iter(lambda:f.read(1024*1024),b''):
                    n+=len(block)
                    if n>part['bytes']:raise ValueError('Source too large')
                    writer.write(block);h.update(block);local.update(block);total+=len(block)
            if n!=part['bytes'] or local.hexdigest()!=part['source_sha256']:raise ValueError('Source mismatch')
    if total!=recipe['archive_bytes'] or h.hexdigest()!=recipe['archive_sha256']:raise ValueError('Complete archive mismatch')
    return {'bytes':total,'sha256':h.hexdigest()}

def api(path,method='GET'):
    conn=http.client.HTTPSConnection('api.github.com',timeout=90)
    conn.request(method,'/repos/'+REPO+'/'+path,headers={
        'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'Accept':'application/vnd.github+json',
        'User-Agent':'EggieDocuFlow-release-transport','X-GitHub-Api-Version':'2022-11-28'})
    response=conn.getresponse();body=response.read();conn.close()
    if response.status not in (200,201,204):raise RuntimeError('GitHub API '+method+' '+path+' HTTP '+str(response.status))
    return json.loads(body) if body else None

def assets():
    result=[];page=1
    while True:
        batch=api('releases/'+str(RELEASE)+'/assets?per_page=100&page='+str(page));result+=batch
        if len(batch)<100:return result
        page+=1

def matches(a,size,digest):
    return a['state']=='uploaded' and a['size']==size and a.get('digest')=='sha256:'+digest

def release_guard():
    r=api('releases/'+str(RELEASE))
    if not r['draft'] or r['target_commitish']!=DOC_HEAD:raise RuntimeError('Draft target changed')
    a=assets()
    if any(x['name'] not in EXPECTED for x in a):raise RuntimeError('Unexpected draft asset')
    if len({x['name'] for x in a})!=len(a):raise RuntimeError('Duplicate draft asset names')
    for name in list(EXPECTED)[3:]:
        found=[x for x in a if x['name']==name]
        if len(found)!=1 or not matches(found[0],*EXPECTED[name]):raise RuntimeError('Installer verification failed')
    return a

def upload(path):
    name=path.name;size,digest=EXPECTED[name]
    validate(path,size,digest)
    conn=http.client.HTTPSConnection('uploads.github.com',timeout=180)
    url='/repos/'+REPO+'/releases/'+str(RELEASE)+'/assets?name='+urllib.parse.quote(name)
    conn.putrequest('POST',url)
    for k,v in {'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'User-Agent':'EggieDocuFlow-release-transport',
                'Content-Type':'application/octet-stream','Content-Length':str(size),
                'Accept':'application/vnd.github+json'}.items():conn.putheader(k,v)
    conn.endheaders()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):conn.send(b)
    response=conn.getresponse();body=response.read();conn.close()
    if response.status!=201:raise RuntimeError('Upload HTTP '+str(response.status)+'; no automatic retry')
    result=json.loads(body)
    if not matches(result,size,digest):raise RuntimeError('Uploaded digest mismatch')
    current=[x for x in assets() if x['name']==name]
    if len(current)!=1 or not matches(current[0],size,digest):raise RuntimeError('Upload readback mismatch')
    print('RELEASE_ASSET_VERIFIED '+json.dumps({k:current[0][k] for k in ['id','name','state','size','digest']}),flush=True)

def publish_assets(output):
    # Verify all local files before touching the draft. This never publishes the release itself.
    names=list(EXPECTED)[:3]
    for name in names:validate(output/name,*EXPECTED[name])
    for name in names:
        current=[x for x in release_guard() if x['name']==name]
        if current and matches(current[0],*EXPECTED[name]):continue
        if current:
            old=REPLACE.get(name);a=current[0]
            if not old or a['id']!=old[0] or not matches(a,old[1],old[2]):
                raise RuntimeError('Existing unapproved or active asset: '+name)
            api('releases/assets/'+str(a['id']),'DELETE')
            if any(x['name']==name for x in assets()):raise RuntimeError('Deletion readback failed')
        upload(output/name)
    final=release_guard()
    if len(final)!=5 or not all(matches(a,*EXPECTED[a['name']]) for a in final):raise RuntimeError('Five-asset verification failed')
    (output/'release-upload-report.json').write_text(json.dumps({'status':'all_five_draft_assets_verified','assets':final},indent=2))
    print('ALL_FIVE_DRAFT_ASSETS_VERIFIED',flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['assemble','publish']);p.add_argument('--output',default='cloud-output');args=p.parse_args()
    output=Path(args.output);output.mkdir(exist_ok=True)
    if args.mode=='publish':publish_assets(output);return
    recipe=json.loads((ROOT/'recipe.json').read_text());cache=Path('cloud-cache');cache.mkdir(exist_ok=True)
    failures=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        unique={item['sha256']:item for item in recipe['downloads']}
        futures={pool.submit(download,item,cache):item for item in unique.values()}
        for future in as_completed(futures):
            try:future.result()
            except Exception as e:
                failures.append(str(e));print('SOURCE_FAILED '+str(e),flush=True)
    if failures:raise RuntimeError(json.dumps(failures))
    path=output/recipe['archive_name']
    with path.open('wb') as f:
        report=assemble(recipe,(ROOT/'seed.bin').read_bytes(),lambda h:(cache/h).open('rb'),f)
    with zipfile.ZipFile(path) as z:
        if len(z.infolist())!=recipe['zip_entries'] or z.testzip() is not None:raise RuntimeError('ZIP validation failed')
    for name in list(EXPECTED)[1:3]:
        shutil.copyfile(ROOT/name,output/name);validate(output/name,*EXPECTED[name])
    report.update(status='byte_identical',source_archives=len(recipe['downloads']),zip_entries=recipe['zip_entries'])
    (output/'assembly-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('ASSEMBLY_VERIFIED '+json.dumps(report),flush=True)

if __name__=='__main__':main()

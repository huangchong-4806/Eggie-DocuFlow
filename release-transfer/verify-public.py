from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import datetime, hashlib, json, urllib.request
from transport import EXPECTED, api

release = api('releases/tags/v1.5.0')
assert not release['draft'] and not release['prerelease']
assert release['id'] == 416808990
assert release['target_commitish'] == '22f7c0dcfab7739c44d5ba2693ab538a05676046'
assert len(release['assets']) == 5 and {a['name'] for a in release['assets']} == set(EXPECTED)

def verify(asset):
    size, digest = EXPECTED[asset['name']]
    assert asset['state'] == 'uploaded' and asset['size'] == size and asset['digest'] == 'sha256:'+digest
    url = asset['browser_download_url']
    assert url.startswith('https://github.com/huangchong-4806/Eggie-DocuFlow/releases/download/v1.5.0/')
    total = 0
    h = hashlib.sha256()
    # Public HTTPS download, without credentials; do not read upload artifacts or caches.
    with urllib.request.urlopen(url, timeout=120) as response:
        while True:
            block = response.read(1024*1024)
            if not block: break
            total += len(block)
            assert total <= size
            h.update(block)
    assert total == size and h.hexdigest() == digest, asset['name']
    result = {'name':asset['name'],'size':total,'sha256':h.hexdigest(),'url':url}
    print('PUBLIC_ASSET_VERIFIED '+json.dumps(result),flush=True)
    return result

with ThreadPoolExecutor(max_workers=4) as pool:
    rows = list(pool.map(verify, release['assets']))
report = {'status':'passed','release_url':release['html_url'],'tag':'v1.5.0',
          'assets':rows,'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'method':'Independent fresh GitHub Actions runner fetched release metadata using read-only token; all five public download URLs were streamed without credentials and checked byte counts and SHA256. No upload artifact or cached package was reused.'}
Path('public-download-verification.json').write_text(json.dumps(report,indent=2)+'\n')
print('ALL_FIVE_PUBLIC_DOWNLOADS_VERIFIED',flush=True)

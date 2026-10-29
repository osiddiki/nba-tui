"""Local, session-scoped HLS relay for players that serve image-wrapped segments."""
from __future__ import annotations
import gzip
import hashlib
import http.server
import io
import json
import secrets
import struct
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
import zlib

UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36'
MAX_SEGMENT = 24 * 1024 * 1024


def _download(url, referer, timeout=15, limit=MAX_SEGMENT):
    origin = urllib.parse.urlsplit(referer)
    headers = {'User-Agent': UA, 'Referer': referer, 'Origin': f'{origin.scheme}://{origin.netloc}', 'Accept':'*/*'}
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                data = res.read(limit + 1)
            break
        except urllib.error.HTTPError as exc:
            # A rejected playlist token is handled separately by Relay.get.
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(.2 * (attempt + 1))
    if len(data) > limit: raise ValueError('response too large')
    return data


def _limited_gzip(data):
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as g:
        out = g.read(MAX_SEGMENT + 1)
    if len(out) > MAX_SEGMENT: raise ValueError('segment too large')
    return out


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p-a), abs(p-b), abs(p-c)
    return a if pa <= pb and pa <= pc else b if pb <= pc else c


def unwrap_segment(data):
    if data[:1] == b'\x47': return data
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        pos = 12
        while pos + 8 <= len(data):
            tag = data[pos:pos+4]; n = struct.unpack_from('<I', data, pos+4)[0]; pos += 8
            if pos + n > len(data): break
            if tag == b'EXIF' and data[pos:pos+1] == b'\x47': return data[pos:pos+n]
            pos += n + (n & 1)
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        pos, chunks, width, height, ctype = 8, [], 0, 0, 0
        while pos + 12 <= len(data):
            n = struct.unpack_from('>I', data, pos)[0]; tag = data[pos+4:pos+8]
            if n > len(data) - pos - 12: raise ValueError('invalid PNG')
            payload = data[pos+8:pos+8+n]; pos += n+12
            if tag == b'IHDR':
                width, height, depth, ctype, _, _, interlace = struct.unpack('>IIBBBBB', payload)
                if depth != 8 or ctype not in (2, 6) or interlace or width*height > 6_000_000:
                    raise ValueError('unsupported PNG format')
            elif tag == b'IDAT': chunks.append(payload)
            elif tag == b'IEND':
                tail = data[pos:]
                if len(tail) > 188 and tail[0] == 0x47 and tail[188] == 0x47: return tail
                break
        if not width or not height or not chunks: raise ValueError('incomplete PNG')
        bpp = 4 if ctype == 6 else 3; stride = width*bpp
        if (stride+1)*height > MAX_SEGMENT: raise ValueError('PNG too large')
        decomp = zlib.decompressobj()
        raw = decomp.decompress(b''.join(chunks), (stride+1)*height+1)
        if len(raw) != (stride+1)*height: raise ValueError('invalid PNG data')
        rgb = bytearray(); prev = bytearray(stride); pos = 0
        for _ in range(height):
            filt = raw[pos]; pos += 1; row = bytearray(raw[pos:pos+stride]); pos += stride
            if filt:
                for i, val in enumerate(row):
                    a = row[i-bpp] if i >= bpp else 0
                    b = prev[i]
                    c = prev[i-bpp] if i >= bpp else 0
                    if filt == 1: val += a
                    elif filt == 2: val += b
                    elif filt == 3: val += (a+b)//2
                    elif filt == 4: val += _paeth(a,b,c)
                    else: raise ValueError('invalid PNG filter')
                    row[i] = val & 255
            if bpp == 3: rgb.extend(row)
            else:
                for i in range(0, len(row), 4): rgb.extend(row[i:i+3])
            prev = row
        if not rgb.startswith(b'TIKTIKPX') or len(rgb) < 12: raise ValueError('PNG has no transport stream')
        n = struct.unpack_from('>I', rgb, 8)[0]
        if n < 1 or n > len(rgb)-12: raise ValueError('invalid image payload length')
        data = _limited_gzip(bytes(rgb[12:12+n]))
    else:
        i = data.find(b'TIKTIKRAW')
        if i >= 0: data = data[i+9:]
        else:
            i = data.find(b'TIKTIKTSGZ')
            if i >= 0: data = _limited_gzip(data[i+10:])
    if len(data) < 189 or data[0] != 0x47 or data[188] != 0x47:
        raise ValueError('invalid transport stream')
    return data


class Relay:
    def __init__(self):
        self.sessions = {}; self.resources = {}; self.lock = threading.Lock()
        owner = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                try:
                    content, kind = owner.get(self.path)
                    self.send_response(200); self.send_header('Content-Type', kind)
                    self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(content)))
                    self.end_headers(); self.wfile.write(content)
                except Exception as exc:
                    data = str(exc).encode('utf8','replace')[:300]
                    try:
                        self.send_response(502); self.send_header('Content-Type','text/plain')
                        self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
                    except (BrokenPipeError, ConnectionResetError): pass
        self.http = http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.http.daemon_threads = True
        self.base = f'http://127.0.0.1:{self.http.server_port}'
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True); self.thread.start()

    def add(self, url, edge, channel, referer):
        sid = secrets.token_urlsafe(18)
        with self.lock:
            self.sessions[sid] = {'url':url, 'edge':edge, 'channel':channel, 'referer':referer,
                                  'token':'', 'expires':0, 'token_lock':threading.Lock(),
                                  'playlist_lock':threading.Lock(), 'cached_playlist':None,
                                  'cached_until':0}
        return self.base + '/playlist/' + sid + '.m3u8'

    def playlist_token(self, session):
        with session['token_lock']:
            if time.time() < session['expires']: return session['token']
            url = session['edge'] + '/api/playlist-token?' + urllib.parse.urlencode({'slug':session['channel']})
            data = json.loads(_download(url, session['referer'], limit=100_000))
            token = data.get('token')
            if not token: raise ValueError('playlist token unavailable')
            session['token'] = str(token); session['expires'] = time.time() + max(5, min(50, int(data.get('ttl') or 120)//2))
            return session['token']

    def get_playlist(self, sid, session):
        # Players may open the same playlist several times at once. Serializing
        # refreshes prevents one rejected token from invalidating a newer token
        # that another request is already using.
        with session['playlist_lock']:
            if session['cached_playlist'] is not None and time.monotonic() < session['cached_until']:
                return session['cached_playlist'], 'application/vnd.apple.mpegurl'
            src = session['url']
            for attempt in range(3):
                token = self.playlist_token(session)
                query = urllib.parse.urlencode({'t':token, '_':int(time.time()*1000)})
                try:
                    text = _download(src + ('&' if '?' in src else '?') + query, session['referer'], limit=1_000_000).decode('utf8')
                    break
                except urllib.error.HTTPError as exc:
                    # This provider explicitly refreshes rejected, short-lived playlist tokens.
                    if exc.code != 403 or attempt == 2:
                        raise
                    with session['token_lock']:
                        session['expires'] = 0
                    time.sleep(.2 * (attempt + 1))
            if not text.lstrip().startswith('#EXTM3U'): raise ValueError('invalid playlist')
            if '#EXT-X-KEY:' in text and 'METHOD=NONE' not in text: raise ValueError('encrypted playlist is unsupported')
            output = []
            for line in text.splitlines():
                if line and not line.startswith('#'):
                    target = urllib.parse.urljoin(src, line.strip())
                    key = hashlib.sha256((sid+target).encode()).hexdigest()[:32]
                    with self.lock:
                        if len(self.resources) > 4000: self.resources.clear()
                        self.resources[key] = (target, session['referer'])
                    output.append(self.base+'/segment/'+key+'.ts')
                else: output.append(line)
            playlist = ('\n'.join(output)+'\n').encode()
            session['cached_playlist'] = playlist
            session['cached_until'] = time.monotonic() + 1.5
            return playlist, 'application/vnd.apple.mpegurl'

    def get(self, path):
        path = urllib.parse.urlsplit(path).path
        if path.startswith('/playlist/') and path.endswith('.m3u8'):
            sid = path[len('/playlist/'):-len('.m3u8')]
            session = self.sessions.get(sid)
            if not session: raise ValueError('unknown stream')
            return self.get_playlist(sid, session)
        if path.startswith('/segment/') and path.endswith('.ts'):
            key = path[len('/segment/'):-3]
            resource = self.resources.get(key)
            if not resource: raise ValueError('unknown segment')
            return unwrap_segment(_download(*resource)), 'video/mp2t'
        raise ValueError('unknown path')

    def close(self):
        self.http.shutdown(); self.http.server_close()

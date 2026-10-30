"""Implementation package for the Sports CLI terminal app."""
import os as _os
import ssl as _ssl
import subprocess as _subprocess
import sys as _sys
import time as _time


def _macos_roots():
    """System Keychain roots as a cached PEM bundle; /etc/ssl/cert.pem lacks some newer roots."""
    base = _os.environ.get('XDG_CACHE_HOME') or _os.path.join(_os.path.expanduser('~'), '.cache')
    path = _os.path.join(base, 'sports-live', 'system-roots.pem')
    try:
        if _time.time() - _os.path.getmtime(path) < 7 * 86400: return path
    except OSError:
        pass
    try:
        pem = _subprocess.run(['/usr/bin/security', 'find-certificate', '-a', '-p',
                               '/System/Library/Keychains/SystemRootCertificates.keychain'],
                              capture_output=True, timeout=10, check=True).stdout
        if pem.count(b'BEGIN CERTIFICATE') < 50: return None
        _os.makedirs(_os.path.dirname(path), mode=0o700, exist_ok=True)
        temporary = path + '.tmp'
        with open(temporary, 'wb') as out: out.write(pem)
        _os.replace(temporary, path)
        return path
    except (OSError, _subprocess.SubprocessError):
        return path if _os.path.isfile(path) else None


# Python.org macOS builds ship without root certificates, or link to a certifi
# bundle frozen at install time, so HTTPS fails on hosts with newer roots.
# Use the operating system's maintained roots in those cases.
_default = _ssl.get_default_verify_paths().cafile or ''
if not _os.environ.get('SSL_CERT_FILE') and (not _os.path.isfile(_default) or 'Python.framework' in _default):
    _bundles = [_macos_roots()] if _sys.platform == 'darwin' else []
    for _bundle in (*_bundles, '/etc/ssl/cert.pem', '/etc/ssl/certs/ca-certificates.crt'):
        if _bundle and _os.path.isfile(_bundle):
            _os.environ['SSL_CERT_FILE'] = _bundle
            break

"""Implementation package for the Sports CLI terminal app."""
import os as _os
import ssl as _ssl

# Python.org macOS builds ship without root certificates, or link to a certifi
# bundle frozen at install time that lacks newer roots, so HTTPS fails on some
# hosts. Prefer the operating system's maintained bundle in those cases.
_default = _ssl.get_default_verify_paths().cafile or ''
if not _os.environ.get('SSL_CERT_FILE') and (not _os.path.isfile(_default) or 'Python.framework' in _default):
    for _bundle in ('/etc/ssl/cert.pem', '/etc/ssl/certs/ca-certificates.crt'):
        if _os.path.isfile(_bundle):
            _os.environ['SSL_CERT_FILE'] = _bundle
            break

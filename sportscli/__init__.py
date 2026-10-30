"""Implementation package for the Sports CLI terminal app."""
import os as _os
import ssl as _ssl

# Python.org macOS builds ship without root certificates until "Install
# Certificates" is run, which makes every HTTPS request fail. Fall back to the
# operating system's bundle when Python's own default is missing.
if not _os.environ.get('SSL_CERT_FILE') and not _os.path.isfile(_ssl.get_default_verify_paths().cafile or ''):
    for _bundle in ('/etc/ssl/cert.pem', '/etc/ssl/certs/ca-certificates.crt'):
        if _os.path.isfile(_bundle):
            _os.environ['SSL_CERT_FILE'] = _bundle
            break

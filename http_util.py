"""HTTP GET with a safe fallback.

Some Windows Python installs fail to verify Let's Encrypt certificates (stale root
store). When that happens we switch to Windows' own curl.exe, which verifies the
certificate with the Windows certificate system. Verification is never turned off.
"""
import gzip
import os
import shutil
import ssl
import subprocess
import urllib.error
import urllib.request

UA = "albion-bm-helper/1.0 (personal black market tool)"
_use_curl = False


class HTTPStatusError(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.code = code


def _curl_path():
    win = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "curl.exe")
    return win if os.path.exists(win) else shutil.which("curl")


def _via_curl(url, timeout, out_path=None):
    curl = _curl_path()
    if not curl:
        raise RuntimeError("Cannot verify HTTPS certificates and curl.exe is not available")
    args = [curl, "-sS", "-L", "--compressed", "--max-time", str(timeout), "-A", UA,
            "-w", "\n%{http_code}"]
    if out_path:
        args += ["-o", out_path]
    p = subprocess.run(args + [url], capture_output=True, timeout=timeout + 15)
    if p.returncode != 0:
        raise urllib.error.URLError(p.stderr.decode(errors="replace").strip())
    out = p.stdout
    body, _, code = out.rpartition(b"\n")
    code = int(code or 0)
    if code != 200:
        raise HTTPStatusError(code)
    return body


def get(url, timeout=60, out_path=None):
    """Returns body bytes (or writes to out_path). Raises HTTPStatusError / URLError."""
    global _use_curl
    if not _use_curl:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
        except urllib.error.HTTPError as e:
            raise HTTPStatusError(e.code)
        except urllib.error.URLError as e:
            if isinstance(e.reason, ssl.SSLCertVerificationError):
                print("[net] Python can't verify the certificate here, using Windows curl instead")
                _use_curl = True
            else:
                raise
        else:
            if out_path:
                with open(out_path, "wb") as f:
                    f.write(body)
            return body
    return _via_curl(url, timeout, out_path)

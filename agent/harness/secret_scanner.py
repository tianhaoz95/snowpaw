import re

_PATTERNS = [
    re.compile(r'AKIA[0-9A-Z]{16}'),                         # AWS key
    re.compile(r'(?i)(api_key|secret|token)\s*=\s*["\'][^"\']{8,}'),
    re.compile(r'-----BEGIN (RSA |EC )?PRIVATE KEY-----'),
]

def scan(text: str) -> list[str]:
    """Scan *text* for patterns that look like credentials."""
    return [p.pattern for p in _PATTERNS if p.search(text)]

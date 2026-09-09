import ipaddress
import socket
from urllib.parse import urlparse, urlunparse, urljoin
import tldextract

def normalize_url(url: str) -> str:
    """
    Normalize URL: ensure scheme (http/https), lowercase hostname, strip fragments,
    normalize trailing slashes.
    """
    if not url:
        return ""
    
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
        
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    
    if ":" in netloc:
        host, port = netloc.split(":", 1)
        if (scheme == "http" and port == "80") or (scheme == "https" and port == "443"):
            netloc = host
            
    path = parsed.path
    if path == "":
        path = "/"
    elif len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
        
    query = parsed.query
    normalized = urlunparse((scheme, netloc, path, parsed.params, query, ""))
    return normalized

def is_same_registrable_domain(url1: str, url2: str) -> bool:
    """
    Compare if two URLs share the same registrable domain using tldextract.
    Supports IP addresses / localhost as matching domains.
    """
    p1 = urlparse(url1)
    p2 = urlparse(url2)
    h1 = (p1.hostname or "").lower()
    h2 = (p2.hostname or "").lower()

    if not h1 or not h2:
        return False

    # Direct match for exact hostnames, IP addresses, or localhost
    if h1 == h2:
        return True

    ext1 = tldextract.extract(url1)
    ext2 = tldextract.extract(url2)
    
    domain1 = ext1.domain if ext1.domain else h1
    domain2 = ext2.domain if ext2.domain else h2
    
    suffix1 = ext1.suffix if ext1.suffix else ""
    suffix2 = ext2.suffix if ext2.suffix else ""

    reg1 = f"{domain1}.{suffix1}".strip(".")
    reg2 = f"{domain2}.{suffix2}".strip(".")

    return reg1.lower() == reg2.lower() and bool(reg1)

def is_safe_url(url: str, allow_localhost: bool = False) -> bool:
    """
    Reject non http/https schemes and private/loopback IP addresses (SSRF Protection).
    If allow_localhost is True, loopback/private IPs are permitted (useful for local test suites/fixtures).
    """
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ("http", "https"):
        return False
        
    host = parsed.hostname
    if not host:
        return False
        
    if allow_localhost:
        return True

    if host.lower() in ("localhost", "localhost.localdomain", "loopback"):
        return False
        
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    except ValueError:
        try:
            addr_info = socket.getaddrinfo(host, None)
            for family, sockaddr, proto, canonname, sockaddr_val in addr_info:
                ip_str = sockaddr_val[0]
                ip = ipaddress.ip_address(ip_str)
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                    return False
        except socket.gaierror:
            pass
            
    return True

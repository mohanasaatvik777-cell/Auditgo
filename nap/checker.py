import re
import json
from typing import Dict, List, Any
from bs4 import BeautifulSoup
import phonenumbers
from crawler.fetcher import CrawledPage

def normalize_phone_number(raw_phone: str) -> str:
    """
    Parse phone number using phonenumbers library and convert to E.164 standard.
    Fallback to cleaned digits with '+' if default region parsing succeeds or fails gracefully.
    """
    if not raw_phone:
        return ""
    try:
        # Try parsing without region or with US/IN default fallbacks
        for region in [None, "US", "IN", "GB", "CA", "AU"]:
            try:
                parsed = phonenumbers.parse(raw_phone, region)
                if phonenumbers.is_valid_number(parsed) or phonenumbers.is_possible_number(parsed):
                    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
            except Exception:
                continue
    except Exception:
        pass

    # Fallback digit extraction
    digits = re.sub(r'[^\d+]', '', raw_phone)
    if not digits.startswith("+") and len(digits) >= 10:
        digits = "+" + digits
    return digits if len(digits) >= 8 else raw_phone.strip()

def normalize_address(raw_address: str) -> str:
    """
    Normalize whitespace, casing, punctuation, and standard street abbreviations.
    """
    if not raw_address:
        return ""
    
    addr = raw_address.strip().lower()
    # Normalize punctuation and spaces
    addr = re.sub(r'[\r\n\t]+', ' ', addr)
    addr = re.sub(r'[^\w\s,.-]', '', addr)
    addr = re.sub(r'\s+', ' ', addr)
    
    # Common abbreviation replacements
    abbreviations = {
        r'\bstreet\b': 'st',
        r'\bavenue\b': 'ave',
        r'\broad\b': 'rd',
        r'\bboulevard\b': 'blvd',
        r'\bdrive\b': 'dr',
        r'\bsuite\b': 'ste',
        r'\bapartment\b': 'apt',
        r'\bbuilding\b': 'bldg',
        r'\bfloor\b': 'fl'
    }
    for full, abbr in abbreviations.items():
        addr = re.sub(full, abbr, addr)
        
    return addr.strip()

class NAPChecker:
    def __init__(self, crawl_data: Dict[str, Any]):
        self.crawled_pages: Dict[str, CrawledPage] = crawl_data.get("crawled_pages", {})
        self.phone_occurrences = [] # list of dicts: {page, raw, normalized, source, confidence}
        self.address_occurrences = []
        self.name_occurrences = []

    def check(self) -> List[Dict[str, Any]]:
        self._extract_nap_data()
        
        report = []
        report.append(self._analyze_field("phone", self.phone_occurrences, normalize_phone_number))
        report.append(self._analyze_field("address", self.address_occurrences, normalize_address))
        report.append(self._analyze_field("name", self.name_occurrences, lambda s: s.strip().lower()))
        
        return report

    def _extract_nap_data(self):
        for url, page in self.crawled_pages.items():
            if page.status_code != 200 or "text/html" not in page.content_type:
                continue

            soup = BeautifulSoup(page.content, "lxml")
            
            # 1. JSON-LD Extraction (Highest Confidence: 0.95)
            json_ld_tags = soup.find_all("script", type="application/ld+json")
            for tag in json_ld_tags:
                try:
                    data = json.loads(tag.string or "")
                    if isinstance(data, dict):
                        data_list = [data]
                    elif isinstance(data, list):
                        data_list = data
                    else:
                        data_list = []
                        
                    for item in data_list:
                        if not isinstance(item, dict):
                            continue
                        t = item.get("@type", "")
                        if isinstance(t, list):
                            t = " ".join(t)
                        if any(k in str(t) for k in ["LocalBusiness", "Organization", "PostalAddress", "Store", "Restaurant"]):
                            # Phone
                            p = item.get("telephone")
                            if p:
                                self.phone_occurrences.append({
                                    "page": url, "raw": str(p), "source": "json_ld", "confidence": 0.95
                                })
                            # Name
                            n = item.get("name")
                            if n:
                                self.name_occurrences.append({
                                    "page": url, "raw": str(n), "source": "json_ld", "confidence": 0.95
                                })
                            # Address
                            addr_obj = item.get("address")
                            if isinstance(addr_obj, dict):
                                parts = [
                                    addr_obj.get("streetAddress", ""),
                                    addr_obj.get("addressLocality", ""),
                                    addr_obj.get("addressRegion", ""),
                                    addr_obj.get("postalCode", ""),
                                    addr_obj.get("addressCountry", "")
                                ]
                                full_a = ", ".join([p for p in parts if p])
                                if full_a:
                                    self.address_occurrences.append({
                                        "page": url, "raw": full_a, "source": "json_ld", "confidence": 0.95
                                    })
                            elif isinstance(addr_obj, str) and addr_obj:
                                self.address_occurrences.append({
                                    "page": url, "raw": addr_obj, "source": "json_ld", "confidence": 0.95
                                })
                except Exception:
                    pass

            # Target priority pages for HTML parsing
            url_lower = url.lower()
            is_target_page = any(k in url_lower for k in ["contact", "about", "location", "footer", "reach-us"])
            
            # 2. Structured HTML / Footer / Contact Blocks (Confidence: 0.85)
            # Find telephone href links
            for tel_link in soup.find_all("a", href=lambda h: h and h.startswith("tel:")):
                raw_tel = tel_link["href"].replace("tel:", "").strip()
                if raw_tel:
                    self.phone_occurrences.append({
                        "page": url, "raw": raw_tel, "source": "tel_link", "confidence": 0.85
                    })

            # Loose Text RegEx Patterns for Phone Numbers (Confidence: 0.70)
            if is_target_page:
                visible_text = soup.get_text(separator=" ")
                # Phone Regex pattern matching international and local numbers
                phone_matches = re.findall(r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}', visible_text)
                for pm in phone_matches:
                    pm_clean = pm.strip()
                    if len(re.sub(r'\D', '', pm_clean)) >= 10:
                        self.phone_occurrences.append({
                            "page": url, "raw": pm_clean, "source": "text_pattern", "confidence": 0.70
                        })

    def _analyze_field(self, field_name: str, occurrences: List[Dict[str, Any]], norm_fn) -> Dict[str, Any]:
        if not occurrences:
            return {
                "field": field_name,
                "pages_compared": [],
                "values": [],
                "normalized_values": [],
                "confidence": 0.0,
                "verdict": "insufficient_evidence"
            }

        # Deduplicate occurrences per page/raw value
        unique_occ = []
        seen = set()
        for occ in occurrences:
            key = (occ["page"], occ["raw"].strip())
            if key not in seen:
                seen.add(key)
                occ["norm"] = norm_fn(occ["raw"])
                unique_occ.append(occ)

        pages_compared = list(dict.fromkeys([o["page"] for o in unique_occ]))
        raw_values = [o["raw"] for o in unique_occ]
        norm_values = [o["norm"] for o in unique_occ]
        avg_confidence = round(sum(o["confidence"] for o in unique_occ) / len(unique_occ), 2)

        # Verdict logic
        if len(unique_occ) < 2:
            verdict = "insufficient_evidence"
        else:
            unique_raws = set(raw_values)
            unique_norms = set([n for n in norm_values if n])

            if len(unique_raws) == 1:
                verdict = "consistent"
            elif len(unique_norms) == 1:
                verdict = "formatting_difference"
            else:
                verdict = "mismatch"

        return {
            "field": field_name,
            "pages_compared": pages_compared,
            "values": raw_values,
            "normalized_values": norm_values,
            "confidence": avg_confidence,
            "verdict": verdict
        }

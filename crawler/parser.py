import re
from bs4 import BeautifulSoup, Comment

class TextChunk:
    def __init__(self, text: str, start_offset: int, end_offset: int, tag_name: str = ""):
        self.text = text
        self.start_offset = start_offset
        self.end_offset = end_offset
        self.tag_name = tag_name

class HTMLParserResult:
    def __init__(self, raw_html: str):
        self.raw_html = raw_html
        self.soup = BeautifulSoup(raw_html, "lxml")
        self.visible_text = ""
        self.chunks = []
        self._extract_text_with_offsets()
        
    def _extract_text_with_offsets(self):
        """
        Extract clean visible text passages while keeping exact character offsets
        back into raw HTML or raw text body.
        """
        # Create clean text string and record offsets
        if not self.raw_html:
            return

        # Strip scripts/styles/comments for visible text candidate generation
        body = self.soup.find("body") or self.soup
        
        # Clone soup for text stripping
        temp_soup = BeautifulSoup(str(body), "lxml")
        for s in temp_soup(["script", "style", "meta", "noscript", "svg", "header", "footer", "nav"]):
            s.decompose()
            
        for comment in temp_soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()
            
        cleaned_text = temp_soup.get_text(separator=" ", strip=True)
        self.visible_text = cleaned_text
        
        # Sentence / passage chunking with offsets in cleaned visible text
        raw_text = temp_soup.get_text()
        
        # Find exact matches in raw_html for raw text occurrences
        sentences = re.split(r'(?<=[.!?])\s+', cleaned_text)
        current_pos = 0
        for sent in sentences:
            sent = sent.strip()
            if not sent or len(sent) < 15:
                continue
                
            idx = self.raw_html.find(sent, current_pos)
            if idx == -1:
                # Try finding without strict spacing
                idx = self.raw_html.find(sent)
                
            if idx != -1:
                chunk = TextChunk(
                    text=sent,
                    start_offset=idx,
                    end_offset=idx + len(sent)
                )
                self.chunks.append(chunk)
                current_pos = idx + len(sent)
            else:
                # Store chunk with synthetic offset if exact html match isn't found immediately
                chunk = TextChunk(
                    text=sent,
                    start_offset=0,
                    end_offset=len(sent)
                )
                self.chunks.append(chunk)

def parse_html(raw_html: str) -> HTMLParserResult:
    return HTMLParserResult(raw_html)

"""Text normalization, noise removal, token extraction, and mojibake recovery."""
import re
import unicodedata
from typing import List, Set, Tuple, Optional

# Noise patterns inside parentheses/brackets
PAREN_NOISE_RE = re.compile(
    r"[\[\(]\s*(?:"
    r"mv|m/v|official\s*(?:music\s*)?video|official\s*audio|official\s*hd|"
    r"official\s*track|lyrics?|가사|4k|hd|remastered|리마스터|티저|teaser|"
    r"live\s*clip|special\s*clip|visualizer|color\s*coded\s*lyrics?|"
    r"선공개|풀버전|audio|audio\s*video|vertical\s*video"
    r")\s*[^\]\)]*[\]\)]",
    re.IGNORECASE,
)

# Trailing suffix noise
SUFFIX_NOISE_RE = re.compile(
    r"\s*(?:[-–|/:]\s*)?(?:"
    r"official\s*(?:music\s*)?video|official\s*audio|lyric\s*video|visualizer|"
    r"official\s*video|audio\s*track|special\s*clip|live\s*clip|teaser|mv|m/v"
    r")\s*$",
    re.IGNORECASE,
)

# Version tags detection
VERSION_KEYWORDS = [
    ("live", re.compile(r"[\(\[]?\s*\b(?:live(?:\s*ver(?:sion)?|\s*clip)?|라이브)\b\s*[\)\]]?", re.IGNORECASE)),
    ("inst", re.compile(r"[\(\[]?\s*\b(?:inst(?:\.|rumental)?|mr|반주)\b\s*[\)\]]?", re.IGNORECASE)),
    ("remix", re.compile(r"[\(\[]?\s*\b(?:remix|리믹스)\b\s*[\)\]]?", re.IGNORECASE)),
    ("acoustic", re.compile(r"[\(\[]?\s*\b(?:acoustic(?:\s*ver(?:sion)?)?|어쿠스틱)\b\s*[\)\]]?", re.IGNORECASE)),
    ("cover", re.compile(r"[\(\[]?\s*\b(?:cover|커버)\b\s*[\)\]]?", re.IGNORECASE)),
]

# Featuring patterns
FEAT_RE = re.compile(
    r"[\(\[]?\s*(?:feat\.?|ft\.?|prod\.?\s*by|with)\s+([^\)\]\-–]+)[\)\]]?",
    re.IGNORECASE,
)

# Punctuation and non-alphanumeric strip regex
PUNCT_RE = re.compile(r"[\s\-_–—.,!?:;\'\"~`@#$%^&*()\[\]{}|\\/<>+=]+")


def normalize_text(text: Optional[str]) -> str:
    """Normalize text using NFKC, lowercase, and removing whitespace/punctuation."""
    if not text:
        return ""
    # Unicode NFKC normalization
    text = unicodedata.normalize("NFKC", text)
    # Lowercase
    text = text.lower()
    # Strip punctuation and spaces
    return PUNCT_RE.sub("", text)


def clean_noise(text: str) -> str:
    """Remove video noise tokens (MV, Official Video, Lyrics, 4K, etc.)."""
    if not text:
        return ""
    # Remove parenthesized/bracketed noise
    cleaned = PAREN_NOISE_RE.sub(" ", text)
    # Remove trailing suffix noise
    cleaned = SUFFIX_NOISE_RE.sub("", cleaned)
    # Strip leading/trailing symbols without stripping valid trailing parentheses
    cleaned = cleaned.strip(" -–—_|/: \t\r\n")
    return cleaned.strip()


def extract_version_tag(text: str) -> Tuple[str, str]:
    """Detect version tag (studio, live, inst, remix, acoustic, cover) and strip it from text."""
    if not text:
        return "studio", ""
    detected_tag = "studio"
    cleaned = text
    for tag, pattern in VERSION_KEYWORDS:
        if pattern.search(cleaned):
            detected_tag = tag
            cleaned = pattern.sub(" ", cleaned)
            break
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return detected_tag, cleaned


def extract_features(text: str) -> Tuple[List[str], str]:
    """Extract featured artists (feat, ft, prod by, with) and remove them from title."""
    if not text:
        return [], ""
    featured: List[str] = []
    def _repl(match):
        raw_artists = match.group(1).strip()
        # Split multiple featured artists by comma, &, /
        for part in re.split(r"[,&/]", raw_artists):
            p = part.strip()
            if p:
                featured.append(p)
        return " "

    cleaned = FEAT_RE.sub(_repl, text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return featured, cleaned


def extract_parenthetical_subtokens(text: str) -> Set[str]:
    """Extract outer text and inner parenthetical tokens for bilingual titles.
    
    e.g., '좋은 날 (Good Day)' -> {'좋은날', 'goodday'}
    """
    results: Set[str] = set()
    norm_full = normalize_text(text)
    if norm_full:
        results.add(norm_full)

    # Find all paren contents (...) or [...]
    parens = re.findall(r"[\(\[](.*?)[\)\]]", text)
    for p in parens:
        p_clean = clean_noise(p)
        _, p_no_ver = extract_version_tag(p_clean)
        _, p_final = extract_features(p_no_ver)
        norm_p = normalize_text(p_final)
        if norm_p and len(norm_p) >= 1:
            results.add(norm_p)

    # Outside paren content
    outside = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", text)
    outside = clean_noise(outside)
    _, outside_no_ver = extract_version_tag(outside)
    _, outside_final = extract_features(outside_no_ver)
    norm_outside = normalize_text(outside_final)
    if norm_outside and len(norm_outside) >= 1:
        results.add(norm_outside)

    return results


def extract_title_variants(title: str) -> Set[str]:
    """Return all normalized title variants for a track title.
    
    e.g., '좋은 날 (Good Day)' -> {'좋은날', 'goodday', '좋은날goodday', 'goodday좋은날'}
    """
    if not title:
        return set()

    cleaned = clean_noise(title)
    _, no_version = extract_version_tag(cleaned)
    _, core_title = extract_features(no_version)

    variants: Set[str] = set()

    # Split on title/artist delimiters if present (e.g. 'IU _ Good Day(좋은 날)')
    segments = re.split(r"\s*[-_–—|]\s*", core_title)
    for seg in segments:
        seg_clean = seg.strip()
        if seg_clean:
            variants.update(extract_parenthetical_subtokens(seg_clean))

    variants.update(extract_parenthetical_subtokens(core_title))
    norm_core = normalize_text(core_title)
    if norm_core:
        variants.add(norm_core)

    # If variants include distinct sub-tokens A and B, also add combined A+B and B+A
    sub_items = [v for v in variants if v != norm_core and len(v) >= 2]
    if len(sub_items) >= 2:
        for i in range(len(sub_items)):
            for j in range(len(sub_items)):
                if i != j:
                    variants.add(sub_items[i] + sub_items[j])

    return variants


def extract_artist_variants(artist: str) -> Set[str]:
    """Extract artist variants (e.g. 'IU(아이유)' -> {'iu', '아이유'})."""
    if not artist:
        return set()
    cleaned = clean_noise(artist)
    variants = extract_parenthetical_subtokens(cleaned)
    norm = normalize_text(cleaned)
    if norm:
        variants.add(norm)
    return variants


def split_artist_title_candidates(text: str) -> List[Tuple[str, str]]:
    """Split a string like 'Artist - Title' or 'Title - Artist' into candidates.
    
    Returns [(A, B), (B, A)] if separator is present, or [(text, ''), ('', text)].
    """
    cleaned = clean_noise(text)
    # Check common separators: ' - ', ' _ ', ' | ', ' / ', '–'
    parts = re.split(r"\s*[-_–—|]\s*", cleaned, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        part_a, part_b = parts[0].strip(), parts[1].strip()
        return [
            (part_a, part_b),  # (Artist, Title) candidate
            (part_b, part_a),  # (Title, Artist) candidate
        ]
    return [(cleaned, "")]


def recover_mojibake(text: Optional[str]) -> str:
    """Recover EUC-KR / CP949 text wrongly decoded as Latin-1 / ISO-8859-1.
    
    e.g., 'ÀÎÀ¯' (0xC0 0xCE 0xC0 0xAF) -> '아이유'
    """
    if not text:
        return ""
    # If the text already has Hangul syllables, it's likely not pure mojibake
    has_hangul = any("\uac00" <= ch <= "\ud7a3" for ch in text)
    if has_hangul:
        return text

    # Check if string contains extended Latin-1 characters (0x80 - 0xFF)
    if any(0x80 <= ord(ch) <= 0xFF for ch in text):
        try:
            raw_bytes = text.encode("latin-1")
            decoded = raw_bytes.decode("cp949")
            # Verify if decoded has Hangul syllables
            if any("\uac00" <= ch <= "\ud7a3" for ch in decoded):
                return decoded
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass

    return text

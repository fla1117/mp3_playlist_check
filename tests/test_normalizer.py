"""Unit tests for normalizer, noise cleaner, version extractor, and mojibake recovery."""
import pytest
from src.matcher.normalizer import (
    clean_noise,
    extract_artist_variants,
    extract_features,
    extract_title_variants,
    extract_version_tag,
    normalize_text,
    recover_mojibake,
    split_artist_title_candidates,
)
from src.scanner.fallback_parser import parse_filename_fallback


def test_clean_noise_bracket_and_suffix():
    raw = "[MV] 아이유(IU) - 좋은 날 (Good Day) (Official Video)"
    cleaned = clean_noise(raw)
    assert "[MV]" not in cleaned
    assert "Official Video" not in cleaned
    assert "아이유(IU)" in cleaned
    assert "좋은 날" in cleaned

    # 4K, 가사, Remastered
    raw2 = "BTS - Butter (Lyrics / 가사) [4K Remastered]"
    cleaned2 = clean_noise(raw2)
    assert "Lyrics" not in cleaned2
    assert "가사" not in cleaned2
    assert "4K" not in cleaned2
    assert "Remastered" not in cleaned2
    assert "BTS - Butter" in cleaned2


def test_extract_version_tag():
    # Studio default
    v_tag, title = extract_version_tag("아이유 - 좋은 날")
    assert v_tag == "studio"
    assert "좋은 날" in title

    # Live
    v_tag, title = extract_version_tag("아이유 - 좋은 날 (Live ver.)")
    assert v_tag == "live"
    assert "Live" not in title

    # Instrumental / MR
    v_tag, title = extract_version_tag("Dynamite (Inst.)")
    assert v_tag == "inst"

    v_tag, title = extract_version_tag("Hype Boy (MR)")
    assert v_tag == "inst"

    # Remix
    v_tag, title = extract_version_tag("Ditto (Club Remix)")
    assert v_tag == "remix"

    # Acoustic
    v_tag, title = extract_version_tag("Celebrity (Acoustic ver.)")
    assert v_tag == "acoustic"

    # Cover
    v_tag, title = extract_version_tag("IU - Like You (Cover)")
    assert v_tag == "cover"


def test_extract_features():
    raw = "Eight (Feat. & Prod. by SUGA of BTS)"
    feats, cleaned = extract_features(raw)
    assert any("SUGA" in f for f in feats)
    assert "Feat." not in cleaned
    assert "Eight" in cleaned

    raw2 = "Love Me Like You (with IU)"
    feats2, cleaned2 = extract_features(raw2)
    assert "IU" in feats2
    assert "with" not in cleaned2


def test_extract_title_variants_bilingual():
    title = "좋은 날 (Good Day)"
    variants = extract_title_variants(title)
    # Should include Korean sub-token, English sub-token, and combined
    assert "좋은날" in variants
    assert "goodday" in variants

    title2 = "[MV] IU(아이유) _ Good Day(좋은 날)"
    variants2 = extract_title_variants(title2)
    assert "goodday" in variants2
    assert "좋은날" in variants2


def test_extract_artist_variants():
    artist = "IU(아이유)"
    variants = extract_artist_variants(artist)
    assert "iu" in variants
    assert "아이유" in variants


def test_split_artist_title_candidates():
    # ' - ' delimiter
    cands = split_artist_title_candidates("아이유 - 좋은 날")
    assert len(cands) == 2
    assert cands[0] == ("아이유", "좋은 날")
    assert cands[1] == ("좋은 날", "아이유")

    # ' _ ' delimiter
    cands2 = split_artist_title_candidates("IU _ Good Day")
    assert len(cands2) == 2
    assert cands2[0] == ("IU", "Good Day")
    assert cands2[1] == ("Good Day", "IU")


def test_recover_mojibake():
    # '아이유' encoded in CP949 and mistakenly decoded as Latin-1
    mojibake = "아이유".encode("cp949").decode("latin-1")
    restored = recover_mojibake(mojibake)
    assert restored == "아이유"

    # Normal text should remain untouched
    normal = "아이유 (IU) - 좋은 날"
    assert recover_mojibake(normal) == normal

    ascii_text = "Good Day"
    assert recover_mojibake(ascii_text) == ascii_text


def test_filename_fallback_parser():
    p1 = "01. 아이유 - 좋은 날.mp3"
    artist, title = parse_filename_fallback(p1)
    assert artist == "아이유"
    assert title == "좋은 날"

    p2 = "12 - BTS - Dynamite.flac"
    artist2, title2 = parse_filename_fallback(p2)
    assert artist2 == "BTS"
    assert title2 == "Dynamite"

    p3 = "03_NewJeans_Ditto.m4a"
    artist3, title3 = parse_filename_fallback(p3)
    assert artist3 == "NewJeans"
    assert title3 == "Ditto"

    # No separator
    p4 = "04. JustATitle.mp3"
    artist4, title4 = parse_filename_fallback(p4)
    assert artist4 is None or artist4 != ""
    assert "JustATitle" in title4

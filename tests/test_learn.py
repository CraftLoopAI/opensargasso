"""The Learn page content: the same sections in every language, each with text and sources."""
import json
import pathlib

LEARN = pathlib.Path(__file__).parent.parent / "site" / "learn.js"
VIEWS = {"#beaches", "#learn", "#managers", "#data"}


def content():
    text = LEARN.read_text(encoding="utf-8")
    return json.loads(text[text.index("{"):text.rindex("}") + 1])


def test_every_language_has_the_same_sections_with_sources():
    langs = content()
    assert set(langs) == {"en", "fr", "nl"}
    ids = {lang: [s["id"] for s in langs[lang]["sections"]] for lang in langs}
    assert ids["fr"] == ids["en"] and ids["nl"] == ids["en"], ids
    for lang, page in langs.items():
        assert page["title"] and page["intro"] and page["sourcesLabel"], lang
        for s in page["sections"]:
            assert s["title"] and s["text"] and all(p.strip() for p in s["text"]), (lang, s["id"])
            assert s["sources"] and all(url.startswith("https://") and label for label, url in s["sources"]), (lang, s["id"])
            if "action" in s:
                assert s["action"][1] in VIEWS, (lang, s["id"])
        assert "—" not in json.dumps(page, ensure_ascii=False), lang      # house style: no em dashes


def test_sources_match_across_languages():
    langs = content()
    urls = {lang: [[u for _, u in s["sources"]] for s in langs[lang]["sections"]] for lang in langs}
    assert urls["fr"] == urls["en"] and urls["nl"] == urls["en"]

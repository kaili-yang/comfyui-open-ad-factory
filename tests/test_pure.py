import json

import pytest
import torch

from open_ad_factory import assemble, fetch, judge, storyboard as sb

PRODUCT_HTML = """<html><head><title>Fallback title</title>
<meta property="og:title" content="OG Name">
<meta property="og:image" content="/img/og.jpg">
<meta property="og:site_name" content="Acme">
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[{"@type":"WebPage"},{"@type":"Product","name":"Acme Bottle","description":"<p>Keeps   drinks cold for 24h.</p>",
 "brand":{"@type":"Brand","name":"Acme"},"image":["https://cdn.acme.com/a.jpg",{"url":"//cdn.acme.com/b.jpg"}],
 "offers":{"@type":"Offer","price":"29.00","priceCurrency":"USD"}}]}
</script></head><body></body></html>"""


def make_board(n=4):
    roles = sb.LAYOUTS[n]
    return {
        "product_name": "Acme Bottle", "audience": "hikers", "angle": "cold all day", "voice": "a warm female voice",
        "headline": "Cold for 24 hours", "cta": "Shop now", "post_caption": "Stay cold.", "hashtags": ["hydration", "#hike"],
        "shots": [{"role": r, "keyframe_prompt": f"kf {r}", "motion_prompt": f"motion {r}", "voiceover": f"Say \"{r}\"", "caption": f"cap {r}"} for r in roles],
    }


def test_parse_product_jsonld_wins_over_og():
    info = fetch.parse_product_html(PRODUCT_HTML, "https://acme.com/p/bottle")
    assert info["name"] == "Acme Bottle"
    assert info["description"] == "Keeps drinks cold for 24h."
    assert info["brand"] == "Acme"
    assert (info["price"], info["currency"]) == ("29.00", "USD")
    assert info["images"] == ["https://cdn.acme.com/a.jpg", "https://cdn.acme.com/b.jpg", "https://acme.com/img/og.jpg"]
    assert "Price: 29.00 USD" in fetch.format_product_brief(info)


def test_parse_product_og_only():
    html = '<meta property="og:title" content="Thing"><meta name="description" content="A thing.">'
    info = fetch.parse_product_html(html, "https://x.com/")
    assert info["name"] == "Thing" and info["description"] == "A thing."


def test_parse_shopify_json():
    info = fetch.parse_shopify_json({"product": {"title": "Glide Legging", "body_html": "<b>Soft</b>", "vendor": "VEYRIN",
                                                 "variants": [{"price": "88.00"}], "images": [{"src": "https://cdn/x.png"}]}}, "u")
    assert info["name"] == "Glide Legging" and info["description"] == "Soft" and info["images"] == ["https://cdn/x.png"]
    assert info["brand"] == "VEYRIN" and info["price"] == "88.00"


def test_demo_store_page_parses():
    """The bundled VEYRIN demo page is what every default and demo points at; it must stay parseable."""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "site", "demo-store", "veyrin-glide-legging", "index.html")
    with open(path, encoding="utf-8") as f:
        info = fetch.parse_product_html(f.read(), "https://kaili-yang.github.io/comfyui-open-ad-factory/demo-store/veyrin-glide-legging/")
    assert info["name"] == 'Glide High-Rise Legging 25"' and info["brand"] == "VEYRIN"
    assert (info["price"], info["currency"]) == ("88.00", "USD")
    assert len(info["images"]) == 3 and info["images"][0].endswith("glide-legging-front.jpg")


def test_fetch_rejects_bad_scheme():
    with pytest.raises(ValueError):
        fetch.fetch_product("ftp://x")


def test_storyboard_roundtrip_with_fences_and_trailing_commas():
    text = "Sure!\n```json\n" + json.dumps(make_board()).replace("]}", "],}", 1) + "\n```"
    board = sb.parse_storyboard(text, 4)
    assert board["hashtags"] == ["#hydration", "#hike"]
    assert [s["role"] for s in board["shots"]] == ["hook", "problem", "solution", "cta"]


def test_storyboard_accepts_padded_and_cased_keys():
    # Seen from Qwen3-4B: '" shots": [...]'
    text = json.dumps(make_board()).replace('"shots"', '" shots"').replace('"voiceover"', '"Voiceover "')
    assert sb.parse_storyboard(text, 4)["shots"][0]["voiceover"] == 'Say "hook"'


def test_storyboard_rejects_wrong_shot_count():
    with pytest.raises(ValueError, match="expected 5 shots"):
        sb.parse_storyboard(json.dumps(make_board(4)), 5)


def test_storyboard_rejects_missing_shot_field():
    board = make_board()
    board["shots"][2]["voiceover"] = " "
    with pytest.raises(ValueError, match="shot 3"):
        sb.parse_storyboard(json.dumps(board), 4)


def test_prompts():
    board = make_board()
    assert "<image1>" in sb.keyframe_prompt(board, 0)
    vp = sb.video_prompt(board, 1)
    assert vp.startswith("motion problem. A warm female voice says") and "\"Say 'problem'\"" in vp
    assert sb.keyframe_prompt(board, 0).startswith("kf hook. Keep the product")
    user = sb.build_user_prompt("Product: X", 5, 4, "cinematic", "", "English", "- Shot 1: faster")
    assert "exactly 5 shots" in user and "20-second" in user and "FEEDBACK" in user and "5. cta" in user
    assert "FEEDBACK" not in sb.build_user_prompt("Product: X", 3, 5, "ugc", "", "English")


def test_judge_score_and_report():
    raw = {"scores": {k: 10 for k in judge.RUBRIC}, "fixes": ["Shot 1: start with motion"], "strengths": ["clear"], "verdict": "Good."}
    review = judge.parse_review(json.dumps(raw))
    assert review["score"] == 100.0
    raw["scores"] = {k: 5 for k in judge.RUBRIC} | {"hook": 15}
    review = judge.parse_review(json.dumps(raw))
    assert review["scores"]["hook"] == 10.0
    assert review["score"] == 62.5
    assert "62.5 / 100" in judge.report(review) and judge.feedback(review) == "- Shot 1: start with motion"


def test_judge_missing_score():
    with pytest.raises(ValueError, match="hook"):
        judge.parse_review('{"scores": {"pacing": 3}}')


def test_product_canvas_and_end_card():
    img = torch.rand(1, 300, 500, 3)
    canvas = assemble.product_canvas(img, 768, 1344)
    assert canvas.shape == (1, 1344, 768, 3) and canvas.min() >= 0 and canvas.max() <= 1
    card = assemble.end_card(img, 704, 1280, 10, "Headline here", "Shop now")
    assert card.shape == (10, 1280, 704, 3)


def test_caption_script_detection_and_wrapping():
    assert [assemble.script_of(s) for s in ("ONE LINK", "UN ENLACE", "リンクひとつ", "링크 하나", "一个链接", "एक लिंक")] == \
        ["latin", "latin", "ja", "ko", "zh", "hi"]
    from PIL import Image, ImageDraw
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    font = assemble._font(40)
    # Korean keeps its spaces and wraps at words; Chinese wraps per character
    assert all(" " in line or len(line) <= 3 for line in assemble._wrap(draw, "새로운 방법 링크 하나로 광고 완성", font, 160))
    assert assemble._wrap(draw, "THE NEW WAY IS HERE", font, 10000) == ["THE NEW WAY IS HERE"]


def test_hindi_needs_raqm():
    from PIL import features
    assert assemble.can_render("नया तरीका") == features.check_feature("raqm")
    assert assemble.can_render("ONE LINK")


def test_auto_background_picks_white_for_packshots():
    packshot = torch.ones(1, 200, 200, 3)
    packshot[:, 80:120, 80:120] = 0.1
    canvas = assemble.product_canvas(packshot, 100, 200, background="auto")
    assert canvas[0, 0, 0].tolist() == [1.0, 1.0, 1.0]
    photo = torch.rand(1, 200, 200, 3)
    assert assemble.product_canvas(photo, 100, 200, background="auto")[0, 0, 0].mean() < 0.99


def test_concat_fits_audio_to_frames():
    a = torch.rand(25, 64, 36, 3)
    b = torch.rand(50, 32, 18, 3)
    audio_a = {"waveform": torch.rand(1, 2, 44100 // 2), "sample_rate": 44100}
    audio_b = {"waveform": torch.rand(1, 1, 16000 * 3), "sample_rate": 16000}
    images, audio = assemble.concat([(a, audio_a), (b, audio_b), (a, None)], fps=25)
    assert images.shape == (100, 64, 36, 3)
    assert audio["sample_rate"] == 44100 and audio["waveform"].shape == (1, 2, 44100 * 4)

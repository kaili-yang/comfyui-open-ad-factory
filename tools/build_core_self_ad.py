"""Build example_workflows/open_ad_factory_self_ad_core.json: the Open Ad Factory self-ad using ONLY built-in ComfyUI nodes.

For hosted environments where custom nodes cannot be installed but the official template models are preinstalled.
The storyboard is written out here instead of by the planner node, the product photo is generated from a prompt
(no third-party imagery), captions use Draw Text Overlay, and Gemma 4 still grades the finished cut.

    python tools/build_core_self_ad.py --server http://127.0.0.1:8188 --out build/raw_self_ad_core.json
"""
import argparse
import json
import os
import urllib.request

from build_workflow import Builder, first, load_template

WIDTH, HEIGHT, SECONDS = 704, 1280, 5

HERO_PROMPT = (
    "Vertical studio product photograph for a tech launch ad. A modern black smartphone stands upright on a glossy lime-yellow "
    "pedestal against a smooth deep violet gradient background, soft rim light and a gentle reflection on the pedestal. "
    "The phone screen shows a sleek dark app interface: at the top the bold white title \"OPEN AD FACTORY\", below it a rounded "
    "URL bar, then a row of four small vertical video thumbnails in purple, gray, blue and yellow, then a huge bright yellow "
    "number \"92\" with \"/100\" under it, and at the bottom a yellow pill button reading \"GENERATE AD\". "
    "Crisp, photorealistic, premium advertising photography, centered composition, generous empty space around the phone."
)

CREATOR = "a friendly woman in her late twenties with shoulder-length curly dark hair, wearing a mustard-yellow hoodie"

SHOTS = [
    {
        "caption": "ONE LINK. ONE AD.",
        "refs": "hero",
        "keyframe": f"Vertical selfie-style frame in a cozy home studio with a ring light and plants. {CREATOR} holds the phone from <image1> close to the camera with the screen facing the viewer, eyebrows raised in excitement. Keep the phone and its screen exactly as in <image1>. Photorealistic, natural light, no extra text.",
        "motion": "She leans toward the camera with wide eyes and taps the phone screen, which glows brighter. Handheld selfie camera with a slight natural shake. Quiet room tone. She says to the camera in an excited, upbeat voice: \"I just made a whole video ad from one link!\"",
    },
    {
        "caption": "NO CREDITS. NO API KEYS.",
        "refs": "shot1+hero",
        "keyframe": "The same woman from <image1>, same hoodie and hair, now sits at a cluttered desk in warm evening light, frowning at a laptop that shows a red pop-up reading \"OUT OF CREDITS\". The phone from <image2> lies face up on the desk. Medium shot, photorealistic.",
        "motion": "She sighs, closes the laptop lid with a soft thud, then picks up the phone from the desk and smiles. Static camera. Paper rustles and a soft laptop click. She says in a relieved voice: \"No more paying per video for closed AI tools.\"",
    },
    {
        "caption": "PASTE A LINK. PRESS RUN.",
        "refs": "hero",
        "keyframe": "Close-up of two hands holding the phone from <image1> over a dark wooden desk, the screen lit and colorful light from the screen falling on the fingers. Keep the phone and its screen exactly as in <image1>. Shallow depth of field, photorealistic.",
        "motion": "A thumb taps the yellow GENERATE AD button, the four thumbnails on the screen light up one after another, and the camera slowly pushes in toward the screen. Soft interface clicks and a rising whoosh. A warm female voice-over says: \"Paste a product link. Open models shoot and voice it on your GPU.\"",
    },
    {
        "caption": "FREE ON GITHUB",
        "refs": "shot1+hero",
        "keyframe": "The same woman from <image1>, same hoodie and hair, stands in front of a bright yellow wall with a big bold black banner reading \"FREE ON GITHUB\" above her head. She holds the phone from <image2> next to her face with the screen toward the camera, grinning. Colorful confetti in the air. Medium shot, photorealistic.",
        "motion": "She points at the yellow 92 on the phone screen and laughs as confetti drifts down, and the camera slowly pulls back. Upbeat pop whoosh and confetti rustle. She says to the camera in a cheerful voice: \"It even grades its own ad. Get Open Ad Factory free on GitHub!\"",
    },
]

JUDGE_PROMPT = """You are a strict short-video ad reviewer. Watch this vertical video ad for Open Ad Factory (a free, open-source ComfyUI tool that turns a product link into a video ad and grades it) and listen to its audio.

Score each criterion from 0 to 10: hook (first 2 seconds stop the scroll), product_clarity, message, pacing, audio, cta, visual_quality (no AI artifacts).
Then give the weighted total out of 100 with weights hook 25, product_clarity 20, message 15, pacing 15, audio 10, cta 10, visual_quality 5.
Finish with the three most important fixes for the next cut, each naming the shot (1-4).

Format:
Scores: hook X/10, product_clarity X/10, message X/10, pacing X/10, audio X/10, cta X/10, visual_quality X/10
Virality score: N/100
Fixes:
1. ...
2. ...
3. ..."""

POST_PROMPT = """Write the TikTok and Instagram Reels caption for a short ad about Open Ad Factory: a free, open-source ComfyUI node pack. Paste any product URL and it makes a vertical video ad with voiceover and captions, then an AI judge scores the ad and the next run improves it. It runs on your own GPU with open-weights models only, no API keys, no credits.
Two short punchy sentences, then the link github.com/kaili-yang/comfyui-open-ad-factory, then five hashtags. Plain text only."""

NOTE = """# Open Ad Factory: self-ad (built-in nodes only)
The ad for Open Ad Factory, made with the Open Ad Factory pipeline, rebuilt with **only built-in ComfyUI nodes** for hosted machines where custom nodes cannot be installed.

1. **Qwen-Image 2.1** generates the product photo from a prompt: a phone running Open Ad Factory. No third-party images.
2. **Qwen-Image 2.1 Edit** makes the first frame of each of the 4 shots. Shots 2 and 4 reuse the creator from shot 1 so she stays the same person.
3. **LTX-2.3** animates each frame with her voice and sound (5 s each, 704x1280).
4. **Draw Text Overlay** burns in captions; **Concatenate Video** joins the shots; **Save Video** writes the 20 s ad.
5. **Gemma 4** watches and listens to the ad and gives a virality score out of 100 with fixes, plus writes the social post caption.

Edit the storyboard directly: prompts on the Shot keyframe and Shot video nodes, captions on the Caption nodes.

All models are the ones from the official templates *Qwen Image 2.1 Text to Image*, *Image Edit (Qwen Image 2.1)*, *LTX-2.3 Image to Video* and *Gemma 4 Text Generation*."""


def build(info):
    ltx = load_template("video_ltx2_3_i2v")
    edit = load_template("image_qwen_image_2_1_image_edit")
    t2i = load_template("image_qwen_image_2_1_t2i")
    gemma = load_template("llm_gemma4_text_gen")
    sub = lambda t: next(n for n in t["nodes"] if n["type"] == t["definitions"]["subgraphs"][0]["id"])

    b = Builder(info)
    b.add({"type": "MarkdownNote", "pos": [-1100, -300], "size": [520, 620], "inputs": [], "outputs": [], "properties": {},
           "widgets_values": [NOTE], "color": "#432", "bgcolor": "#653"})

    hero = b.copy_node(sub(t2i), (-500, -300), title="Product photo (Qwen-Image 2.1, generated)")
    hero["widgets_values"][0] = HERO_PROMPT
    hero["widgets_values"][7:9] = [768, 1344]
    hero["widgets_values"][11] = 920
    hero_preview = b.pack_node("PreviewImage", (-500, 450), {}, size=(300, 480), title="Product photo")
    b.link(hero, 0, hero_preview, "images")

    concat = b.add({"type": "ConcatenateVideo", "pos": [3000, -300], "size": [320, 200],
                    "inputs": [{"name": f"videos.video{i}", "type": "VIDEO", "link": None} for i in range(len(SHOTS))]
                    + [{"name": "codec", "type": "COMBO", "widget": {"name": "codec"}, "link": None},
                       {"name": "complete_audio", "type": "AUDIO", "link": None}],
                    "outputs": [{"name": "VIDEO", "type": "VIDEO", "links": []}],
                    "properties": {"Node name for S&R": "ConcatenateVideo"}, "widgets_values": ["auto"]})

    keyframes = []
    for i, shot in enumerate(SHOTS):
        y = -300 + i * 560
        kf = b.copy_node(sub(edit), (0, y), title=f"Shot {i + 1} keyframe (Qwen-Image 2.1 Edit)")
        kf["widgets_values"][1] = shot["keyframe"]
        kf["widgets_values"][13] = 930 + i
        if shot["refs"] == "hero":
            b.link(hero, 0, kf, "images.image_1")
        else:
            b.link(keyframes[0], 0, kf, "images.image_1")
            b.link(hero, 0, kf, "images.image_2")
        keyframes.append(kf)

        vid = b.copy_node(sub(ltx), (550, y), title=f"Shot {i + 1} video (LTX-2.3)")
        vid["widgets_values"][0] = shot["motion"]
        vid["widgets_values"][1:5] = [True, WIDTH, HEIGHT, SECONDS]
        vid["widgets_values"][6] = 940 + i
        b.link(kf, 0, vid, "input")

        parts = b.pack_node("GetVideoComponents", (1100, y), {}, size=(260, 160))
        b.link(vid, 0, parts, "video")
        cap = b.pack_node("TextOverlay", (1420, y), {"text": shot["caption"], "font_size": 5.5, "position": "top", "align": "center"},
                          size=(320, 260), title=f"Caption {i + 1}")
        b.link(parts, 0, cap, "images")
        clip_video = b.pack_node("CreateVideo", (1800, y), {}, size=(260, 160))
        b.link(cap, 0, clip_video, "images")
        b.link(parts, 2, clip_video, "fps")
        b.link(parts, 1, clip_video, "audio")
        b.link(clip_video, 0, concat, f"videos.video{i}")

    save = b.pack_node("SaveVideo", (3400, -300), {"filename_prefix": "open_ad_factory/self_ad"}, size=(420, 760))
    b.link(concat, 0, save, "video")

    clip = b.copy_node(first(gemma["nodes"], "CLIPLoader"), (3000, 600), title="Load Gemma 4 (judge + caption)")
    final_parts = b.pack_node("GetVideoComponents", (3000, 100), {}, size=(260, 160))
    b.link(concat, 0, final_parts, "video")
    small = b.pack_node("ImageScaleBy", (3000, 340), {"upscale_method": "area", "scale_by": 0.35}, size=(260, 120))
    b.link(final_parts, 0, small, "image")

    judge = b.copy_node(first(gemma["nodes"], "TextGenerate"), (3400, 520), title="Virality judge (Gemma 4)")
    judge["widgets_values"][0] = JUDGE_PROMPT
    judge["widgets_values"][2:4] = ["on", 0.3]
    b.link(clip, 0, judge, "clip")
    b.link(small, 0, judge, "video")
    b.link(final_parts, 1, judge, "audio")
    report = b.pack_node("PreviewAny", (3850, 520), {}, size=(460, 520), title="Virality report")
    b.link(judge, 0, report, "source")

    post = b.copy_node(first(gemma["nodes"], "TextGenerate"), (3400, 1150), title="Social post caption (Gemma 4)")
    post["widgets_values"][0] = POST_PROMPT
    b.link(clip, 0, post, "clip")
    post_preview = b.pack_node("PreviewAny", (3850, 1150), {}, size=(460, 300), title="Social post caption")
    b.link(post, 0, post_preview, "source")

    return {
        "id": "6b1f3f0e-0a3c-4c62-9d1b-3a5e0adfac03",
        "revision": 0,
        "last_node_id": b.next_id - 1,
        "last_link_id": b.next_link - 1,
        "nodes": b.nodes,
        "links": b.links,
        "groups": [],
        "definitions": {"subgraphs": t2i["definitions"]["subgraphs"] + edit["definitions"]["subgraphs"] + ltx["definitions"]["subgraphs"]},
        "config": {},
        "extra": {"ds": {"scale": 0.4, "offset": [1300, 500]}},
        "version": 0.4,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:8188")
    ap.add_argument("--out", default="build/raw_self_ad_core.json")
    args = ap.parse_args()
    with urllib.request.urlopen(args.server + "/object_info") as r:
        info = json.load(r)
    wf = build(info)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(wf, f, indent=2, ensure_ascii=False)
    print(f"wrote {args.out}: {len(wf['nodes'])} nodes, {len(wf['links'])} links")


if __name__ == "__main__":
    main()

"""Build example_workflows/open_ad_factory_self_ad_core.json: the Open Ad Factory self-ad using ONLY built-in ComfyUI nodes.

For hosted environments where custom nodes cannot be installed but the official template models are preinstalled.
The storyboard is written out here instead of by the planner node. The logo and the product photo are generated from
prompts (no third-party imagery), captions use Draw Text Overlay, the logo is composited as a watermark, and
Qwen3-VL-8B grades the finished cut.

Story: the old way (cold, messy, per-video credits) and the new way (one link, warm, clean) on the SAME desk and framing,
so the contrast reads in one glance, with a slow-motion release as the payoff and a logo end card.

    cd tools && python build_core_self_ad.py --server http://127.0.0.1:8188 --out ../build/raw_self_ad_core.json
"""
import argparse
import json
import os
import urllib.request

from build_workflow import Builder, first, load_template

WIDTH, HEIGHT = 704, 1280
CANVAS_W, CANVAS_H = 768, 1344
WATERMARK, WATERMARK_MARGIN, WATERMARK_BOTTOM = 112, 28, 230
GITHUB = "github.com/kaili-yang/comfyui-open-ad-factory"
LLM_FILE = "qwen3vl_8b_int8_convrot.safetensors"  # already installed for Qwen-Image 2.1; loaded as a plain Qwen3-VL-8B for text generation
PE_FILES = ("qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors", "qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors")

LOGO_PROMPT = (
    "Flat vector brand logo on a solid pure black background. Centered icon: a bright lime-yellow rounded square with a bold "
    "black play-button triangle inside it and three small yellow sparkles at its upper right corner. Directly below the icon, "
    "the wordmark \"OPEN AD FACTORY\" in heavy white condensed sans-serif capital letters, spelled exactly. Minimal, high "
    "contrast, crisp edges, professional brand identity, no other text, no mockup, no gradients."
)

PHONE_PROMPT = (
    "Vertical studio product photograph for a tech launch ad. A modern black smartphone stands upright on a glossy lime-yellow "
    "pedestal against a smooth deep violet gradient background, soft rim light and a gentle reflection on the pedestal. "
    "The phone screen shows a sleek dark app interface: an empty dark header area at the top, below it a rounded URL bar, "
    "then a row of four small vertical video thumbnails in purple, gray, blue and yellow, then a huge bright yellow number "
    "\"92\" with \"/100\" under it, and at the bottom a yellow pill button reading \"GENERATE AD\". "
    "Crisp, photorealistic, premium advertising photography, centered composition, generous empty space around the phone."
)

PHONE_LOGO_PROMPT = (
    "Place the logo from <image2> (the yellow play-button icon with the white OPEN AD FACTORY wordmark) centered in the empty "
    "dark header area at the top of the phone screen in <image1>. Keep the phone, the rest of the screen, the pedestal, the "
    "lighting and the background exactly the same."
)

CREATOR = "a friendly woman in her late twenties with shoulder-length curly dark hair, wearing a mustard-yellow hoodie"
VOICE = "a warm, slightly husky female voice"
SAME_SET = "The same woman, the same desk and the exact same camera framing as <image1>."

# refs: images fed to Qwen-Image Edit in order (<image1>, <image2>, ...). image_1 sets the output size.
# judge: frame indices (25 fps) the judge looks at.
SHOTS = [
    {
        "name": "old way",
        "seconds": 5,
        "refs": ["phone"],
        "caption": "THE OLD WAY: DAYS + CREDITS",
        "keyframe": f"Vertical handheld frame of a cramped home desk under harsh cold blue fluorescent light, desaturated colors. {CREATOR} is buried behind the desk: sticky-note storyboards cover the wall behind her, stacks of invoices, a camera on a tripod, and a laptop showing two red error pop-ups reading \"RENDER FAILED\" and \"OUT OF CREDITS\". The phone from <image1> lies face up on the desk with its screen dark. She holds her head in both hands, exhausted. Photorealistic.",
        "motion": f"Another red pop-up appears on the laptop and the phone buzzes on the desk; she groans and drops her forehead onto a pile of sticky notes, which flutter up. Shaky handheld camera. Error beeps and phone vibration. She mutters in {VOICE}: \"Script, shoot, voiceover, edit... and every tool charges per video.\"",
        "judge": (12, 90),
    },
    {
        "name": "new way",
        "seconds": 5,
        "refs": ["shot1", "phone", "logo"],
        "caption": "THE NEW WAY: OPEN AD FACTORY",
        "keyframe": f"{SAME_SET} Same clutter and cold blue light. She now sits up and holds the phone from <image2> toward the camera; its screen shows the logo from <image3> large and glowing, with a product link pasted into the URL bar below it. Photorealistic.",
        "motion": f"She takes a breath, her thumb hovers over the yellow button on the phone, then presses it, and the noise in the room cuts to silence. Static camera. She says in {VOICE}, half doubtful: \"Or... I paste one link into Open Ad Factory.\"",
        "judge": (12, 90),
    },
    {
        "name": "payoff",
        "seconds": 5,
        "refs": ["shot1", "phone", "logo"],
        "caption": "WRITTEN. SHOT. VOICED. DONE.",
        "keyframe": f"{SAME_SET} The instant she presses the button on the phone from <image2>: a burst of warm golden light pours from the screen showing the logo from <image3>, sticky notes and invoices start lifting off the desk, and the cold blue light begins turning warm. Photorealistic, dynamic.",
        "motion": f"In slow motion a gust blows every sticky note and invoice off the desk, the laptop error pop-ups close one by one, and the light shifts from cold blue to warm gold. Papers whoosh and flutter, then a bright chime. She laughs and says in {VOICE}: \"Script, shots, voice, captions. Done.\"",
        "judge": (12, 90),
    },
    {
        "name": "result",
        "seconds": 5,
        "refs": ["shot1", "phone", "logo"],
        "caption": "IT EVEN GRADES ITS OWN AD",
        "keyframe": f"{SAME_SET} The desk is now clean and tidy, lit by warm golden light, nothing left of the clutter. She leans back with a coffee mug and turns the phone from <image2> toward the camera; its screen plays the finished ad with a big yellow \"92/100\". Behind her the laptop shows the logo from <image3> above the words \"FREE ON GITHUB\". Photorealistic.",
        "motion": f"She raises an eyebrow, sips her coffee and taps the score on the phone screen with a grin, and the camera slowly pulls back. Light upbeat whoosh. She says in {VOICE}: \"Open Ad Factory even grades its own ad.\"",
        "judge": (12, 90),
    },
    {
        "name": "logo end card",
        "seconds": 3,
        "refs": None,  # the logo itself, padded to 9:16 on black
        "caption": "FREE ON GITHUB",
        "footer": GITHUB,
        "motion": f"The logo slowly scales up as a bright light sweep crosses the yellow icon and small sparkles pop around it on the black background. Punchy whoosh, then a soft logo sting. {VOICE.capitalize()} says: \"Open Ad Factory. Free on GitHub.\"",
        "judge": (40,),
    },
]


def spoken(shot):
    return shot["motion"].rsplit('"', 2)[-2]


def judge_prompt():
    frames = [f"shot {i + 1} ({s['name']}) at {k / 25:.1f} s" for i, s in enumerate(SHOTS) for k in s["judge"]]
    total = sum(s["seconds"] for s in SHOTS)
    return "\n".join([
        f"You are a strict short-video ad reviewer. These {len(frames)} images are frames from a {total}-second vertical video ad for Open Ad Factory "
        "(a free, open-source ComfyUI tool that turns a product link into a video ad and grades it). In order they are: " + "; ".join(frames) + ".",
        "",
        "Spoken lines and captions:",
        *[f"Shot {i + 1} ({s['name']}): says \"{spoken(s)}\" / caption \"{s['caption']}\"" for i, s in enumerate(SHOTS)],
        "",
        "Score each criterion from 0 to 10: hook (shot 1 stops the scroll), contrast (old way vs new way is instantly clear), payoff (the moment the pain disappears feels satisfying), "
        "brand (logo and name are memorable), cta, visual_quality (no AI artifacts such as warped hands, faces, logo or text).",
        "Then give the weighted total out of 100 with weights hook 20, contrast 20, payoff 20, brand 20, cta 10, visual_quality 10.",
        f"Finish with the three most important fixes for the next cut, each naming the shot (1-{len(SHOTS)}).",
        "",
        "Format:",
        "Scores: hook X/10, contrast X/10, payoff X/10, brand X/10, cta X/10, visual_quality X/10",
        "Virality score: N/100",
        "Fixes:",
        "1. ...",
        "2. ...",
        "3. ...",
    ])


POST_PROMPT = f"""Write the TikTok and Instagram Reels caption for a short ad about Open Ad Factory: a free, open-source ComfyUI node pack. The old way of making a video ad means scripts, shoots, voiceovers, edits and AI tools that charge per video. With Open Ad Factory you paste one product link and open-weights models on your own GPU write, shoot, voice and caption the ad, then an AI judge grades it.
Two short punchy sentences that contrast the old way and the new way and name Open Ad Factory, then the link {GITHUB}, then five hashtags. Plain text only."""

NOTE = f"""# Open Ad Factory: self-ad (built-in nodes only)
The ad for Open Ad Factory, rebuilt with **only built-in ComfyUI nodes** for hosted machines where custom nodes cannot be installed.

**Story:** the old way and the new way on the same desk and framing. Cold blue, cluttered, per-video credits → one link → slow-motion release, the mess blows away → clean, warm desk with the graded ad → logo end card.

1. **Qwen-Image 2.1** generates the logo, then the phone product photo; Qwen-Image 2.1 Edit puts the logo on the phone screen. No third-party images.
2. **Qwen-Image 2.1 Edit** makes the first frame of shots 1-4. Shots 2-4 edit shot 1, so the woman, desk and framing stay identical; the logo is passed in as a reference.
3. **LTX-2.3** animates each frame with her voice and sound (704x1280). Shot 5 animates the logo itself on black.
4. **Draw Text Overlay** burns in captions, **Image Composite Masked** adds the logo watermark to shots 1-4, **Concatenate Video** joins everything, **Save Video** writes the {sum(s['seconds'] for s in SHOTS)} s ad.
5. **Qwen3-VL-8B** looks at key frames with the script, scores hook, contrast, payoff, brand, CTA and visual quality out of 100, and writes the social post caption.

Edit the storyboard on the nodes: Shot keyframe (image prompt), Shot video (motion and spoken line), Caption.

## Models (nothing extra to download)
- Qwen Image 2.1: `qwen_image_2.1_int8_convrot`, `qwen3vl_8b_int8_convrot`, `qwen_image_2.1_vae_bf16`
- LTX-2.3: `ltx-2.3-22b-dev-fp8`, `gemma_3_12B_it_fp4_mixed`, `ltx-2.3-spatial-upscaler-x2-1.1`, `ltx_2.3_22b_distilled_1.1_lora_dynamic_fro09_avg_rank_111_bf16`, `gemma-3-12b-it-abliterated_lora_rank64_bf16`

The Qwen prompt enhancer (`refine_prompt`) is off; its model slot points at `qwen3vl_8b_int8_convrot` so no Qwen3.5 PE file is needed. The judge and caption writer reuse `qwen3vl_8b_int8_convrot`, so they read frames and the script but do not hear the audio."""


def swap_pe_model(template):
    """Point the Qwen prompt-enhancer slot at the already installed Qwen3-VL-8B instead of the separate Qwen3.5 PE files."""
    for sg in template["definitions"]["subgraphs"]:
        for n in sg["nodes"]:
            if n["type"] == "CLIPLoader" and n["widgets_values"][0] in PE_FILES:
                n["widgets_values"][:2] = [LLM_FILE, "stable_diffusion"]
    for n in template["nodes"]:
        n["widgets_values"] = [LLM_FILE if v in PE_FILES else v for v in n.get("widgets_values") or []]
    return template


def build(info):
    ltx = load_template("video_ltx2_3_i2v")
    edit = swap_pe_model(load_template("image_qwen_image_2_1_image_edit"))
    t2i = swap_pe_model(load_template("image_qwen_image_2_1_t2i"))
    gemma = load_template("llm_gemma4_text_gen")
    sub = lambda t: next(n for n in t["nodes"] if n["type"] == t["definitions"]["subgraphs"][0]["id"])

    b = Builder(info)
    b.add({"type": "MarkdownNote", "pos": [-1700, -300], "size": [560, 760], "inputs": [], "outputs": [], "properties": {},
           "widgets_values": [NOTE], "color": "#432", "bgcolor": "#653"})

    def rgb(node, pos, title):
        # Qwen-Image 2.1 decodes RGBA; LTX and the compositing nodes take RGB
        out = b.pack_node("SplitImageWithAlpha", pos, {}, size=(260, 80), title=title)
        b.link(node, 0, out, "image")
        return out

    def t2i_node(prompt, size, seed, pos, title):
        node = b.copy_node(sub(t2i), pos, title=title)
        node["widgets_values"][0] = prompt
        node["widgets_values"][7:9] = list(size)
        node["widgets_values"][11] = seed
        return node

    def edit_node(prompt, seed, pos, title, refs):
        node = b.copy_node(sub(edit), pos, title=title)
        node["widgets_values"][1] = prompt
        node["widgets_values"][13] = seed
        for k, ref in enumerate(refs):
            b.link(ref, 0, node, f"images.image_{k + 1}")
        return node

    logo = rgb(t2i_node(LOGO_PROMPT, (1024, 1024), 910, (-1100, -300), "Logo (Qwen-Image 2.1, generated)"), (-1100, 330), "Logo RGB")
    b.link(logo, 0, b.pack_node("PreviewImage", (-1100, 440), {}, size=(300, 300), title="Logo"), "images")
    phone_raw = rgb(t2i_node(PHONE_PROMPT, (CANVAS_W, CANVAS_H), 920, (-700, -300), "Phone (Qwen-Image 2.1, generated)"), (-700, 330), "Phone RGB")
    phone = rgb(edit_node(PHONE_LOGO_PROMPT, 921, (-300, -300), "Logo onto phone screen (Qwen-Image 2.1 Edit)", [phone_raw, logo]),
                (-300, 330), "Product photo RGB")
    b.link(phone, 0, b.pack_node("PreviewImage", (-300, 440), {}, size=(300, 480), title="Product photo"), "images")

    logo_card = b.pack_node("ResizeAndPadImage", (-1100, 800), {"target_width": CANVAS_W, "target_height": CANVAS_H, "padding_color": "black",
                                                                  "interpolation": "area"}, size=(300, 160), title="Logo end card 9:16")
    b.link(logo, 0, logo_card, "image")
    watermark = b.pack_node("ImageScale", (-1100, 1000), {"upscale_method": "area", "width": WATERMARK, "height": WATERMARK, "crop": "disabled"},
                            size=(300, 160), title="Logo watermark")
    b.link(logo, 0, watermark, "image")

    concat = b.add({"type": "ConcatenateVideo", "pos": [3000, -300], "size": [320, 200],
                    "inputs": [{"name": f"videos.video{i}", "type": "VIDEO", "link": None} for i in range(len(SHOTS))]
                    + [{"name": "codec", "type": "COMBO", "widget": {"name": "codec"}, "link": None},
                       {"name": "complete_audio", "type": "AUDIO", "link": None}],
                    "outputs": [{"name": "VIDEO", "type": "VIDEO", "links": []}],
                    "properties": {"Node name for S&R": "ConcatenateVideo"}, "widgets_values": ["auto"]})
    judge_count = sum(len(s["judge"]) for s in SHOTS)
    frames = b.add({"type": "BatchImagesNode", "pos": [2300, 2700], "size": [260, 300],
                    "inputs": [{"name": f"images.image{k}", "type": "IMAGE", "link": None} for k in range(judge_count)],
                    "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": []}],
                    "properties": {"Node name for S&R": "BatchImagesNode"}, "widgets_values": []})

    sources = {"phone": phone, "logo": logo}
    frame_slot = 0
    for i, shot in enumerate(SHOTS):
        y = -300 + i * 620
        if shot["refs"] is None:
            first_frame = logo_card
        else:
            kf = edit_node(shot["keyframe"], 930 + i, (0, y), f"Shot {i + 1} keyframe: {shot['name']} (Qwen-Image 2.1 Edit)",
                           [sources[r] for r in shot["refs"]])
            first_frame = rgb(kf, (0, y + 500), f"Shot {i + 1} keyframe RGB")
            if i == 0:
                sources["shot1"] = first_frame

        vid = b.copy_node(sub(ltx), (550, y), title=f"Shot {i + 1} video: {shot['name']} (LTX-2.3)")
        vid["widgets_values"][0] = shot["motion"]
        vid["widgets_values"][1:5] = [True, WIDTH, HEIGHT, shot["seconds"]]  # prompt_enhance, width, height, duration
        vid["widgets_values"][6] = 940 + i  # seed
        b.link(first_frame, 0, vid, "input")

        parts = b.pack_node("GetVideoComponents", (1100, y), {}, size=(260, 160))
        b.link(vid, 0, parts, "video")
        frames_out = b.pack_node("TextOverlay", (1420, y), {"text": shot["caption"], "font_size": 5.5, "position": "top", "align": "center"},
                                 size=(320, 260), title=f"Caption {i + 1}")
        b.link(parts, 0, frames_out, "images")
        if shot.get("footer"):
            footer = b.pack_node("TextOverlay", (1420, y + 280), {"text": shot["footer"], "font_size": 2.5, "position": "bottom", "align": "center"},
                                 size=(320, 260), title=f"Footer {i + 1}")
            b.link(frames_out, 0, footer, "images")
            frames_out = footer
        else:
            mark = b.pack_node("ImageCompositeMasked", (1420, y + 280), {"x": WIDTH - WATERMARK - WATERMARK_MARGIN,
                                                                         "y": HEIGHT - WATERMARK - WATERMARK_BOTTOM, "resize_source": False},
                               size=(320, 200), title=f"Logo watermark {i + 1}")
            b.link(frames_out, 0, mark, "destination")
            b.link(watermark, 0, mark, "source")
            frames_out = mark

        clip_video = b.pack_node("CreateVideo", (1800, y), {}, size=(260, 160))
        b.link(frames_out, 0, clip_video, "images")
        b.link(parts, 2, clip_video, "fps")
        b.link(parts, 1, clip_video, "audio")
        b.link(clip_video, 0, concat, f"videos.video{i}")
        for j, index in enumerate(shot["judge"]):
            pick = b.pack_node("ImageFromBatch", (1800 + j * 280, y + 220), {"batch_index": index, "length": 1}, size=(260, 130),
                               title=f"Shot {i + 1} frame @{index}")
            b.link(frames_out, 0, pick, "image")
            b.link(pick, 0, frames, f"images.image{frame_slot}")
            frame_slot += 1

    save = b.pack_node("SaveVideo", (3400, -300), {"filename_prefix": "open_ad_factory/self_ad"}, size=(420, 760))
    b.link(concat, 0, save, "video")

    clip = b.copy_node(first(gemma["nodes"], "CLIPLoader"), (3000, 600), title="Load Qwen3-VL-8B (judge + caption)")
    clip["widgets_values"][:2] = [LLM_FILE, "stable_diffusion"]
    small = b.pack_node("ImageScaleBy", (3000, 340), {"upscale_method": "area", "scale_by": 0.5}, size=(260, 120))
    b.link(frames, 0, small, "image")
    b.link(small, 0, b.pack_node("PreviewImage", (2600, 2700), {}, size=(360, 300), title="Frames the judge sees"), "images")

    judge = b.copy_node(first(gemma["nodes"], "TextGenerate"), (3400, 520), title="Virality judge (Qwen3-VL-8B)")
    judge["widgets_values"][0] = judge_prompt()
    judge["widgets_values"][2:4] = ["on", 0.3]
    b.link(clip, 0, judge, "clip")
    b.link(small, 0, judge, "image")
    b.link(judge, 0, b.pack_node("PreviewAny", (3850, 520), {}, size=(460, 520), title="Virality report"), "source")

    post = b.copy_node(first(gemma["nodes"], "TextGenerate"), (3400, 1150), title="Social post caption (Qwen3-VL-8B)")
    post["widgets_values"][0] = POST_PROMPT
    b.link(clip, 0, post, "clip")
    b.link(post, 0, b.pack_node("PreviewAny", (3850, 1150), {}, size=(460, 300), title="Social post caption"), "source")

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
        "extra": {"ds": {"scale": 0.35, "offset": [1700, 500]}},
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

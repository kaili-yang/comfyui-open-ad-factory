"""Build example_workflows/open_ad_factory.json.

The LTX-2.3 image-to-video and Qwen-Image 2.1 edit stages are the official Comfy
template subgraphs, copied verbatim from the installed comfyui-workflow-templates
package, so the model settings stay the ones Comfy tuned. Node input layouts for
this pack come from a running server's /object_info.

    python tools/build_workflow.py --server http://127.0.0.1:8188 --out build/raw_workflow.json

The raw file is then normalized and validated in a real frontend by tools/validate_workflow.mjs.
"""
import argparse
import copy
import json
import os
import urllib.request

import comfyui_workflow_templates_json

TEMPLATES = os.path.join(os.path.dirname(comfyui_workflow_templates_json.__file__), "templates")
SHOTS = 4
SECONDS = 5
WIDTH, HEIGHT = 704, 1280

NOTE = f"""# Open Ad Factory
Paste a product URL, press **Run**, get a {SHOTS * SECONDS + 2}-second vertical video ad that grades itself.

1. **Product Page to Brief** reads the page (Shopify, schema.org or Open Graph) and puts the product photo on a 9:16 canvas.
2. **Ad Storyboard Planner** (Gemma 4) writes {SHOTS} shots: hook, problem, solution, call to action, with voiceover and captions.
3. Each shot: **Qwen-Image 2.1 Edit** puts the product into the first frame, **LTX-2.3** animates it with voice and sound.
4. **Assemble Ad** joins the shots, burns in captions and adds the end card.
5. **Ad Virality Judge** (Gemma 4 watches and listens) scores the cut out of 100 and saves its fixes.

**Run again** with the same project name: the planner reads the judge's fixes and rewrites the storyboard. Watch the score climb in `output/open_ad_factory/<project>/history.jsonl`.

Open weights only. No partner nodes, no API keys.

## Models
**text_encoders**
- [gemma4_e4b_it_fp8_scaled.safetensors](https://huggingface.co/Comfy-Org/gemma-4/resolve/main/text_encoders/gemma4_e4b_it_fp8_scaled.safetensors)

Qwen-Image 2.1 and LTX-2.3 files are listed inside their subgraphs and in the official templates *Image Edit (Qwen Image 2.1)* and *LTX-2.3 Image to Video*.

Keep `seconds_per_shot` on the planner equal to `duration` on the LTX nodes."""


def load_template(name):
    with open(os.path.join(TEMPLATES, name + ".json"), encoding="utf-8") as f:
        return json.load(f)


def first(nodes, type_):
    return next(n for n in nodes if n["type"] == type_)


class Builder:
    def __init__(self, object_info):
        self.info = object_info
        self.nodes, self.links = [], []
        self.next_id = 1
        self.next_link = 1

    def add(self, node):
        node["id"] = self.next_id
        node.setdefault("flags", {})
        node.setdefault("mode", 0)
        node["order"] = len(self.nodes)
        self.next_id += 1
        self.nodes.append(node)
        return node

    def pack_node(self, type_, pos, widgets, size=(400, 300), title=None):
        info = self.info[type_]
        inputs, values = [], []
        order = info["input_order"]
        for section in ("required", "optional"):
            for name in order.get(section, []):
                spec = info["input"][section][name]
                kind, opts = spec[0], spec[1] if len(spec) > 1 else {}
                kind = "COMBO" if isinstance(kind, list) else kind
                is_widget = kind in ("INT", "FLOAT", "STRING", "BOOLEAN", "COMBO", "COLOR") and not opts.get("forceInput")
                entry = {"name": name, "type": kind, "link": None}
                if is_widget:
                    entry["widget"] = {"name": name}
                    values.append(widgets.get(name, opts.get("default")))
                    if opts.get("control_after_generate"):
                        values.append("fixed")
                inputs.append(entry)
        outputs = [{"name": n, "type": t, "links": []} for n, t in zip(info["output_name"], info["output"])]
        node = {"type": type_, "pos": list(pos), "size": list(size), "inputs": inputs, "outputs": outputs,
                "properties": {"Node name for S&R": type_}, "widgets_values": values}
        if title:
            node["title"] = title
        return self.add(node)

    def copy_node(self, template_node, pos, title=None):
        node = copy.deepcopy(template_node)
        node["pos"] = list(pos)
        for i in node.get("inputs", []):
            i["link"] = None
        for o in node.get("outputs", []):
            o["links"] = []
        if title:
            node["title"] = title
        return self.add(node)

    def link(self, src, out_slot, dst, in_name):
        slot = next(i for i, x in enumerate(dst["inputs"]) if x["name"] == in_name)
        type_ = src["outputs"][out_slot]["type"]
        lid = self.next_link
        self.next_link += 1
        src["outputs"][out_slot]["links"].append(lid)
        dst["inputs"][slot]["link"] = lid
        self.links.append([lid, src["id"], out_slot, dst["id"], slot, type_])


SELF_AD = {
    "url": "https://github.com/kaili-yang/comfyui-open-ad-factory",
    "image": "open_ad_factory_hero.png",
    "project": "open_ad_factory_self_ad",
    "style": "playful",
    "audience": "e-commerce sellers, indie brands and marketers who pay per video on closed AI ad tools",
    "notes": ("The product is Open Ad Factory, a free open-source ComfyUI node pack, not GitHub. "
              "Paste any product URL and it makes a 22-second vertical video ad with voiceover, captions and an end card. "
              "Then an AI judge watches the ad, scores it out of 100, and the next run fixes what the judge found, so the ad improves itself. "
              "Runs on your own GPU with open-weights models only (Gemma 4, Qwen-Image 2.1, LTX-2.3): no API keys, no credits, no subscription. "
              "The product photo shows the app on a phone. Call to action: get it free on GitHub."),
}


def build(object_info, url=None, image=None, notes="", project="my_ad", style="ugc", audience="", workflow_id="6b1f3f0e-0a3c-4c62-9d1b-3a5e0adfac01"):
    ltx = load_template("video_ltx2_3_i2v")
    qwen = load_template("image_qwen_image_2_1_image_edit")
    gemma = load_template("llm_gemma4_text_gen")
    ltx_node = next(n for n in ltx["nodes"] if n["type"] == ltx["definitions"]["subgraphs"][0]["id"])
    qwen_node = next(n for n in qwen["nodes"] if n["type"] == qwen["definitions"]["subgraphs"][0]["id"])

    b = Builder(object_info)
    note = b.add({"type": "MarkdownNote", "pos": [-900, -200], "size": [560, 820], "inputs": [], "outputs": [], "properties": {},
                  "widgets_values": [NOTE], "color": "#432", "bgcolor": "#653"})
    clip = b.copy_node(first(gemma["nodes"], "CLIPLoader"), (-300, 380), title="Load Gemma 4 (planner + judge)")
    page_widgets = {"width": 768, "height": 1344, "extra_notes": notes}
    if url:
        page_widgets["url"] = url
    page = b.pack_node("OpenAdProductPage", (-300, -200), page_widgets, size=(420, 330))
    if image:
        photo = b.copy_node(first(ltx["nodes"], "LoadImage"), (-800, 700), title="Product photo")
        photo["widgets_values"][0] = image
        b.link(photo, 0, page, "image")
    planner = b.pack_node("OpenAdPlanner", (200, -200), {"num_shots": str(SHOTS), "seconds_per_shot": SECONDS, "project": project,
                                                         "style": style, "audience": audience}, size=(400, 420))
    summary = b.pack_node("PreviewAny", (200, 300), {}, size=(400, 420), title="Storyboard")
    post = b.pack_node("PreviewAny", (200, 760), {}, size=(400, 200), title="Social post caption")
    b.link(page, 0, planner, "brief")
    b.link(page, 1, planner, "product_image")
    b.link(clip, 0, planner, "clip")
    b.link(planner, 1, summary, "source")
    b.link(planner, 2, post, "source")

    assemble = b.pack_node("OpenAdAssemble", (2400, -200), {}, size=(400, 400))
    b.link(planner, 0, assemble, "storyboard")
    b.link(page, 1, assemble, "product_image")

    for i in range(SHOTS):
        y = -200 + i * 520
        shot = b.pack_node("OpenAdShot", (700, y), {"shot": i + 1}, size=(320, 160), title=f"Shot {i + 1}")
        b.link(planner, 0, shot, "storyboard")

        kf = b.copy_node(qwen_node, (1100, y), title=f"Shot {i + 1} keyframe (Qwen-Image 2.1 Edit)")
        kf["widgets_values"][13] = 1000 + i  # seed
        b.link(shot, 0, kf, "prompt")
        b.link(page, 2, kf, "images.image_1")

        vid = b.copy_node(ltx_node, (1650, y), title=f"Shot {i + 1} video (LTX-2.3)")
        vid["widgets_values"][1:5] = [True, WIDTH, HEIGHT, SECONDS]  # prompt_enhance, width, height, duration
        vid["widgets_values"][6] = 2000 + i  # seed
        b.link(kf, 0, vid, "input")
        b.link(shot, 1, vid, "value")
        b.link(vid, 0, assemble, f"video_{i + 1}")

    save = b.pack_node("SaveVideo", (2900, -200), {"filename_prefix": "open_ad_factory/ad"}, size=(420, 760))
    b.link(assemble, 0, save, "video")
    judge = b.pack_node("OpenAdViralityJudge", (2400, 300), {"project": project}, size=(400, 300))
    b.link(clip, 0, judge, "clip")
    b.link(assemble, 0, judge, "video")
    b.link(planner, 0, judge, "storyboard")
    report = b.pack_node("PreviewAny", (2400, 680), {}, size=(460, 520), title="Virality report")
    b.link(judge, 1, report, "source")

    return {
        "id": workflow_id,
        "revision": 0,
        "last_node_id": b.next_id - 1,
        "last_link_id": b.next_link - 1,
        "nodes": b.nodes,
        "links": b.links,
        "groups": [],
        "definitions": {"subgraphs": qwen["definitions"]["subgraphs"] + ltx["definitions"]["subgraphs"]},
        "config": {},
        "extra": {"ds": {"scale": 0.45, "offset": [1000, 400]}},
        "version": 0.4,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:8188")
    ap.add_argument("--out", default="build/raw_workflow.json")
    ap.add_argument("--self-ad", action="store_true", help="Build the workflow where Open Ad Factory advertises itself.")
    args = ap.parse_args()
    with urllib.request.urlopen(args.server + "/object_info") as r:
        info = json.load(r)
    wf = build(info, **SELF_AD, workflow_id="6b1f3f0e-0a3c-4c62-9d1b-3a5e0adfac02") if args.self_ad else build(info)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(wf, f, indent=2, ensure_ascii=False)
    print(f"wrote {args.out}: {len(wf['nodes'])} nodes, {len(wf['links'])} links")


if __name__ == "__main__":
    main()

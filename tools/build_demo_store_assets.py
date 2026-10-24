"""Build example_workflows/demo_store_product_shots_core.json: the product photos for the fictional VEYRIN demo store.

Built-in nodes only (Qwen-Image 2.1 text-to-image), so it runs on hosted ComfyUI without custom nodes. Save the three
outputs as site/demo-store/veyrin-glide-legging/images/glide-legging-{front,lifestyle,detail}.jpg.

    cd tools && python build_demo_store_assets.py --server http://127.0.0.1:8188 --out ../build/raw_demo_assets.json
"""
import argparse
import json
import os
import urllib.request

from build_workflow import Builder, load_template, swap_pe_model

PRODUCT = ("a pair of high-rise women's yoga leggings in a deep midnight plum color, smooth matte buttery-soft fabric, "
           "a wide high waistband with a small hidden pocket, ankle length, no logos, no text")

SHOTS = [
    ("front", (1024, 1024), "Ecommerce studio packshot of " + PRODUCT + ", laid flat and perfectly symmetrical on a pure white seamless background, "
     "soft even studio lighting, crisp fabric texture, centered, photorealistic product photography."),
    ("lifestyle", (896, 1120), "Lifestyle photo of a woman in her late twenties with dark hair in a bun doing a low lunge yoga pose in a bright minimal "
     "studio with pale wood floor and morning window light, wearing " + PRODUCT + " and a cream sports bra, full body, photorealistic, editorial."),
    ("detail", (896, 1120), "Macro close-up of the waistband of " + PRODUCT + ", showing the soft brushed fabric, flat seams and the small hidden "
     "pocket at the back of the waistband, shallow depth of field, soft studio light, photorealistic."),
]

NOTE = """# VEYRIN demo store: product photos
Generates the three product photos for the fictional VEYRIN demo store with **Qwen-Image 2.1** (built-in nodes only).

Save the outputs as `site/demo-store/veyrin-glide-legging/images/glide-legging-front.jpg`, `-lifestyle.jpg` and `-detail.jpg`.
VEYRIN is a made-up brand, so the demo ads contain no third-party logos, products or likenesses."""


def build(info):
    t2i = swap_pe_model(load_template("image_qwen_image_2_1_t2i"))
    sub = next(n for n in t2i["nodes"] if n["type"] == t2i["definitions"]["subgraphs"][0]["id"])
    b = Builder(info)
    b.add({"type": "MarkdownNote", "pos": [-600, 0], "size": [480, 300], "inputs": [], "outputs": [], "properties": {},
           "widgets_values": [NOTE], "color": "#432", "bgcolor": "#653"})
    for i, (name, size, prompt) in enumerate(SHOTS):
        node = b.copy_node(sub, (0, i * 560), title=f"VEYRIN {name}")
        node["widgets_values"][0] = prompt
        node["widgets_values"][7:9] = list(size)
        node["widgets_values"][11] = 7100 + i
        rgb = b.pack_node("SplitImageWithAlpha", (480, i * 560), {}, size=(260, 80))
        b.link(node, 0, rgb, "image")
        save = b.pack_node("SaveImage", (780, i * 560), {"filename_prefix": f"veyrin/glide-legging-{name}"}, size=(320, 400))
        b.link(rgb, 0, save, "images")
    return {
        "id": "6b1f3f0e-0a3c-4c62-9d1b-3a5e0adfac04", "revision": 0,
        "last_node_id": b.next_id - 1, "last_link_id": b.next_link - 1,
        "nodes": b.nodes, "links": b.links, "groups": [],
        "definitions": {"subgraphs": t2i["definitions"]["subgraphs"]},
        "config": {}, "extra": {"ds": {"scale": 0.6, "offset": [700, 100]}}, "version": 0.4,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:8188")
    ap.add_argument("--out", default="build/raw_demo_assets.json")
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

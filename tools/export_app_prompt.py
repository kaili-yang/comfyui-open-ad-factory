"""Turn the validated example workflow into the API prompt the web app submits.

    python tools/export_app_prompt.py build/raw_workflow.api.json example_workflows/open_ad_factory.json web/app/prompt.json

The API prompt comes from validate_workflow.mjs (real frontend conversion, subgraphs flattened to "parent:child" ids).
Each top-level node id also gets a stage, so the app can show localized progress and route outputs, and every model
file the prompt loads is listed with its models folder, so the app can check readiness before a run.
"""
import json
import re
import sys

TYPE_STAGES = {
    "OpenAdProductPage": "page",
    "OpenAdPlanner": "plan",
    "OpenAdAssemble": "assemble",
    "SaveVideo": "save",
    "OpenAdViralityJudge": "judge",
    "CLIPLoader": "load",
}
TITLE_OUTPUTS = {"Storyboard": "storyboard", "Social post caption": "post", "Virality report": "report"}
# (class_type, input) -> models folder, for every loader the templates use
MODEL_FOLDERS = {
    ("CLIPLoader", "clip_name"): "text_encoders",
    ("UNETLoader", "unet_name"): "diffusion_models",
    ("VAELoader", "vae_name"): "vae",
    ("CheckpointLoaderSimple", "ckpt_name"): "checkpoints",
    ("LTXAVTextEncoderLoader", "text_encoder"): "text_encoders",
    ("LTXAVTextEncoderLoader", "ckpt_name"): "checkpoints",
    ("LTXVAudioVAELoader", "ckpt_name"): "checkpoints",
    ("LoraLoader", "lora_name"): "loras",
    ("LoraLoaderModelOnly", "lora_name"): "loras",
    ("LatentUpscaleModelLoader", "model_name"): "latent_upscale_models",
}


def stage_of(node):
    title = node.get("title") or ""
    if m := re.match(r"Shot (\d+) preview", title):
        return {"stage": "output", "output": "keyframe", "shot": int(m.group(1))}
    if m := re.match(r"Shot (\d+) (keyframe|video)", title):
        return {"stage": m.group(2), "shot": int(m.group(1))}
    if title in TITLE_OUTPUTS:
        return {"stage": "output", "output": TITLE_OUTPUTS[title]}
    if node["type"] in TYPE_STAGES:
        return {"stage": TYPE_STAGES[node["type"]]}
    return None


def models_of(prompt):
    found = {}
    for node in prompt.values():
        for name, value in node["inputs"].items():
            folder = MODEL_FOLDERS.get((node["class_type"], name))
            if folder and isinstance(value, str):
                found[(folder, value)] = True
            elif isinstance(value, str) and value.endswith((".safetensors", ".pt", ".pth", ".gguf")):
                raise ValueError(f"model input {node['class_type']}.{name} has no folder mapping")
    return [{"folder": f, "file": v} for f, v in sorted(found)]


def main(api_path, workflow_path, out_path):
    with open(api_path, encoding="utf-8") as f:
        prompt = json.load(f)
    with open(workflow_path, encoding="utf-8") as f:
        workflow = json.load(f)
    stages = {str(n["id"]): s for n in workflow["nodes"] if (s := stage_of(n))}
    missing = {"page", "plan", "assemble", "judge", "save"} - {s["stage"] for s in stages.values()}
    if missing:
        raise ValueError(f"workflow is missing stages {sorted(missing)}")
    models = models_of(prompt)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"prompt": prompt, "stages": stages, "models": models}, f, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {out_path}: {len(prompt)} API nodes, {len(stages)} staged nodes, {len(models)} model files")


if __name__ == "__main__":
    main(*sys.argv[1:4])

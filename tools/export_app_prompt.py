"""Turn the validated example workflow into the API prompt the web app submits.

    python tools/export_app_prompt.py build/raw_workflow.api.json example_workflows/open_ad_factory.json web/app/prompt.json

The API prompt comes from validate_workflow.mjs (real frontend conversion, subgraphs flattened to "parent:child" ids).
Each top-level node id also gets a stage, so the app can show localized progress and route outputs.
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


def stage_of(node):
    title = node.get("title") or ""
    m = re.match(r"Shot (\d+) (keyframe|video)", title)
    if m:
        return {"stage": m.group(2), "shot": int(m.group(1))}
    if title in TITLE_OUTPUTS:
        return {"stage": "output", "output": TITLE_OUTPUTS[title]}
    if node["type"] in TYPE_STAGES:
        return {"stage": TYPE_STAGES[node["type"]]}
    return None


def main(api_path, workflow_path, out_path):
    with open(api_path, encoding="utf-8") as f:
        prompt = json.load(f)
    with open(workflow_path, encoding="utf-8") as f:
        workflow = json.load(f)
    stages = {str(n["id"]): s for n in workflow["nodes"] if (s := stage_of(n))}
    missing = {"page", "plan", "assemble", "judge", "save"} - {s["stage"] for s in stages.values()}
    if missing:
        raise ValueError(f"workflow is missing stages {sorted(missing)}")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"prompt": prompt, "stages": stages}, f, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {out_path}: {len(prompt)} API nodes, {len(stages)} staged nodes")


if __name__ == "__main__":
    main(*sys.argv[1:4])

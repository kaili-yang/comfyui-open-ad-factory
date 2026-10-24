# Open Ad Factory: agent notes

- Tests: `python -m pytest tests` with the ComfyUI venv (`../ComfyUI/.venv/bin/python`). Node tests need ComfyUI at `../ComfyUI` or `COMFYUI_PATH`; they run real node classes with a fake LLM.
- Example workflow is generated, never hand-edited:
  1. Start ComfyUI with this repo in `custom_nodes`.
  2. `python tools/build_workflow.py --server http://127.0.0.1:8188` (copies the official LTX-2.3 I2V and Qwen-Image 2.1 Edit template subgraphs from the installed `comfyui_workflow_templates_json`).
  3. `PLAYWRIGHT_DIR=../ComfyUI_frontend node tools/validate_workflow.mjs build/raw_workflow.json example_workflows/open_ad_factory.json` (headless frontend → API prompt → server validation; only missing-model errors are allowed).
- Self-ad workflow: `python tools/build_workflow.py --self-ad --out build/raw_self_ad.json`, then validate into `example_workflows/open_ad_factory_self_ad.json`. Needs `assets/open_ad_factory_hero.png` copied into `ComfyUI/input/` for validation (regenerate with `tools/make_hero.py`).
- Built-in-only self-ad: `cd tools && python build_core_self_ad.py --out ../build/raw_self_ad_core.json`, then validate into `example_workflows/open_ad_factory_self_ad_core.json`. The validator's core mode fails on any class whose `python_module` starts with `custom_nodes`.
- Widget index assumptions in `build_workflow.py`: Qwen subgraph seed = 13; LTX subgraph prompt_enhance/width/height/duration = 1..4, seed = 6. Recheck when the templates package updates.
- Small LLMs emit sloppy JSON (padded keys, trailing commas, fences); `storyboard.extract_json` normalizes these. Keep real-model outputs as regression tests.
- `docs/winning-plans.zh.md` is local-only (listed in `.git/info/exclude`); do not commit it.

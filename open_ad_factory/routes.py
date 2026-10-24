"""The Open Ad Factory web app: served at /open_ad_factory/ by the ComfyUI server, local only."""
import json
import os
import re

from aiohttp import web

import folder_paths
from server import PromptServer

APP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "app")
routes = PromptServer.instance.routes


def project_path(name):
    return os.path.join(folder_paths.get_output_directory(), "open_ad_factory", re.sub(r"[^A-Za-z0-9_\-]+", "_", name.strip()) or "ad")


def read_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@routes.get("/open_ad_factory")
async def app_redirect(request):
    raise web.HTTPFound("/open_ad_factory/")


@routes.get("/open_ad_factory/")
async def app_index(request):
    return web.FileResponse(os.path.join(APP_DIR, "index.html"))


@routes.get("/open_ad_factory/api/project/{name}")
async def project(request):
    folder = project_path(request.match_info["name"])
    history = []
    if os.path.exists(os.path.join(folder, "history.jsonl")):
        with open(os.path.join(folder, "history.jsonl"), encoding="utf-8") as f:
            history = [json.loads(line) for line in f if line.strip()]
    return web.json_response({
        "history": history,
        "review": read_json(os.path.join(folder, "review.json"), None),
        "storyboard": read_json(os.path.join(folder, "storyboard.json"), None),
    })


routes.static("/open_ad_factory/static", APP_DIR)

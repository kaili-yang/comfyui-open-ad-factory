"""The Open Ad Factory web app: served at /open_ad_factory/ by the ComfyUI server."""
import asyncio
import glob
import json
import os
import re

from aiohttp import web

import folder_paths
from server import PromptServer

from . import fetch

APP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "app")
VIDEO_EXTS = (".mp4", ".webm", ".mov", ".mkv")
routes = PromptServer.instance.routes


def safe_name(name):
    return re.sub(r"[^A-Za-z0-9_\-]+", "_", name.strip()) or "ad"


def ads_root():
    return os.path.join(folder_paths.get_output_directory(), "open_ad_factory")


def read_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def latest_video(name):
    """Newest file written by SaveVideo with filename_prefix open_ad_factory/<name>."""
    files = [f for f in glob.glob(os.path.join(ads_root(), f"{glob.escape(name)}_*")) if f.lower().endswith(VIDEO_EXTS)]
    if not files:
        return None
    newest = max(files, key=os.path.getmtime)
    return {"filename": os.path.basename(newest), "subfolder": "open_ad_factory", "type": "output", "mtime": os.path.getmtime(newest)}


def project_summary(name):
    folder = os.path.join(ads_root(), name)
    history = []
    if os.path.exists(os.path.join(folder, "history.jsonl")):
        with open(os.path.join(folder, "history.jsonl"), encoding="utf-8") as f:
            history = [json.loads(line) for line in f if line.strip()]
    storyboard = read_json(os.path.join(folder, "storyboard.json"), None)
    review = read_json(os.path.join(folder, "review.json"), None)
    video = latest_video(name)
    stamps = [os.path.getmtime(os.path.join(folder, f)) for f in os.listdir(folder)] if os.path.isdir(folder) else []
    if video:
        stamps.append(video["mtime"])
    return {"name": name, "history": history, "storyboard": storyboard, "review": review, "video": video, "updated": max(stamps, default=0)}


@routes.get("/open_ad_factory")
async def app_redirect(request):
    raise web.HTTPFound("/open_ad_factory/")


@routes.get("/open_ad_factory/")
async def app_index(request):
    return web.FileResponse(os.path.join(APP_DIR, "index.html"))


@routes.get("/open_ad_factory/api/product")
async def product(request):
    """Preview what the planner will read from a product page, before spending GPU time."""
    url = request.query.get("url", "").strip()
    try:
        info = await asyncio.to_thread(fetch.fetch_product, url)
    except (ValueError, OSError) as e:
        return web.json_response({"error": str(e)}, status=422)
    return web.json_response(info)


@routes.get("/open_ad_factory/api/projects")
async def projects(request):
    root = ads_root()
    names = [n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n))] if os.path.isdir(root) else []
    items = [project_summary(n) for n in names]
    items.sort(key=lambda p: p["updated"], reverse=True)
    return web.json_response(items)


@routes.get("/open_ad_factory/api/project/{name}")
async def project(request):
    return web.json_response(project_summary(safe_name(request.match_info["name"])))


routes.static("/open_ad_factory/static", APP_DIR)

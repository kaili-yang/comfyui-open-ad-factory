import io as _io
import json
import logging
import os
import re
from fractions import Fraction

import numpy as np
import torch
from PIL import Image
from typing_extensions import override

import folder_paths
from comfy_api.latest import ComfyExtension, InputImpl, Types, io
from comfy_extras.nodes_textgen import TextGenerate

from . import assemble, fetch, judge, storyboard as sb

Storyboard = io.Custom("OPEN_AD_STORYBOARD")
CATEGORY = "Open Ad Factory"


def _project_dir(project):
    name = re.sub(r"[^A-Za-z0-9_\-]+", "_", project.strip()) or "ad"
    path = os.path.join(folder_paths.get_output_directory(), "open_ad_factory", name)
    os.makedirs(path, exist_ok=True)
    return path


def _generate(clip, prompt, system_prompt, seed, max_length, temperature, image=None, video=None, audio=None):
    sampling = {"sampling_mode": "on", "temperature": temperature, "top_k": 64, "top_p": 0.95, "min_p": 0.05, "repetition_penalty": 1.05, "seed": seed}
    out = TextGenerate.execute(clip=clip, prompt=prompt, max_length=max_length, sampling_mode=sampling, image=image, video=video, audio=audio,
                               thinking=False, system_prompt=system_prompt)
    return out.result[0]


def _load_image(url):
    body, _ = fetch.http_get(url, accept="image/avif,image/webp,image/png,image/jpeg,*/*")
    img = Image.open(_io.BytesIO(body))
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        white = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(white, img)
    img = img.convert("RGB")
    return torch.from_numpy(np.asarray(img, dtype=np.float32) / 255.0).unsqueeze(0)


class OpenAdProductPage(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="OpenAdProductPage",
            display_name="Product Page to Brief",
            category=CATEGORY,
            description="Reads a product URL (Shopify, schema.org Product or Open Graph pages) and returns a product brief, the product photo, and a vertical canvas for the keyframe model.",
            inputs=[
                io.String.Input("url", default="https://www.allbirds.com/products/mens-tree-runners", tooltip="Product page URL. Leave empty to use only the manual fields and image."),
                io.Int.Input("image_index", default=0, min=0, max=20, tooltip="Which product image on the page to use."),
                io.Int.Input("width", default=768, min=256, max=2048, step=32, tooltip="Canvas width for the keyframe model."),
                io.Int.Input("height", default=1344, min=256, max=2048, step=32, tooltip="Canvas height for the keyframe model."),
                io.Combo.Input("background", options=["auto", "blur", "white", "black"], default="auto", tooltip="auto: white for studio packshots, blurred photo otherwise."),
                io.String.Input("extra_notes", multiline=True, default="", optional=True, tooltip="Anything the page does not say: offer, key benefit, tone. Added to the brief."),
                io.Image.Input("image", optional=True, tooltip="Use this product photo instead of the one on the page."),
            ],
            outputs=[
                io.String.Output(display_name="brief"),
                io.Image.Output(display_name="product_image"),
                io.Image.Output(display_name="canvas"),
            ],
        )

    @classmethod
    def execute(cls, url, image_index, width, height, background, extra_notes="", image=None) -> io.NodeOutput:
        info = fetch.fetch_product(url.strip()) if url.strip() else {"name": "", "images": []}
        if image is None:
            if not info["images"]:
                raise ValueError("No product image found on the page. Connect an image to the 'image' input.")
            image = _load_image(info["images"][min(image_index, len(info["images"]) - 1)])
        brief = fetch.format_product_brief(info) if info["name"] else ""
        if extra_notes.strip():
            brief = f"{brief}\nNotes: {extra_notes.strip()}".strip()
        if not brief:
            raise ValueError("Empty brief: give a product URL or describe the product in extra_notes.")
        canvas = assemble.product_canvas(image, width, height, background=background)
        return io.NodeOutput(brief, image[:1, ..., :3], canvas)


class OpenAdPlanner(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="OpenAdPlanner",
            display_name="Ad Storyboard Planner",
            category=CATEGORY,
            description="An open-weights LLM (Gemma 4 recommended) writes a shot-by-shot ad storyboard: keyframes, motion, voiceover, captions and the end card. Reads the judge's notes from the last run of the same project.",
            inputs=[
                io.Clip.Input("clip", tooltip="A text-generation model loaded with Load CLIP, e.g. gemma4_e4b_it."),
                io.String.Input("brief", force_input=True),
                io.Image.Input("product_image", optional=True, tooltip="Lets the LLM see the product."),
                io.Combo.Input("num_shots", options=["3", "4", "5"], default="4"),
                io.Int.Input("seconds_per_shot", default=5, min=2, max=10, tooltip="Must match the duration set on the video model."),
                io.Combo.Input("style", options=list(sb.STYLES), default="ugc"),
                io.String.Input("audience", default="", tooltip="Leave empty to let the LLM infer it."),
                io.String.Input("language", default="English"),
                io.String.Input("project", default="my_ad", tooltip="Runs with the same project name share judge feedback and saved files."),
                io.Boolean.Input("use_judge_feedback", default=True, tooltip="Rewrite the storyboard using the fixes from the last virality review of this project."),
                io.Int.Input("seed", default=0, min=0, max=0xffffffffffffffff, control_after_generate=True),
                io.Int.Input("max_length", default=3072, min=512, max=16384, advanced=True),
            ],
            outputs=[
                Storyboard.Output(display_name="storyboard"),
                io.String.Output(display_name="summary"),
                io.String.Output(display_name="post_caption"),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, project, use_judge_feedback, **kwargs):
        if not use_judge_feedback:
            return ""
        path = os.path.join(_project_dir(project), "feedback.md")
        return os.path.getmtime(path) if os.path.exists(path) else ""

    @classmethod
    def execute(cls, clip, brief, num_shots, seconds_per_shot, style, audience, language, project, use_judge_feedback, seed, max_length, product_image=None) -> io.NodeOutput:
        n = int(num_shots)
        folder = _project_dir(project)
        notes = ""
        feedback_path = os.path.join(folder, "feedback.md")
        if use_judge_feedback and os.path.exists(feedback_path):
            with open(feedback_path, encoding="utf-8") as f:
                notes = f.read()

        prompt = sb.build_user_prompt(brief, n, seconds_per_shot, style, audience, language, notes)
        text = _generate(clip, prompt, sb.SYSTEM_PROMPT, seed, max_length, 0.8, image=product_image)
        try:
            board = sb.parse_storyboard(text, n)
        except (ValueError, KeyError) as e:
            text = _generate(clip, sb.REPAIR_PROMPT.format(error=e, n=n, previous=text), sb.SYSTEM_PROMPT, seed, max_length, 0.2)
            try:
                board = sb.parse_storyboard(text, n)
            except (ValueError, KeyError) as e2:
                raise ValueError(f"The LLM did not return a valid storyboard ({e2}). Try another seed or a larger model.\n\n{text[:2000]}") from e2

        board["brief"] = brief
        board["seconds_per_shot"] = seconds_per_shot
        board["project"] = project
        with open(os.path.join(folder, "storyboard.json"), "w", encoding="utf-8") as f:
            json.dump(board, f, ensure_ascii=False, indent=2)
        post = f"{board.get('post_caption', '')}\n{' '.join(board['hashtags'])}".strip()
        return io.NodeOutput(board, sb.summary(board), post)


class OpenAdShot(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="OpenAdShot",
            display_name="Ad Shot",
            category=CATEGORY,
            description="Picks one shot from the storyboard and returns the prompts for the keyframe (image edit) and video models.",
            inputs=[
                Storyboard.Input("storyboard"),
                io.Int.Input("shot", default=1, min=1, max=5),
            ],
            outputs=[
                io.String.Output(display_name="keyframe_prompt"),
                io.String.Output(display_name="video_prompt"),
                io.String.Output(display_name="caption"),
            ],
        )

    @classmethod
    def execute(cls, storyboard, shot) -> io.NodeOutput:
        count = len(storyboard["shots"])
        if shot > count:
            raise ValueError(f"The storyboard has {count} shots but shot {shot} was requested. Set num_shots on the planner to at least {shot}, or bypass this branch.")
        i = shot - 1
        return io.NodeOutput(sb.keyframe_prompt(storyboard, i), sb.video_prompt(storyboard, i), storyboard["shots"][i]["caption"])


class OpenAdAssemble(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="OpenAdAssemble",
            display_name="Assemble Ad",
            category=CATEGORY,
            description="Joins the shot clips in order, burns in the captions and adds an end card with the headline and call to action.",
            inputs=[
                Storyboard.Input("storyboard"),
                io.Image.Input("product_image"),
                io.Video.Input("video_1"),
                io.Video.Input("video_2", optional=True),
                io.Video.Input("video_3", optional=True),
                io.Video.Input("video_4", optional=True),
                io.Video.Input("video_5", optional=True),
                io.Boolean.Input("captions", default=True),
                io.Float.Input("caption_position", default=0.72, min=0.05, max=0.95, step=0.01, tooltip="Vertical center of captions, 0 = top. Keep clear of the app UI at the bottom."),
                io.Float.Input("end_card_seconds", default=2.0, min=0.0, max=6.0, step=0.5),
                io.String.Input("font_path", default="", advanced=True, tooltip="Optional .ttf/.otf file. Leave empty to pick a font for the caption's script automatically (Latin, Chinese, Japanese, Korean, Hindi)."),
            ],
            outputs=[io.Video.Output(display_name="video")],
        )

    @classmethod
    def execute(cls, storyboard, product_image, video_1, captions, caption_position, end_card_seconds, font_path, video_2=None, video_3=None, video_4=None, video_5=None) -> io.NodeOutput:
        videos = [v for v in (video_1, video_2, video_3, video_4, video_5) if v is not None]
        if captions and not assemble.can_render(storyboard["shots"][0]["caption"]):
            logging.warning("Open Ad Factory: this Pillow build has no libraqm, so Devanagari captions would render garbled; captions are skipped.")
            captions = False
        segments, frame_rate = [], None
        for i, video in enumerate(videos):
            c = video.get_components()
            frame_rate = frame_rate or Fraction(c.frame_rate)
            frames = c.images[..., :3]
            if captions and i < len(storyboard["shots"]):
                h, w = frames.shape[1:3]
                frames = assemble.composite(frames, assemble.text_layer(w, h, storyboard["shots"][i]["caption"].upper(), caption_position, font_path=font_path))
            segments.append((frames, c.audio))

        fps = float(frame_rate)
        if end_card_seconds > 0:
            h, w = segments[0][0].shape[1:3]
            frames = max(1, round(end_card_seconds * fps))
            segments.append((assemble.end_card(product_image.to(segments[0][0]), w, h, frames, storyboard["headline"], storyboard["cta"], font_path), None))

        images, audio = assemble.concat(segments, fps)
        return io.NodeOutput(InputImpl.VideoFromComponents(Types.VideoComponents(images=images, audio=audio, frame_rate=frame_rate)))


class OpenAdViralityJudge(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="OpenAdViralityJudge",
            display_name="Ad Virality Judge",
            category=CATEGORY,
            description="A multimodal open-weights LLM (Gemma 4 sees video and hears audio) grades the cut on a 7-part engagement rubric, returns a 0-100 score, and saves its fixes so the next planner run improves the ad.",
            inputs=[
                io.Clip.Input("clip", tooltip="A multimodal text-generation model, e.g. gemma4_e4b_it (video + audio)."),
                io.Video.Input("video"),
                Storyboard.Input("storyboard", optional=True, tooltip="The brief the ad is graded against."),
                io.String.Input("project", default="my_ad", tooltip="Fixes are saved here for the planner's next run."),
                io.Boolean.Input("save_feedback", default=True),
                io.Int.Input("frame_size", default=448, min=224, max=1024, step=32, tooltip="Longest side of the frames shown to the judge.", advanced=True),
                io.Int.Input("seed", default=0, min=0, max=0xffffffffffffffff),
                io.Int.Input("max_length", default=2048, min=256, max=8192, advanced=True),
                io.String.Input("language", default="English", tooltip="Language for the strengths, fixes and verdict."),
            ],
            outputs=[
                io.Float.Output(display_name="score"),
                io.String.Output(display_name="report"),
                io.String.Output(display_name="feedback"),
            ],
        )

    @classmethod
    def execute(cls, clip, video, project, save_feedback, frame_size, seed, max_length, language="English", storyboard=None) -> io.NodeOutput:
        c = video.get_components()
        frames = c.images[..., :3]
        fps = float(c.frame_rate)
        # TextGenerate assumes 24 fps video frames; retime so its 1 fps sampling sees one frame per second
        idx = (torch.arange(round(frames.shape[0] * 24 / fps)) * fps / 24).long().clamp(max=frames.shape[0] - 1)
        frames = frames[idx]
        h, w = frames.shape[1:3]
        scale = frame_size / max(h, w)
        if scale < 1:
            frames = assemble._resize(frames, round(w * scale), round(h * scale))

        if storyboard is not None:
            brief = f"{storyboard.get('brief', '')}\nAngle: {storyboard.get('angle', '')}\nAudience: {storyboard.get('audience', '')}\nCall to action: {storyboard['cta']}"
            n = len(storyboard["shots"])
        else:
            brief, n = "Not provided. Judge the ad on its own.", 5

        prompt = judge.build_user_prompt(brief, n, language)
        text = _generate(clip, prompt, judge.SYSTEM_PROMPT, seed, max_length, 0.3, video=frames, audio=c.audio)
        try:
            review = judge.parse_review(text)
        except (ValueError, KeyError, TypeError) as e:
            raise ValueError(f"The judge did not return a valid review ({e}). Try another seed.\n\n{text[:2000]}") from e

        report = judge.report(review)
        notes = judge.feedback(review)
        if save_feedback:
            folder = _project_dir(project)
            with open(os.path.join(folder, "feedback.md"), "w", encoding="utf-8") as f:
                f.write(notes)
            with open(os.path.join(folder, "review.json"), "w", encoding="utf-8") as f:
                json.dump(review, f, ensure_ascii=False, indent=2)
            with open(os.path.join(folder, "history.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps({"score": review["score"], "scores": review["scores"]}) + "\n")
        return io.NodeOutput(review["score"], report, notes)


class OpenAdFactoryExtension(ComfyExtension):
    @override
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [OpenAdProductPage, OpenAdPlanner, OpenAdShot, OpenAdAssemble, OpenAdViralityJudge]

"""Storyboard prompts and parsing for the ad planner.

The planner LLM writes one JSON object. Everything downstream (keyframes, video
prompts, captions, end card, judge) reads from that object, so parsing is strict:
a storyboard either has every field the graph needs or it raises.
"""
import json
import re

SHOT_ROLES = {
    "hook": "Stop the scroll in the first second: a surprising visual, a bold question or a striking close-up of the product.",
    "problem": "Show the everyday pain the product solves, in a relatable moment.",
    "solution": "The product enters and fixes the problem. The product is the hero of the frame.",
    "proof": "Show it working: a close-up detail, a result, a happy user or a before and after.",
    "cta": "Product beauty shot with a clear reason to act now.",
}

LAYOUTS = {
    3: ["hook", "solution", "cta"],
    4: ["hook", "problem", "solution", "cta"],
    5: ["hook", "problem", "solution", "proof", "cta"],
}

STYLES = {
    "ugc": "UGC creator style: handheld phone footage, natural light, a real person talking to camera, authentic and casual.",
    "cinematic": "Cinematic commercial: polished studio lighting, slow camera moves, premium product beauty shots.",
    "playful": "Playful social ad: bright colors, fast energetic motion, fun props, upbeat tone.",
    "minimal": "Minimal premium: clean backgrounds, soft shadows, calm pacing, elegant product focus.",
}

SYSTEM_PROMPT = """You are a senior performance-marketing creative director who writes short vertical video ads for TikTok, Reels and Shorts.
You turn a product brief into a shot-by-shot storyboard that an image model and an image-to-video model will render.
Answer with ONE JSON object and nothing else: no markdown, no code fences, no comments."""

USER_TEMPLATE = """Write a {seconds}-second vertical (9:16) video ad with exactly {n} shots of about {shot_seconds} seconds each.

PRODUCT BRIEF
{brief}

AD STYLE: {style}
TARGET AUDIENCE: {audience}
LANGUAGE of voiceover and captions: {language}
{extra}
SHOT ORDER (use these roles in this order):
{roles}

RULES
- The product photo is <image1>. Every keyframe_prompt must keep the exact product from <image1> (same shape, color, logo, packaging) and say where it is in the frame.
- keyframe_prompt: an image-edit instruction that turns <image1> into the first frame of the shot. Describe setting, people, lighting, camera framing. Vertical 9:16 composition.
- motion_prompt: what moves during the shot, in present tense, plus camera motion and ambient sound. Do not repeat the keyframe description. No scene cuts inside a shot.
- voiceover: the exact words spoken in this shot, at most {max_words} words, natural and punchy. The cta shot ends with the call to action.
- caption: on-screen text for this shot, at most 6 words.
- Never invent facts, prices, discounts or claims that are not in the brief.

JSON SCHEMA
{{
  "product_name": "short product name",
  "audience": "who this ad is for",
  "angle": "the one selling idea of the ad",
  "voice": "voiceover voice, e.g. 'a warm female voice'",
  "headline": "end card headline, at most 6 words",
  "cta": "end card call to action, at most 4 words",
  "post_caption": "caption for the social post, one or two sentences",
  "hashtags": ["#tag", "#tag", "#tag"],
  "shots": [
    {{"role": "hook", "keyframe_prompt": "...", "motion_prompt": "...", "voiceover": "...", "caption": "..."}}
  ]
}}"""

REPAIR_PROMPT = """Your previous answer was not valid storyboard JSON ({error}).
Return the same storyboard again as ONE valid JSON object that follows the schema exactly, with exactly {n} shots. No other text.

Previous answer:
{previous}"""

REQUIRED_TOP = ("product_name", "voice", "headline", "cta", "shots")
REQUIRED_SHOT = ("role", "keyframe_prompt", "motion_prompt", "voiceover", "caption")


def build_user_prompt(brief, num_shots, seconds_per_shot, style, audience, language, feedback=""):
    roles = LAYOUTS[num_shots]
    extra = ""
    if feedback.strip():
        extra = "\nFEEDBACK FROM THE LAST CUT (fix every point):\n" + feedback.strip() + "\n"
    return USER_TEMPLATE.format(
        seconds=num_shots * seconds_per_shot,
        n=num_shots,
        shot_seconds=seconds_per_shot,
        brief=brief.strip(),
        style=STYLES[style],
        audience=audience.strip() or "infer the most likely buyer from the brief",
        language=language,
        extra=extra,
        roles="\n".join(f"{i + 1}. {r}: {SHOT_ROLES[r]}" for i, r in enumerate(roles)),
        max_words=max(6, int(seconds_per_shot * 2.6)),
    )


def _normalize_keys(value):
    # Small models emit keys like " shots" or "Voiceover"
    if isinstance(value, dict):
        return {k.strip().lower(): _normalize_keys(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_keys(v) for v in value]
    return value


def extract_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object found")
    blob = text[start:end + 1]
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        # Trailing commas are the most common LLM JSON mistake
        data = json.loads(re.sub(r",\s*([}\]])", r"\1", blob))
    return _normalize_keys(data)


def parse_storyboard(text, num_shots):
    data = extract_json(text)
    missing = [k for k in REQUIRED_TOP if not data.get(k)]
    if missing:
        raise ValueError(f"missing fields {missing}")
    shots = data["shots"]
    if not isinstance(shots, list) or len(shots) != num_shots:
        raise ValueError(f"expected {num_shots} shots, got {len(shots) if isinstance(shots, list) else 'none'}")
    for i, shot in enumerate(shots):
        missing = [k for k in REQUIRED_SHOT if not str(shot.get(k, "")).strip()]
        if missing:
            raise ValueError(f"shot {i + 1} is missing {missing}")
    data["hashtags"] = [h if h.startswith("#") else "#" + h for h in (data.get("hashtags") or []) if isinstance(h, str) and h.strip()]
    return data


def _sentence(text):
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."


def keyframe_prompt(storyboard, index):
    shot = storyboard["shots"][index]
    return f"{_sentence(shot['keyframe_prompt'])} Keep the product from <image1> exactly as it is. Photorealistic, vertical 9:16 frame, no text or watermarks."


def video_prompt(storyboard, index):
    shot = storyboard["shots"][index]
    line = shot["voiceover"].strip().replace('"', "'")
    return f"{_sentence(shot['motion_prompt'])} {storyboard['voice'].strip().capitalize()} says in a clear voice-over: \"{line}\""


def summary(storyboard):
    lines = [f"# {storyboard['product_name']}", f"Angle: {storyboard.get('angle', '')}", f"Audience: {storyboard.get('audience', '')}", ""]
    for i, shot in enumerate(storyboard["shots"]):
        lines += [f"## Shot {i + 1}: {shot['role']}", f"Keyframe: {shot['keyframe_prompt']}", f"Motion: {shot['motion_prompt']}",
                  f"Voiceover: \"{shot['voiceover']}\"", f"Caption: {shot['caption']}", ""]
    lines += [f"End card: {storyboard['headline']} / {storyboard['cta']}", "", storyboard.get("post_caption", ""), " ".join(storyboard["hashtags"])]
    return "\n".join(lines)

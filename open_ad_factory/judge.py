"""Virality judge: a multimodal LLM watches the cut and grades it on a fixed rubric.

The LLM only gives 0-10 sub-scores and notes. The final 0-100 score is a fixed
weighted sum computed here, so it is stable and comparable between runs.
The rubric follows what drives short-video engagement: an early hook, a clear
subject, pacing and audio (see the SnapUGC engagement study, ECCV 2024).
"""
from .storyboard import extract_json

RUBRIC = {
    "hook": (25, "Do the first 2 seconds stop the scroll? Strong motion, a face, a question or a surprising visual score high. A slow static opening scores low."),
    "product_clarity": (20, "Is the product clearly visible, recognizable and consistent across shots?"),
    "message": (15, "Is the single benefit obvious to someone who watches once with the sound off?"),
    "pacing": (15, "Does every second earn its place? No dead time, no confusing jumps."),
    "audio": (10, "Is the voiceover clear and natural, and does the sound fit the visuals?"),
    "cta": (10, "Does the ad end with a clear, specific reason and way to act now?"),
    "visual_quality": (5, "Free of AI artifacts: warped hands or faces, melting product, flicker, unreadable text."),
}

SYSTEM_PROMPT = "You are a strict short-video ad reviewer who predicts how a vertical ad will perform on TikTok and Reels. You answer with one JSON object only."

USER_TEMPLATE = """Watch this vertical video ad and listen to its audio. Grade it against the creative brief.

CREATIVE BRIEF (what the ad was meant to do)
{brief}

Score each criterion from 0 to 10 (10 = best in class, 5 = average ad, 0 = broken):
{rubric}

Then list the most important fixes for the next cut. Each fix must name the shot (1-{n}) or "end card" and say concretely what to change.

Answer with ONE JSON object, no other text:
{{
  "scores": {{{keys}}},
  "strengths": ["..."],
  "fixes": ["Shot 1: ...", "..."],
  "verdict": "one sentence prediction of how this ad will perform"
}}"""


def build_user_prompt(brief, num_shots):
    return USER_TEMPLATE.format(
        brief=brief.strip(),
        rubric="\n".join(f"- {k}: {desc}" for k, (_, desc) in RUBRIC.items()),
        n=num_shots,
        keys=", ".join(f'"{k}": 0' for k in RUBRIC),
    )


def parse_review(text):
    data = extract_json(text)
    scores = data.get("scores")
    if not isinstance(scores, dict):
        raise ValueError("review has no scores object")
    clean = {}
    for key in RUBRIC:
        if key not in scores:
            raise ValueError(f"review is missing the {key} score")
        clean[key] = min(10.0, max(0.0, float(scores[key])))
    data["scores"] = clean
    data["fixes"] = [str(f) for f in data.get("fixes") or []]
    data["strengths"] = [str(s) for s in data.get("strengths") or []]
    data["verdict"] = str(data.get("verdict", ""))
    data["score"] = weighted_score(clean)
    return data


def weighted_score(scores):
    total = sum(w for w, _ in RUBRIC.values())
    return round(sum(scores[k] * w for k, (w, _) in RUBRIC.items()) * 10.0 / total, 1)


def grade(score):
    for limit, label in ((85, "A: ready to scale"), (70, "B: ready to test"), (55, "C: needs another cut"), (0, "D: rework the concept")):
        if score >= limit:
            return label


def report(review):
    lines = [f"Virality score: {review['score']} / 100 ({grade(review['score'])})", review["verdict"], ""]
    for key, (weight, _) in RUBRIC.items():
        value = review["scores"][key]
        lines.append(f"{key:<15} {value:>4.1f}/10  {'#' * round(value)}{'.' * (10 - round(value))}  weight {weight}")
    if review["strengths"]:
        lines += ["", "Strengths:"] + [f"+ {s}" for s in review["strengths"]]
    if review["fixes"]:
        lines += ["", "Fixes for the next cut:"] + [f"- {f}" for f in review["fixes"]]
    return "\n".join(lines)


def feedback(review):
    """Plain-text notes the planner reads on the next run."""
    return "\n".join(f"- {f}" for f in review["fixes"])

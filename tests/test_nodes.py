"""Run the real node classes inside ComfyUI with a fake LLM. Needs COMFYUI_PATH (default ../ComfyUI)."""
import json
import os
import sys
from fractions import Fraction

import pytest
import torch

COMFYUI_PATH = os.path.abspath(os.environ.get("COMFYUI_PATH", os.path.join(os.path.dirname(__file__), "..", "..", "ComfyUI")))
if not os.path.isdir(os.path.join(COMFYUI_PATH, "comfy_api")):
    pytest.skip(f"ComfyUI not found at {COMFYUI_PATH}", allow_module_level=True)
sys.path.insert(0, COMFYUI_PATH)

import folder_paths  # noqa: E402
from comfy_api.latest import InputImpl, Types  # noqa: E402

from open_ad_factory import judge  # noqa: E402
from open_ad_factory.nodes import OpenAdAssemble, OpenAdPlanner, OpenAdShot, OpenAdViralityJudge  # noqa: E402
from test_pure import make_board  # noqa: E402


class FakeClip:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def tokenize(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        return {"g": [[(1, 1.0)]]}

    def generate(self, tokens, **kwargs):
        return [0]

    def decode(self, ids):
        return self.answers.pop(0) if len(ids) == 1 and ids == [0] and self.answers else "x"


@pytest.fixture(autouse=True)
def output_dir(tmp_path):
    folder_paths.set_output_directory(str(tmp_path))
    return tmp_path


def fake_video(frames=25, h=64, w=36, fps=25):
    audio = {"waveform": torch.rand(1, 2, 48000 * frames // fps), "sample_rate": 48000}
    return InputImpl.VideoFromComponents(Types.VideoComponents(images=torch.rand(frames, h, w, 3), audio=audio, frame_rate=Fraction(fps)))


def review_json(score=6):
    return json.dumps({"scores": {k: score for k in judge.RUBRIC}, "fixes": ["Shot 1: open on motion"], "strengths": ["clear product"], "verdict": "ok"})


def plan(clip, project="t", feedback=True):
    return OpenAdPlanner.execute(clip=clip, brief="Product: Acme Bottle", num_shots="4", seconds_per_shot=5, style="ugc", audience="",
                                 language="English", project=project, use_judge_feedback=feedback, seed=1, max_length=1024).result


def test_planner_repairs_bad_json_and_saves(output_dir):
    clip = FakeClip("not json at all", json.dumps(make_board()))
    board, summary, post = plan(clip)
    assert len(board["shots"]) == 4 and board["seconds_per_shot"] == 5
    assert "Shot 4: cta" in summary and post.endswith("#hydration #hike")
    assert "previous answer was not valid" in clip.calls[1]["prompt"]
    assert (output_dir / "open_ad_factory" / "t" / "storyboard.json").exists()


def test_planner_raises_after_two_bad_answers():
    with pytest.raises(ValueError, match="valid storyboard"):
        plan(FakeClip("nope", "still nope"))


def test_shot_outputs_and_bounds():
    board = make_board(3)
    kf, vp, cap = OpenAdShot.execute(storyboard=board, shot=2).result
    assert "<image1>" in kf and "voice-over" in vp and cap == "cap solution"
    with pytest.raises(ValueError, match="has 3 shots"):
        OpenAdShot.execute(storyboard=board, shot=4)


def test_assemble_adds_captions_and_end_card(tmp_path):
    board = make_board()
    out = OpenAdAssemble.execute(storyboard=board, product_image=torch.rand(1, 100, 80, 3), video_1=fake_video(), video_2=fake_video(50),
                                 captions=True, caption_position=0.7, end_card_seconds=2.0, font_path="").result[0]
    c = out.get_components()
    assert c.images.shape == (25 + 50 + 50, 64, 36, 3)
    assert c.audio["waveform"].shape == (1, 2, 48000 * 5)
    assert c.frame_rate == 25

    path = tmp_path / "ad.mp4"
    out.save_to(str(path))
    decoded = InputImpl.VideoFromFile(str(path)).get_components()
    assert decoded.images.shape[0] == 125 and decoded.audio is not None


def test_judge_feedback_loop_reaches_planner(output_dir):
    board = make_board()
    board["brief"] = "Product: Acme Bottle"
    clip = FakeClip(review_json())
    score, report, notes = OpenAdViralityJudge.execute(clip=clip, video=fake_video(50), storyboard=board, project="loop", save_feedback=True,
                                                       frame_size=448, seed=0, max_length=512, language="Japanese").result
    assert "Write the strengths, fixes and verdict in Japanese" in clip.calls[0]["prompt"]
    assert score == 60.0 and "60.0 / 100" in report and notes == "- Shot 1: open on motion"
    assert clip.calls[0]["video"].shape[0] == 48 and clip.calls[0]["audio"] is not None

    planner_clip = FakeClip(json.dumps(make_board()))
    plan(planner_clip, project="loop")
    assert "Shot 1: open on motion" in planner_clip.calls[0]["prompt"]
    assert OpenAdPlanner.fingerprint_inputs(project="loop", use_judge_feedback=True) != ""

    off_clip = FakeClip(json.dumps(make_board()))
    plan(off_clip, project="loop", feedback=False)
    assert "FEEDBACK" not in off_clip.calls[0]["prompt"]

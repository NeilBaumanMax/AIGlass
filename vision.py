from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
UPSTREAM = ROOT / "vendor" / "walkguide"
sys.path.insert(0, str(UPSTREAM))

WALKGUIDE_REVISION = "1bd27dd1a90d5b169074588a3487611f40af4716"
DIRECTION_MESSAGES = {
    "straight": "画面中候选通道向前",
    "left": "画面中候选通道偏左",
    "right": "画面中候选通道偏右",
    "stop": "通道不足或不确定，请暂停确认",
}


class Vision:
    def __init__(self):
        import torch

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.models = {}

    def prepare(self):
        from transformers import SegformerForSemanticSegmentation
        for mode in ("indoor", "outdoor"):
            if mode not in self.models:
                self.models[mode] = SegformerForSemanticSegmentation.from_pretrained(
                    UPSTREAM / f"model-{mode}", local_files_only=True
                ).to(self.device).eval()

    def analyze(self, image, mode):
        from live_overlay import indoor_input, indoor_regions, render_regions
        from outdoor_channel import channel_input, channel_regions, trim_channel
        from transformers import SegformerForSemanticSegmentation
        from walkscapes import predict_mask
        from walking_guidance import render_guidance

        if mode not in self.models:
            self.models[mode] = SegformerForSemanticSegmentation.from_pretrained(
                UPSTREAM / f"model-{mode}", local_files_only=True
            ).to(self.device).eval()

        if mode == "indoor":
            frame, clipped = indoor_input(image, enhance=True)
        else:
            frame = channel_input(image)
        labels, confidence = predict_mask(frame, self.models[mode], self.device, with_confidence=True)
        stairs = None
        if mode == "indoor":
            floor, obstacles, stairs = indoor_regions(labels, confidence, clipped)
        else:
            floor, obstacles = channel_regions(labels, confidence)
            floor = trim_channel(image, floor)

        # Use the same masks and renderer as the pinned upstream live pipeline.
        overlay, direction = render_guidance(render_regions(image, floor, obstacles, stairs), floor)

        # Prototype image-space thresholds. They do not estimate physical clearance.
        h, w = floor.shape
        center = (slice(h * 55 // 100, h * 95 // 100), slice(w // 3, 2 * w // 3))
        event = DIRECTION_MESSAGES[direction]
        if stairs is not None and stairs[center].mean() >= 0.08:
            event = "前方疑似台阶"
        elif obstacles[center].mean() >= 0.15:
            event = "前方有障碍"
        self.analysis = {
            'floor': round(float(floor.mean()) * 100, 1),
            'obstacle': round(float(obstacles.mean()) * 100, 1),
            'stairs': round(float(stairs.mean()) * 100, 1) if stairs is not None else None,
            'direction': direction,
            'direction_message': DIRECTION_MESSAGES[direction],
            'message': event,
        }
        return overlay, event

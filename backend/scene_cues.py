"""Interpret unchanged WalkGuide masks for speech; never promote green to a route."""
import cv2
import numpy as np


def visible_surface(floor):
    """Find a substantial patch in the lower view, not isolated green pixels.

    All thresholds are image-space prototype thresholds, not physical clearance.
    A result here permits an observation cue only, never a walking direction.
    """
    h, w = floor.shape
    roi = floor[h * 45 // 100:h * 95 // 100]
    _, _, stats, centers = cv2.connectedComponentsWithStats(roi.astype(np.uint8), connectivity=8)
    candidates = [i for i in range(1, len(stats))
                  if stats[i, cv2.CC_STAT_AREA] >= roi.size * .04
                  and stats[i, cv2.CC_STAT_HEIGHT] >= h * .18
                  and stats[i, cv2.CC_STAT_WIDTH] >= w * .08]
    candidates.sort(key=lambda i: stats[i, cv2.CC_STAT_AREA], reverse=True)
    if not candidates:
        return None
    if len(candidates) > 1 and stats[candidates[0], cv2.CC_STAT_AREA] < 1.5 * stats[candidates[1], cv2.CC_STAT_AREA]:
        return 'ambiguous'
    x = centers[candidates[0], 0] / w
    return 'left' if x < .4 else 'right' if x > .6 else 'ahead'


def describe_scene(floor, obstacles, stairs, direction):
    h, w = floor.shape
    center = (slice(h * 55 // 100, h * 95 // 100), slice(w // 3, 2 * w // 3))
    if stairs is not None and stairs[center].mean() >= .08:
        return {'kind': 'stairs', 'reason': '前方区域识别到疑似台阶，优先停步确认'}
    if obstacles[center].mean() >= .15:
        kind = 'obstacle_' + direction if direction in {'left', 'right'} else 'obstacle'
        return {'kind': kind, 'reason': '前方区域有障碍；侧向提示仅采用 WalkGuide 已找到的连续通道'}
    if direction in {'left', 'right', 'straight'}:
        return {'kind': direction, 'reason': 'WalkGuide 找到从近处延伸的连续候选通道，仍非实际净空测量'}
    side = visible_surface(floor)
    if side is None:
        return {'kind': 'unclear', 'reason': '没有足够连续的可见路面，不能给出行走方向'}
    if side == 'ambiguous':
        return {'kind': 'stop', 'reason': '局部路面分布在多处，但没有连续路线，不任选一侧'}
    return {'kind': 'scan_' + side, 'reason': '有局部绿色路面，但 WalkGuide 未找到连续路线；只提示观察方向'}

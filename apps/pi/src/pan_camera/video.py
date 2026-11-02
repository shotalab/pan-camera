# SPDX-License-Identifier: AGPL-3.0-only

"""Preview rendering and JPEG encoding."""

import cv2
import numpy as np


def draw_preview(frame, tracks, selected_id, width, height):
    image = cv2.resize(
        frame, (width, height),
        interpolation=cv2.INTER_AREA,
    )
    sx = width / frame.shape[1]
    sy = height / frame.shape[0]

    for track in tracks:
        x1, y1, x2, y2 = track["box"]
        a = (max(0, min(width - 1, round(x1 * sx))), max(0, min(height - 1, round(y1 * sy))))
        b = (max(0, min(width - 1, round(x2 * sx))), max(0, min(height - 1, round(y2 * sy))))
        if b[0] <= a[0] or b[1] <= a[1]:
            continue

        selected = track["id"] == selected_id
        color = (220, 230, 70) if selected else (190, 183, 170)
        thickness = 2 if selected else 1
        arm = max(2, min(round(12 * width / 320), (b[0]-a[0]) // 3, (b[1]-a[1]) // 3))
        for x, dx in ((a[0], 1), (b[0], -1)):
            for y, dy in ((a[1], 1), (b[1], -1)):
                points = ((x + dx * arm, y), (x, y), (x, y + dy * arm))
                for start, end in zip(points, points[1:]):
                    cv2.line(image, start, end, (22, 20, 16), thickness + 2, cv2.LINE_AA)
                    cv2.line(image, start, end, color, thickness, cv2.LINE_AA)

        label = f"{track.get('name', 'cup').upper()} {track['id']}"
        scale = 0.42 if width == 320 else 0.7
        (tw, th), base = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, scale, 1
        )

        label_height = th + base + 5
        gap = max(5, round(5 * width / 320))
        lx = max(0, min(width - tw - 6, a[0]))
        if a[1] - gap - label_height >= 0:
            top = a[1] - gap - label_height
        elif b[1] + gap + label_height < height:
            top = b[1] + gap
        else:
            # For edge-filling objects, put the label inside, past the corner arms.
            top = min(height - label_height - 1, a[1] + arm + gap)
            lx = max(0, min(width - tw - 6, a[0] + arm + gap))
        ly = top + th + 3

        cv2.rectangle(
            image,
            (lx, top),
            (lx + tw + 5, ly + base + 1),
            color if selected else (29, 25, 20), -1,
        )
        cv2.putText(
            image, label, (lx + 2, ly),
            cv2.FONT_HERSHEY_SIMPLEX, scale, (25, 24, 18) if selected else color, 1,
            cv2.LINE_AA,
        )
    # Edge markers indicate the center axis without covering the subject.
    cx = width // 2
    size = max(3, round(5 * width / 320))
    for points in (
        [(cx - size, 1), (cx + size, 1), (cx, size + 2)],
        [(cx - size, height - 2), (cx + size, height - 2), (cx, height - size - 3)],
    ):
        triangle = np.array(points, dtype=np.int32)
        cv2.fillConvexPoly(image, triangle, (220, 230, 70), cv2.LINE_AA)
        cv2.polylines(image, [triangle], True, (25, 24, 18), 1, cv2.LINE_AA)
    return image


def encode_jpeg(image):
    for quality in (50, 40, 30, 20):
        ok, encoded = cv2.imencode(
            ".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality]
        )
        if ok and len(encoded) <= 32768:
            return encoded.tobytes()
    return None

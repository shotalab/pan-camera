# SPDX-License-Identifier: AGPL-3.0-only
"""Reconstruct the normal M5Stack screen from Pi-side video and telemetry."""

import time

import cv2
import numpy as np

DISPLAY_FPS = 4


def color565(value):
    return ((value & 31) * 255 // 31, ((value >> 5) & 63) * 255 // 63,
            ((value >> 11) & 31) * 255 // 31)


BG = color565(0x0862)
LINE = color565(0x21A6)
WHITE = (255, 255, 255)
CYAN = (255, 255, 0)
RED = (0, 0, 255)
GREY = (192, 192, 192)


def draw_display(preview, *, state, selected_id, target_name, confidence,
                 object_count, error, pwm, fps, seconds):
    """Return a 320x240 BGR reconstruction; local-only LCD overlays are excluded."""
    image = np.empty((240, 320, 3), dtype=np.uint8)
    image[:] = BG
    image[20:200] = preview

    def text(label, x, y, color=WHITE):
        # Fixed six-pixel cells approximate the LCD's built-in small font.
        for char in str(label):
            cv2.putText(image, char, (x, y + 7), cv2.FONT_HERSHEY_PLAIN,
                        .65, color, 1, cv2.LINE_AA)
            x += 6

    def tile(x, y, width, height, color):
        cv2.rectangle(image, (x + 3, y), (x + width - 4, y + height - 1), color, -1)
        cv2.rectangle(image, (x, y + 3), (x + width - 1, y + height - 4), color, -1)
        for cx in (x + 3, x + width - 4):
            for cy in (y + 3, y + height - 4):
                cv2.circle(image, (cx, cy), 3, color, -1)

    mode = ('STANDBY', 'TRACK', 'LOST')[state]
    mode_color = (CYAN, (0, 255, 0), (0, 255, 255))[state]
    cv2.circle(image, (8, 10), 2, CYAN, -1)
    text('PAN-CAMERA', 17, 6)
    tile(110, 3, 100, 14, LINE)
    text(mode, 160 - len(mode) * 3, 6, mode_color)
    rec = f'REC {seconds // 60:02d}:{seconds % 60:02d}'
    rec_x = 315 - len(rec) * 6
    text(rec, rec_x, 6, RED)
    cv2.circle(image, (rec_x - 8, 10), 3, RED, -1)
    cv2.line(image, (0, 19), (319, 19), LINE)
    if selected_id is None:
        status = f'{object_count} OBJ   FREE   CONF --   ERR --'
    elif state == 2:
        status = f'{object_count} OBJ   {target_name.upper()[:10]} {selected_id}   CONF --'
    else:
        status = f'{object_count} OBJ   {target_name.upper()[:10]} {selected_id}   {confidence}% E{error:+d}'
    text(status, 7, 202)
    # RX and drop counts only exist on the physical receiver.
    text(f'PWM:{pwm} FPS:{fps:.1f} RX:-- D:--', 7, 213, GREY)
    for x in (4, 110, 216):
        tile(x, 225, 100, 14, LINE)
    text('A SELECT', 30, 229)
    text('B STOP' if state else 'B CENTER' if selected_id is None else 'B START', 139, 229, CYAN)
    text('C STOP', 251, 229, RED)
    return image


class DisplayRecorder:
    """Low-rate MJPEG output with wall-clock timing and held frames across gaps."""

    def __init__(self, path, started):
        self.writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'),
                                      DISPLAY_FPS, (320, 240))
        if not self.writer.isOpened():
            self.writer.release()
            raise RuntimeError('Display recording file could not be opened')
        self.started = started
        self.count = 0
        self.previous = None

    def _slot(self):
        return int(max(0, time.monotonic() - self.started) * DISPLAY_FPS)

    def write(self, preview, **status):
        slot = self._slot()
        if slot < self.count:
            return
        image = draw_display(preview, **status)
        while self.count < slot:
            self.writer.write(self.previous if self.previous is not None else image)
            self.count += 1
        self.writer.write(image)
        self.count += 1
        self.previous = image

    def stop(self):
        try:
            if self.previous is not None:
                slot = self._slot()
                while self.count <= slot:
                    self.writer.write(self.previous)
                    self.count += 1
        finally:
            self.writer.release()

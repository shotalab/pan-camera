# SPDX-License-Identifier: AGPL-3.0-only

"""Minimal timestamped Matroska input stream for unchanged MJPEG packets.

Element definitions: https://www.matroska.org/technical/elements.html
The final indexed video/audio file is muxed by FFmpeg, not by this module.
"""


def _element(identifier, data):
    size = len(data)
    length = next(n for n in range(1, 9) if size < (1 << (7 * n)) - 1)
    return bytes.fromhex(identifier) + ((1 << (7 * length)) | size).to_bytes(length, 'big') + data


def _uint(identifier, value):
    return _element(identifier, value.to_bytes(max(1, (value.bit_length() + 7) // 8), 'big'))


def header(width, height, fps):
    ebml = (_uint('4286', 1) + _uint('42f7', 1) + _uint('42f2', 4)
            + _uint('42f3', 8) + _element('4282', b'matroska')
            + _uint('4287', 4) + _uint('4285', 2))
    info = (_uint('2ad7b1', 1_000_000) + _element('4d80', b'PAN-CAMERA')
            + _element('5741', b'PAN-CAMERA'))
    track = (_uint('d7', 1) + _uint('73c5', 1) + _uint('83', 1) + _uint('9c', 0)
             + _element('86', b'V_MJPEG') + _uint('23e383', int(1_000_000_000 / fps))
             + _element('e0', _uint('b0', width) + _uint('ba', height)))
    return (_element('1a45dfa3', ebml) + bytes.fromhex('18538067') + b'\x01' + b'\xff' * 7
            + _element('1549a966', info) + _element('1654ae6b', _element('ae', track)))


def frame(jpeg, timestamp_ms):
    # One keyframe per cluster, track 1, relative block time 0, no lacing.
    block = _element('a3', b'\x81\x00\x00\x80' + jpeg)
    return _element('1f43b675', _uint('e7', timestamp_ms) + block)

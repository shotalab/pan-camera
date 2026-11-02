# SPDX-License-Identifier: AGPL-3.0-only

"""Run target selection, visual tracking, remote control and recording."""

import argparse
import secrets
import shutil
import socket
import struct
import time
from collections import OrderedDict

import cv2
import numpy as np
from ultralytics import YOLO

from .camera import USBCamera169, LatestFrameCamera
from .actuator import ServoConfig
from .controller import PanController
from .paths import ROOT
from .protocol import TELEMETRY, load_network, send_video
from .recorder import RECORD_DIR, Recorder
from .video import draw_preview, encode_jpeg
from .smooth_servo import SmoothPanServo
from .detection_config import enabled_classes
from .raw_recorder import RecordingConfig

TRACKER = ROOT / "config/bytetrack_pan.yaml"

HEARTBEAT_TIMEOUT = 2.0
MAX_RECORD_SECONDS = 600


def extract_tracks(result):
    boxes = result.boxes
    if boxes is None or len(boxes) == 0:
        return []

    ids = (
        boxes.id.int().cpu().tolist()
        if boxes.id is not None
        else [None] * len(boxes)
    )
    coords = boxes.xyxy.cpu().tolist()
    scores = boxes.conf.cpu().tolist()
    classes = boxes.cls.int().cpu().tolist()

    tracks = []
    for tid, box, score, class_id in zip(ids, coords, scores, classes):
        if tid is None:
            continue
        x1, y1, x2, y2 = box
        tracks.append({
            "id": int(tid),
            "box": box,
            "cx": (x1 + x2) / 2,
            "confidence": float(score),
            "class_id": int(class_id),
            "name": result.names[int(class_id)],
        })
    return tracks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-servo", action="store_true")
    parser.add_argument("--fps", type=float, default=8.0)
    parser.add_argument("--preview-fps", type=float, default=4.0)
    parser.add_argument("--profile", action="store_true", help="Print measured rates and timings every 5 seconds")
    parser.add_argument("--frames", type=int, default=0)
    parser.add_argument("--classes", nargs="+", help="Override enabled classes, e.g. cup person")
    parser.add_argument("--list-classes", action="store_true", help="List pretrained classes and exit")
    args = parser.parse_args()

    if not 0 <= args.fps <= 30 or not 0 < args.preview_fps <= 10 or args.frames < 0:
        parser.error("Invalid --fps or --frames")

    destination, control_port = load_network()

    model = YOLO(str(ROOT / "models/yolo26n.pt"))
    if args.list_classes:
        for class_id, name in model.names.items():
            print(f"{class_id:2d}: {name}")
        return
    try:
        class_ids = enabled_classes(model.names, args.classes)
    except ValueError as exc:
        parser.error(str(exc))
    config = ServoConfig.load(ROOT / "config/servo.toml")
    controller = PanController(
        deadband_px=5,
        gain_us_per_px=0.12,
        far_gain_us_per_px=0.28,
        max_step_us=140,
        min_us=config.right_us,
        max_us=config.left_us,
    )

    tracker = str(TRACKER) if TRACKER.exists() else "bytetrack.yaml"
    session = secrets.randbits(32)

    recording_config = RecordingConfig.load()
    recorder = Recorder(args.fps or 8.0, raw_config=recording_config)
    servo = None
    tracking = False
    current_us = config.center_us
    selected_id = None
    selected_class = 255
    tracks = []

    # Duplicate commands return the original ACK.
    seen_commands = OrderedDict()

    last_heartbeat = time.monotonic()
    previous_frame_start = None
    measured_fps = 0.0

    print("PAN-CAMERA")
    print(f"PAN2 session: {session}")
    print(f"Camera: {recording_config.width}x{recording_config.height} | YOLO: 320")
    print(f"Detection: {', '.join(model.names[i] for i in class_ids)}")
    print(f"Remote: {destination}")
    print(f"Control port: UDP {control_port}")
    print(f"Servo permission: {args.allow_servo}")
    print("Initial state: STANDBY")
    print("Ctrl+C to stop", flush=True)

    def stop_servo(reason, *, hold_position=False):
        nonlocal servo, current_us, tracking
        if servo is not None:
            try:
                if hold_position:
                    servo.close(hold_position=True)
                else:
                    servo.close()
            finally:
                current_us = servo.current_us
                servo = None
                tracking = False
                # Keep the last commanded pulse across STOP.
            print(f"TRACK STOP: {reason}", flush=True)

    def apply_command(command, visible):
        nonlocal servo, selected_id, selected_class, current_us, tracking

        if command == "SEL":
            if tracking:
                servo.hold()
                current_us = servo.current_us
                tracking = False
                print("TRACK STOP: BUTTON A (holding position)", flush=True)

            ordered = sorted(visible, key=lambda t: t["cx"])
            ids = [t["id"] for t in ordered]

            # FREE -> leftmost -> ... -> rightmost -> FREE
            if selected_id is None:
                selected_id = ids[0] if ids else None
            elif selected_id not in ids:
                selected_id = None
            else:
                index = ids.index(selected_id)
                selected_id = (
                    ids[index + 1]
                    if index + 1 < len(ids)
                    else None
                )

            selected_class = next((t["class_id"] for t in visible if t["id"] == selected_id), 255)
            print(
                "SELECT FREE" if selected_id is None
                else f"SELECT ID {selected_id}",
                flush=True,
            )
            return 0

        if command == "TOGGLE":
            if tracking:
                servo.hold()
                current_us = servo.current_us
                tracking = False
                print("TRACK STOP: BUTTON B (holding position)", flush=True)
                return 0

            if not args.allow_servo:
                return 2  # Servo locked during preview test

            if selected_id is not None and not any(t["id"] == selected_id for t in visible):
                return 1  # NO TARGET

            if servo is None:
                candidate = SmoothPanServo(
                    config, initial_us=current_us,
                    min_us=controller.min_us, max_us=controller.max_us,
                    resume_held=True,
                )
                try:
                    candidate.__enter__()
                except Exception as exc:
                    try:
                        candidate.close()
                    except Exception:
                        pass
                    print(f"SERVO ERROR: {exc}", flush=True)
                    return 3
                servo = candidate

            if selected_id is None:
                servo.set_target(config.center_us)
                print(f"CENTER: {config.center_us} us", flush=True)
                return 0

            servo.hold()
            tracking = True
            print(f"TRACK START: ID {selected_id}", flush=True)
            return 0

        if command == "REC":
            try:
                if recorder.active:
                    recorder.stop()
                else:
                    recorder.start()
            except Exception as exc:
                print(f"REC ERROR: {exc}", flush=True)
                return 3
            return 0

        return 3

    def receive_commands(sock, visible):
        nonlocal last_heartbeat

        for _ in range(24):
            try:
                packet, address = sock.recvfrom(256)
            except BlockingIOError:
                break

            # Only accept messages from the configured M5Stack.
            if address[0] != destination[0] or address[1] != destination[1]:
                continue

            try:
                values = packet.decode("ascii").strip().split(",")
                kind = values[0]

                if kind == "P2H1" and len(values) == 3:
                    sid, _client = map(int, values[1:])
                    if sid == session:
                        last_heartbeat = time.monotonic()
                    continue

                if kind != "P2C1" or len(values) != 5:
                    continue

                sid, client_id, seq = map(int, values[1:4])
                command = values[4]

                if sid != session:
                    continue
                if not all(0 <= x <= 0xFFFFFFFF
                           for x in (client_id, seq)):
                    continue

            except (ValueError, UnicodeError):
                continue

            last_heartbeat = time.monotonic()
            key = (client_id, seq)

            if key in seen_commands:
                code = seen_commands[key]
            else:
                code = apply_command(command, visible)
                seen_commands[key] = code

                if len(seen_commands) > 128:
                    seen_commands.popitem(last=False)

            reply = f"P2A1,{session},{client_id},{seq},{code}"
            sock.sendto(reply.encode("ascii"), address)

    def send_status(sock, frame_id, state, target, fps):
        confidence = (
            round(target["confidence"] * 100)
            if target is not None else 0
        )
        error = (
            round(target["cx"] - recording_config.width / 2)
            if target is not None else 0
        )

        packet = struct.pack(
            TELEMETRY,
            b"P2T2",
            session,
            frame_id,
            current_us if servo is not None else 0,
            max(-32768, min(32767, error)),
            min(65535, max(0, round(fps * 10))),
            state,
            target["class_id"] if target is not None else selected_class,
            min(100, max(0, confidence)),
            min(255, len(tracks)),
            selected_id if selected_id is not None
            and 0 <= selected_id < 65535 else 65535,
            1 if recorder.active else 0,
            recorder.seconds(),
        )
        sock.sendto(packet, destination)

    frame_id = 0
    next_preview = 0.0
    display_preview = None
    display_jpeg = None
    camera_failed = False

    try:
        with USBCamera169(
            width=recording_config.width, height=recording_config.height,
            fps=recording_config.camera_fps,
            device=recording_config.camera_device,
            raw_callback=recorder.write_raw if recording_config.raw_enabled else None,
        ) as source, LatestFrameCamera(source) as camera:
            # Do not energize the servo unless capture is actually working.
            camera.read()
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.bind(("0.0.0.0", control_port))
                sock.setblocking(False)
                if args.allow_servo:
                    servo = SmoothPanServo(
                        config, initial_us=config.center_us,
                        min_us=controller.min_us, max_us=controller.max_us,
                        resume_held=True,
                    )
                    servo.__enter__()
                    current_us = servo.current_us
                    servo.set_target(config.center_us)
                    last_heartbeat = time.monotonic()
                    print(f"STARTUP CENTER: {config.center_us} us (holding position)", flush=True)

                profile_start = time.monotonic()
                capture_start = camera.captured_count if args.profile else 0
                samples = []
                preview_count = 0

                while args.frames == 0 or frame_id < args.frames:
                    started = time.monotonic()

                    receive_commands(sock, tracks)

                    if servo is not None and (
                        started - last_heartbeat > HEARTBEAT_TIMEOUT
                    ):
                        stop_servo("M5Stack heartbeat timeout")

                    if previous_frame_start is not None:
                        dt = started - previous_frame_start
                        if dt > 0:
                            instant = 1.0 / dt
                            measured_fps = (
                                instant if measured_fps == 0
                                else 0.8 * measured_fps + 0.2 * instant
                            )
                    previous_frame_start = started

                    capture_wait_start = time.monotonic()
                    try:
                        frame = camera.read()
                    except RuntimeError as exc:
                        holding = servo is not None
                        stop_servo("CAMERA LOST (holding position)", hold_position=True)
                        camera_failed = True
                        detail = "PWM position hold remains active." if holding else "Servo was not active."
                        print(f"CAMERA ERROR: {exc}. Exiting; {detail}", flush=True)
                        break
                    inference_start = time.monotonic()

                    result = model.track(
                        frame,
                        persist=True,
                        tracker=tracker,
                        imgsz=320,
                        classes=class_ids,
                        conf=0.1,
                        device="cpu",
                        verbose=False,
                    )[0]
                    inference_end = time.monotonic()

                    tracks = extract_tracks(result)
                    receive_commands(sock, tracks)

                    target = next(
                        (t for t in tracks if t["id"] == selected_id),
                        None,
                    )

                    state = (
                        0 if not tracking else
                        2 if target is None else
                        1
                    )

                    if servo is not None:
                        current_us = servo.current_us
                    if servo is not None and tracking:
                        if target is None:
                            servo.hold()
                        else:
                            target_us = controller.next_pulse(
                                current_us=current_us,
                                cup_x=target["cx"],
                                frame_width=frame.shape[1],
                            )
                            servo.set_target(target_us)

                    feedback_end = time.monotonic()
                    preview_ms = 0.0

                    if time.monotonic() >= next_preview:
                        preview = draw_preview(
                            frame, tracks, selected_id, 320, 180
                        )
                        jpeg = encode_jpeg(preview)
                        if jpeg is not None:
                            send_video(sock, session, frame_id, jpeg, destination)
                            preview_count += 1
                            display_jpeg = jpeg
                            display_preview = None
                        next_preview = started + 1 / args.preview_fps
                        preview_ms = (time.monotonic() - feedback_end) * 1000

                    if recorder.active:
                        if recorder.seconds() >= MAX_RECORD_SECONDS:
                            recorder.stop()
                            print("REC STOP: time limit", flush=True)
                        else:
                            recording_frame = draw_preview(
                                frame, tracks, selected_id, 640, 360
                            )
                            try:
                                recorder.write(recording_frame)
                                if recording_config.display_enabled:
                                    if display_preview is None:
                                        # Reuse the latest JPEG sent to the LCD, including compression.
                                        display_preview = (cv2.imdecode(np.frombuffer(display_jpeg, np.uint8), cv2.IMREAD_COLOR)
                                                           if display_jpeg is not None else
                                                           draw_preview(frame, tracks, selected_id, 320, 180))
                                    selected_track = next((t for t in tracks if t["id"] == selected_id), None)
                                    name = (selected_track["name"] if selected_track is not None
                                            else model.names.get(selected_class, "OBJECT"))
                                    recorder.write_display(
                                        display_preview, state=state, selected_id=selected_id,
                                        target_name=name,
                                        confidence=min(100, max(0, round(target["confidence"] * 100))) if target is not None else 0,
                                        object_count=min(255, len(tracks)),
                                        error=round(target["cx"] - recording_config.width / 2) if target is not None else 0,
                                        pwm=current_us if servo is not None else 0,
                                        fps=round(measured_fps * 10) / 10,
                                        seconds=recorder.seconds(),
                                    )
                            except Exception as exc:
                                print(f"REC ERROR: {exc}", flush=True)
                                try:
                                    recorder.stop()
                                except Exception as stop_error:
                                    print(f"REC CLOSE ERROR: {stop_error}", flush=True)

                            if frame_id % 20 == 0 and (
                                shutil.disk_usage(RECORD_DIR).free
                                < 50 * 1024 * 1024
                            ):
                                recorder.stop()
                                print("REC STOP: disk low", flush=True)

                    send_status(
                        sock, frame_id, state, target, measured_fps
                    )

                    if frame_id % 10 == 0:
                        label = ("STANDBY", "TRACK", "LOST")[state]
                        print(
                            f"{frame_id:04d} | {label} | "
                            f"IDs={[t['id'] for t in tracks]} | "
                            f"SELECT={selected_id} | "
                            f"PWM={current_us if servo else 0} | "
                            f"REC={recorder.active} | "
                            f"FPS={measured_fps:.1f}",
                            flush=True,
                        )

                    frame_id = (frame_id + 1) & 0xFFFFFFFF

                    elapsed = time.monotonic() - started
                    if args.fps:
                        time.sleep(max(0, 1 / args.fps - elapsed))
                    if args.profile:
                        samples.append((
                            (inference_start - capture_wait_start) * 1000,
                            (inference_end - inference_start) * 1000,
                            (feedback_end - inference_end) * 1000,
                            preview_ms,
                            (feedback_end - inference_start) * 1000 + camera.frame_age_ms,
                        ))
                        now = time.monotonic()
                        window = now - profile_start
                        if window >= 5:
                            means = [sum(s[i] for s in samples) / len(samples) for i in range(5)]
                            captured = camera.captured_count
                            print(
                                f"PERF | camera={(captured-capture_start)/window:.1f} FPS | "
                                f"loop={len(samples)/window:.1f} FPS | preview_tx={preview_count/window:.1f} FPS | "
                                f"wait={means[0]:.1f}ms | yolo+tracker={means[1]:.1f}ms | "
                                f"feedback={means[2]:.1f}ms | preview_avg={means[3]:.1f}ms | "
                                f"capture_to_command={means[4]:.1f}ms",
                                flush=True,
                            )
                            profile_start, capture_start = now, captured
                            samples.clear()
                            preview_count = 0

    finally:
        try:
            stop_servo("PROGRAM EXIT")
        finally:
            recorder.stop()
            print("PAN-CAMERA stopped", flush=True)

    if camera_failed:
        raise SystemExit(1)


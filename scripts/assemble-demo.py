"""Compose a silent demo from real screenshots; never synthesize application UI.

Default invocation only prints a plan. --check validates the supplied images.
--render requires every real capture to exist before any image/video is created.
Captures are scaled to fit in full, with no cropping, retouching or fake cursor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FFMPEG = shutil.which("ffmpeg")
PALETTE = {
    "paper": "#f7f6f2", "ink": "#292b2b", "muted": "#787a75",
    "line": "#e4e4dc", "accent": "#de642e", "soft": "#efeee8",
}


def read_manifest(path):
    manifest = json.loads(path.read_text(encoding="utf-8"))
    scenes = manifest.get("scenes", [])
    total = sum(scene["duration_seconds"] for scene in scenes)
    if not scenes or not 150 <= total <= 165:
        raise ValueError("The sequence must contain scenes totaling 150–165 seconds.")
    if len({scene["id"] for scene in scenes}) != len(scenes):
        raise ValueError("Scene IDs must be unique.")
    if manifest.get("canvas") != {"width": 1920, "height": 1080, "fps": 30}:
        raise ValueError("The assembly expects a 1920×1080, 30 fps canvas.")
    if not all(isinstance(scene["duration_seconds"], int) and scene["duration_seconds"] > 0 for scene in scenes):
        raise ValueError("Use positive whole-second scene durations.")
    return manifest, total


def locate_captures(manifest):
    directory = ROOT / manifest["capture_directory"]
    resolved, errors = [], []
    for scene in manifest["scenes"]:
        matches = sorted(directory.glob(scene["capture_pattern"])) if directory.is_dir() else []
        if len(matches) != 1:
            errors.append(f"{scene['id']}: expected one {scene['capture_pattern']}, found {len(matches)}")
        else:
            resolved.append((scene, matches[0]))
    if len({path.resolve() for _, path in resolved}) != len(resolved):
        errors.append("A capture was assigned to more than one scene.")
    return resolved, errors


def inspect_captures(captures):
    from PIL import Image
    records = []
    for scene, path in captures:
        with Image.open(path) as source:
            source_format = source.format
            if source_format not in {"PNG", "JPEG"}:
                raise ValueError(f"{path.name}: actual PNG or JPEG captures are required.")
            source.verify()
        with Image.open(path) as source:
            width, height = source.size
            if width < 320 or height < 240 or width * height > 80_000_000:
                raise ValueError(f"{path.name}: unsuitable screenshot dimensions {width}×{height}.")
        raw = path.read_bytes()
        records.append({
            "scene": scene["id"], "capture": path.relative_to(ROOT).as_posix(),
            "format": source_format,
            "width": width, "height": height, "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        })
    return records


def load_font(filename, size):
    from PIL import ImageFont
    path = Path(r"C:\Windows\Fonts") / filename
    if not path.is_file():
        raise ValueError(f"Required font is missing: {path}")
    return ImageFont.truetype(str(path), size)


def fit_lines(draw, text, font, maximum_width):
    lines = []
    for paragraph in text.splitlines():
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            if draw.textlength(candidate, font=font) <= maximum_width:
                current = candidate
            else:
                if not current:
                    raise ValueError(f"Caption token does not fit: {word}")
                lines.append(current)
                current = word
        if current:
            lines.append(current)
    return lines


def render_frame(manifest, scene, source_path, frame_path, elapsed, total):
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (1920, 1080), PALETTE["paper"])
    draw = ImageDraw.Draw(image)
    sans = load_font("segoeui.ttf", 30)
    small = load_font("segoeui.ttf", 22)
    micro = load_font("segoeui.ttf", 19)
    brand = load_font("segoeuib.ttf", 24)
    heading = load_font("segoeuib.ttf", 49)
    total_scenes = len(manifest["scenes"])
    ordinal = next(i for i, item in enumerate(manifest["scenes"], 1) if item["id"] == scene["id"])

    draw.text((64, 29), "PARTS LEDGER", font=brand, fill=PALETTE["accent"])
    draw.text((292, 31), manifest["disclosure"], font=small, fill=PALETTE["muted"])
    state_label = f"CAPTURED STATE {ordinal:02d} / {total_scenes:02d}"
    draw.text((1856 - draw.textlength(state_label, font=micro), 34), state_label, font=micro, fill=PALETTE["muted"])
    if draw.textlength(scene["title"], font=heading) > 1792:
        raise ValueError(f"Scene {scene['id']}: title is too long for the composition.")
    draw.text((64, 80), scene["title"], font=heading, fill=PALETTE["ink"])

    # This frame is editorial. The entire screenshot remains visible inside it.
    viewport = (64, 166, 1856, 874)
    draw.rectangle(viewport, fill="white", outline=PALETTE["line"], width=1)
    with Image.open(source_path) as original:
        screenshot = original.convert("RGB")
        screenshot.thumbnail((viewport[2] - viewport[0] - 2, viewport[3] - viewport[1] - 2), Image.Resampling.LANCZOS)
        x = viewport[0] + ((viewport[2] - viewport[0]) - screenshot.width) // 2
        y = viewport[1] + ((viewport[3] - viewport[1]) - screenshot.height) // 2
        image.paste(screenshot, (x, y))

    lines = fit_lines(draw, scene["caption"], sans, 1772)
    if len(lines) > 2:
        raise ValueError(f"Scene {scene['id']}: caption exceeds two lines; shorten the text.")
    for index, line in enumerate(lines):
        draw.text((64, 903 + 42 * index), line, font=sans, fill=PALETTE["ink"])
    fact_y = 990 if len(lines) == 2 else 965
    fact = scene.get("editorial_fact", "")
    if draw.textlength(fact, font=small) > 1780:
        raise ValueError(f"Scene {scene['id']}: editorial fact is too long.")
    draw.text((64, fact_y), fact, font=small, fill=PALETTE["muted"])
    # A discrete timeline indicates sequence position, not application progress.
    draw.rectangle((64, 1057, 1856, 1060), fill=PALETTE["line"])
    timeline_right = 64 + round(1792 * (elapsed + scene["duration_seconds"]) / total)
    draw.rectangle((64, 1057, timeline_right, 1060), fill=PALETTE["accent"])
    image.save(frame_path, format="PNG", optimize=True)


def srt_time(seconds):
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},000"


def render(manifest, manifest_path, captures, records, total, ffmpeg):
    if not ffmpeg or not Path(ffmpeg).is_file():
        raise ValueError("ffmpeg was not found. Supply its executable with --ffmpeg.")
    output = ROOT / manifest["output_directory"]
    frames = output / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    concat_lines, subtitle_lines, chapters = [], [], []
    elapsed = 0
    for ordinal, (scene, source_path) in enumerate(captures, 1):
        filename = f"{scene['id']}.png"
        render_frame(manifest, scene, source_path, frames / filename, elapsed, total)
        concat_lines.extend([f"file 'frames/{filename}'", f"duration {scene['duration_seconds']}"])
        subtitle_lines.extend([
            str(ordinal), f"{srt_time(elapsed)} --> {srt_time(elapsed + scene['duration_seconds'])}",
            scene["title"], scene["caption"], "",
        ])
        chapters.append(f"{elapsed // 60}:{elapsed % 60:02d} {scene['title']}")
        elapsed += scene["duration_seconds"]
    concat_lines.append(f"file 'frames/{captures[-1][0]['id']}.png'")
    concat_file = output / "sequence.ffconcat"
    concat_file.write_text("ffconcat version 1.0\n" + "\n".join(concat_lines) + "\n", encoding="utf-8")
    (output / "captions.srt").write_text("\n".join(subtitle_lines), encoding="utf-8")
    (output / "chapters.txt").write_text("\n".join(chapters) + "\n", encoding="utf-8")
    destination = output / manifest["output_filename"]
    command = [
        str(ffmpeg), "-hide_banner", "-loglevel", "warning", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-t", str(total), "-vf", "fps=30,format=yuv420p", "-c:v", "libx264",
        "-preset", "medium", "-crf", "18", "-movflags", "+faststart", "-an",
        "-metadata", "title=Parts Ledger — working browser demo",
        "-metadata", "comment=" + manifest["presentation"], str(destination),
    ]
    completed = subprocess.run(command, check=False)
    if completed.returncode:
        raise ValueError(f"ffmpeg failed with exit code {completed.returncode}.")
    ffprobe = Path(ffmpeg).with_name("ffprobe.exe" if sys.platform == "win32" else "ffprobe")
    probe = None
    if ffprobe.is_file():
        process = subprocess.run([
            str(ffprobe), "-v", "error", "-show_entries", "format=duration:stream=width,height,r_frame_rate,codec_name,codec_type",
            "-of", "json", str(destination),
        ], check=True, capture_output=True, text=True)
        probe = json.loads(process.stdout)
        duration = float(probe["format"]["duration"])
        if abs(duration - total) > 0.2 or duration >= 180:
            raise ValueError(f"Unexpected video duration: {duration} seconds.")
        video_streams = [item for item in probe["streams"] if item["codec_type"] == "video"]
        if len(video_streams) != 1 or (video_streams[0]["width"], video_streams[0]["height"]) != (1920, 1080):
            raise ValueError("The encoded video has unexpected stream dimensions.")
    raw = destination.read_bytes()
    report = {
        "presentation": manifest["presentation"], "disclosure": manifest["disclosure"],
        "source_manifest": manifest_path.relative_to(ROOT).as_posix(),
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "capture_inputs": records, "duration_seconds": total,
        "output": destination.relative_to(ROOT).as_posix(), "output_bytes": len(raw),
        "output_sha256": hashlib.sha256(raw).hexdigest(), "ffprobe": probe,
        "review_status": "Encoded locally; playback and all-frame visual review remain required. Not published or submitted.",
    }
    (output / "assembly-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"rendered": str(destination), "duration_seconds": total, "bytes": len(raw), "published": False}, ensure_ascii=False))


def main():
    # The bundled Windows Python may inherit cp949 through redirected output.
    # Keep the manifest's English typography readable in the console as UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "video/sequence-manifest.json")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--plan", action="store_true", help="Print sequence timing only; write no files.")
    group.add_argument("--check", action="store_true", help="Check real capture inputs; write no files.")
    group.add_argument("--render", action="store_true", help="Assemble from supplied real captures only.")
    parser.add_argument("--ffmpeg", type=Path, default=DEFAULT_FFMPEG)
    args = parser.parse_args()
    try:
        manifest, total = read_manifest(args.manifest)
        captures, errors = locate_captures(manifest)
        elapsed = 0
        if not args.check and not args.render:
            for scene in manifest["scenes"]:
                print(f"{elapsed // 60}:{elapsed % 60:02d}–{(elapsed + scene['duration_seconds']) // 60}:{(elapsed + scene['duration_seconds']) % 60:02d}  {scene['id']}  {scene['title']}")
                elapsed += scene["duration_seconds"]
            print(json.dumps({"duration_seconds": total, "scenes": len(manifest["scenes"]), "captures_present": len(captures), "missing_or_ambiguous": errors, "files_written": 0}, ensure_ascii=False))
            return 0
        if errors:
            raise ValueError("Captures are not ready. Nothing was rendered.\n" + "\n".join(errors))
        records = inspect_captures(captures)
        if args.check:
            print(json.dumps({"capture_inputs": records, "duration_seconds": total, "files_written": 0}, ensure_ascii=False, indent=2))
            return 0
        pending = [scene["id"] for scene in manifest["scenes"] if scene.get("awaiting_outcome")]
        if pending:
            raise ValueError("Final capture mapping/outcomes are not confirmed. Nothing was rendered. Scenes: " + ", ".join(pending))
        render(manifest, args.manifest, captures, records, total, args.ffmpeg)
        return 0
    except (ValueError, OSError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

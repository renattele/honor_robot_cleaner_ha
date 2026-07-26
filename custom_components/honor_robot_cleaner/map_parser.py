"""Parse YuGong / Grit reuse_map_get map_data blobs into rooms + grid."""

from __future__ import annotations

import base64
import json
import logging
import zlib
from dataclasses import dataclass, field
from typing import Any

_LOGGER = logging.getLogger(__name__)


@dataclass
class MapRoom:
    room_id: int
    name: str = ""
    vertices: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class ParsedMap:
    map_id: str = ""
    width: int = 0
    height: int = 0
    resolution: float = 0.05
    x_min: float = 0.0
    y_min: float = 0.0
    dock: tuple[float, float] | None = None
    rooms: list[MapRoom] = field(default_factory=list)
    cells: list[int] | None = None
    path: list[tuple[float, float]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def has_image(self) -> bool:
        return bool(self.width and self.height and self.cells)


def _try_load_object(raw: str | bytes | dict | list | None) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    text = (raw or "").strip()
    if not text:
        return None

    # Direct JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Base64 → JSON / zlib+JSON
    for decoder in (
        lambda s: base64.b64decode(s),
        lambda s: base64.urlsafe_b64decode(s + "=="),
    ):
        try:
            blob = decoder(text)
        except Exception:  # noqa: BLE001
            continue
        try:
            return json.loads(blob.decode("utf-8"))
        except Exception:  # noqa: BLE001
            pass
        try:
            return json.loads(zlib.decompress(blob).decode("utf-8"))
        except Exception:  # noqa: BLE001
            pass
        try:
            return json.loads(zlib.decompress(blob, -zlib.MAX_WBITS).decode("utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return None


def _as_int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _as_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _parse_rooms(obj: dict[str, Any]) -> list[MapRoom]:
    rooms: list[MapRoom] = []
    candidates = (
        obj.get("room_info")
        or obj.get("rooms")
        or obj.get("roomList")
        or obj.get("zone_list")
        or []
    )
    if isinstance(candidates, str):
        try:
            candidates = json.loads(candidates)
        except json.JSONDecodeError:
            candidates = []
    if not isinstance(candidates, list):
        return rooms
    for item in candidates:
        if not isinstance(item, dict):
            continue
        rid = item.get("room_id", item.get("id", item.get("roomId")))
        if rid is None:
            continue
        name = str(
            item.get("room_name")
            or item.get("name")
            or item.get("roomName")
            or f"Room {rid}"
        )
        verts_raw = (
            item.get("vertexList")
            or item.get("vertex_list")
            or item.get("vertices")
            or []
        )
        verts: list[tuple[float, float]] = []
        if isinstance(verts_raw, list):
            for v in verts_raw:
                if isinstance(v, dict):
                    verts.append((_as_float(v.get("x")), _as_float(v.get("y"))))
                elif isinstance(v, (list, tuple)) and len(v) >= 2:
                    verts.append((_as_float(v[0]), _as_float(v[1])))
        rooms.append(MapRoom(room_id=_as_int(rid), name=name, vertices=verts))
    return rooms


def _parse_cells(obj: dict[str, Any], width: int, height: int) -> list[int] | None:
    raw = (
        obj.get("mapData")
        or obj.get("map_data")
        or obj.get("map_cells")
        or obj.get("data")
    )
    if isinstance(raw, list) and raw and isinstance(raw[0], (int, float)):
        return [int(x) for x in raw]
    if isinstance(raw, str) and raw:
        # Sometimes a compact digit string / CSV
        if "," in raw:
            try:
                return [int(x) for x in raw.split(",") if x.strip() != ""]
            except ValueError:
                pass
        try:
            decoded = base64.b64decode(raw)
            return list(decoded)
        except Exception:  # noqa: BLE001
            pass
    if width and height and isinstance(raw, list) and len(raw) == width * height:
        return [int(x) for x in raw]
    return None


def parse_map_data(
    map_data: str | bytes | dict | None,
    *,
    map_id: str = "",
) -> ParsedMap | None:
    """Best-effort parse of Grit map_data into rooms + optional cell grid."""
    obj = _try_load_object(map_data)
    if obj is None:
        return None
    if isinstance(obj, list):
        # Unexpected top-level list — wrap
        obj = {"rooms": obj}
    if not isinstance(obj, dict):
        return None

    # Nested map payload
    for nest in ("map", "map_info", "mapInfo", "data"):
        nested = obj.get(nest)
        if isinstance(nested, dict) and (
            "width" in nested or "mapData" in nested or "rooms" in nested
        ):
            obj = {**obj, **nested}

    width = _as_int(obj.get("width") or obj.get("map_width"))
    height = _as_int(obj.get("height") or obj.get("map_height"))
    parsed = ParsedMap(
        map_id=str(map_id or obj.get("map_id") or obj.get("mapId") or ""),
        width=width,
        height=height,
        resolution=_as_float(obj.get("resolution"), 0.05),
        x_min=_as_float(obj.get("x_min") or obj.get("xmin")),
        y_min=_as_float(obj.get("y_min") or obj.get("ymin")),
        rooms=_parse_rooms(obj),
        cells=_parse_cells(obj, width, height),
        raw=obj,
    )
    dock_x = obj.get("dockerPosX", obj.get("dock_x", obj.get("charger_x")))
    dock_y = obj.get("dockerPosY", obj.get("dock_y", obj.get("charger_y")))
    if dock_x is not None and dock_y is not None:
        parsed.dock = (_as_float(dock_x), _as_float(dock_y))

    path_raw = obj.get("path") or obj.get("path_points") or []
    if isinstance(path_raw, list):
        for p in path_raw:
            if isinstance(p, dict):
                parsed.path.append((_as_float(p.get("x")), _as_float(p.get("y"))))
            elif isinstance(p, (list, tuple)) and len(p) >= 2:
                parsed.path.append((_as_float(p[0]), _as_float(p[1])))

    if not parsed.rooms and not parsed.has_image:
        _LOGGER.debug("map_data parsed but empty rooms/grid keys=%s", list(obj.keys())[:30])
    return parsed


def render_map_png(parsed: ParsedMap, *, scale: int = 4) -> bytes:
    """Render a simple top-down PNG. Uses stdlib only (PPM→via Pillow if present)."""
    try:
        from PIL import Image, ImageDraw  # type: ignore
    except ImportError:
        return _render_placeholder_png(parsed)

    if not parsed.has_image:
        return _render_placeholder_png(parsed)

    w, h = parsed.width, parsed.height
    img = Image.new("RGB", (w, h), (30, 30, 36))
    pixels = img.load()
    assert parsed.cells is not None
    # Heuristic palette: 0 free, >0 room/obstacle variants
    for i, cell in enumerate(parsed.cells[: w * h]):
        x = i % w
        y = i // w
        c = int(cell)
        if c == 0:
            color = (45, 48, 55)
        elif c < 0:
            color = (90, 90, 100)  # unknown / wall-ish
        elif c == 255 or c > 200:
            color = (20, 20, 24)  # obstacle
        else:
            # room tint
            color = (
                40 + (c * 37) % 140,
                80 + (c * 53) % 120,
                120 + (c * 17) % 80,
            )
        pixels[x, y] = color

    if scale != 1:
        img = img.resize((w * scale, h * scale), Image.NEAREST)
    draw = ImageDraw.Draw(img)
    # Dock
    if parsed.dock and parsed.resolution:
        dx = int((parsed.dock[0] - parsed.x_min) / parsed.resolution * scale)
        dy = int((parsed.dock[1] - parsed.y_min) / parsed.resolution * scale)
        r = 4 * scale
        draw.ellipse((dx - r, dy - r, dx + r, dy + r), fill=(255, 200, 40))
    # Path
    if len(parsed.path) >= 2 and parsed.resolution:
        pts = []
        for px, py in parsed.path:
            pts.append(
                (
                    int((px - parsed.x_min) / parsed.resolution * scale),
                    int((py - parsed.y_min) / parsed.resolution * scale),
                )
            )
        draw.line(pts, fill=(80, 180, 255), width=max(1, scale))

    from io import BytesIO

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _render_placeholder_png(parsed: ParsedMap | None) -> bytes:
    """Minimal valid PNG without Pillow (1x1) or labeled canvas with Pillow."""
    try:
        from io import BytesIO

        from PIL import Image, ImageDraw, ImageFont  # type: ignore

        img = Image.new("RGB", (480, 320), (28, 30, 36))
        draw = ImageDraw.Draw(img)
        title = "Honor map"
        if parsed and parsed.map_id:
            title += f" #{parsed.map_id}"
        draw.text((24, 24), title, fill=(220, 220, 230))
        if parsed and parsed.rooms:
            y = 64
            draw.text((24, y), "Rooms:", fill=(160, 170, 190))
            y += 28
            for room in parsed.rooms[:12]:
                draw.text(
                    (36, y),
                    f"{room.room_id}: {room.name}",
                    fill=(200, 210, 220),
                )
                y += 22
        else:
            draw.text(
                (24, 80),
                "No map grid yet.\nSave a map in Honor AI Space,\nthen refresh.",
                fill=(160, 170, 190),
            )
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        # 1x1 PNG
        return base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
            "/x8AAwMCAO5XBZoAAAAASUVORK5CYII="
        )

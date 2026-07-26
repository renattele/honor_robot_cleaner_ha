"""Parse YuGong / Grit map_data (HTTP or live WSS) into rooms + grid."""

from __future__ import annotations

import base64
import json
import logging
import struct
import zlib
from dataclasses import dataclass, field
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Live WSS occupancy: 2-bit cells (MSB first)
CELL_FREE = 0
CELL_WALL = 1
CELL_UNKNOWN = 3


@dataclass
class MapRoom:
    room_id: int
    name: str = ""
    vertices: list[tuple[float, float]] = field(default_factory=list)
    clean_order: int = -1
    draw: bool = True


@dataclass
class ParsedMap:
    map_id: str = ""
    width: int = 0
    height: int = 0
    resolution: float = 0.05
    x_min: float = 0.0
    y_min: float = 0.0
    dock: tuple[float, float] | None = None
    robot: tuple[float, float] | None = None
    rooms: list[MapRoom] = field(default_factory=list)
    cells: list[int] | None = None
    path: list[tuple[float, float]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    # When True, dock/path/room vertices are already pixel coordinates
    pixel_space: bool = False

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

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    for decoder in (
        lambda s: base64.b64decode(s),
        lambda s: base64.urlsafe_b64decode(s + "=="),
    ):
        try:
            blob = decoder(text)
        except Exception:  # noqa: BLE001
            continue
        for unlock in (
            lambda b: b,
            lambda b: zlib.decompress(b),
            lambda b: zlib.decompress(b, -zlib.MAX_WBITS),
        ):
            try:
                return json.loads(unlock(blob).decode("utf-8"))
            except Exception:  # noqa: BLE001
                continue
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


def _b64(data: str) -> bytes:
    pad = "=" * ((4 - len(data) % 4) % 4)
    return base64.b64decode(data + pad)


def _unpack_2bit_msb(blob: bytes, width: int, height: int) -> list[int]:
    need = width * height
    cells: list[int] = []
    for byte in blob:
        for shift in (6, 4, 2, 0):
            cells.append((byte >> shift) & 3)
            if len(cells) >= need:
                return cells
    return cells[:need]


def _mm_to_px(
    x_mm: float, y_mm: float, *, origin: tuple[float, float], resolution: float
) -> tuple[float, float]:
    ox, oy = origin
    return (ox + (x_mm / 1000.0) / resolution, oy + (y_mm / 1000.0) / resolution)


def _parse_yugong_live(obj: dict[str, Any], *, map_id: str) -> ParsedMap:
    width = _as_int(obj.get("MapWidth") or obj.get("map_width"))
    height = _as_int(obj.get("MapHigh") or obj.get("MapHeight") or obj.get("map_height"))
    resolution = _as_float(obj.get("MapResolution") or obj.get("resolution"), 0.05)
    origin_raw = obj.get("MapOrigin") or [0, 0]
    origin = (_as_float(origin_raw[0]), _as_float(origin_raw[1])) if origin_raw else (0.0, 0.0)

    cells: list[int] | None = None
    map_data_b64 = obj.get("MapData")
    if isinstance(map_data_b64, str) and map_data_b64 and width and height:
        try:
            cells = _unpack_2bit_msb(_b64(map_data_b64), width, height)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Failed to decode MapData grid", exc_info=True)

    rooms: list[MapRoom] = []
    names: dict[int, str] = {}
    room_info = obj.get("room_info")
    if isinstance(room_info, dict):
        for key, val in room_info.items():
            rid = _as_int(key if not isinstance(val, dict) else val.get("room_id", key))
            if isinstance(val, dict):
                names[rid] = str(val.get("room_name") or val.get("name") or f"Room {rid}")
            elif isinstance(val, str) and val:
                names[rid] = val

    for item in obj.get("room_zone_info") or []:
        if not isinstance(item, dict):
            continue
        rid = _as_int(item.get("room_id"))
        xs = item.get("room_point_x") or []
        ys = item.get("room_point_y") or []
        verts: list[tuple[float, float]] = []
        if isinstance(xs, list) and isinstance(ys, list):
            for x, y in zip(xs, ys):
                verts.append(
                    _mm_to_px(_as_float(x), _as_float(y), origin=origin, resolution=resolution)
                )
        clean_order = _as_int(item.get("clean_order"), -1)
        # Single unsorted zone (clean_order -1) is often a blob, not a named room
        draw = not (rid == 0 and clean_order < 0 and len(obj.get("room_zone_info") or []) == 1)
        rooms.append(
            MapRoom(
                room_id=rid,
                name=names.get(rid, f"Room {rid}"),
                vertices=verts,
                clean_order=clean_order,
                draw=draw,
            )
        )

    path: list[tuple[float, float]] = []
    point_data = obj.get("PointData")
    if isinstance(point_data, str) and point_data:
        try:
            blob = _b64(point_data)
            for i in range(0, len(blob) - 3, 4):
                x_mm, y_mm = struct.unpack_from("<hh", blob, i)
                path.append(
                    _mm_to_px(float(x_mm), float(y_mm), origin=origin, resolution=resolution)
                )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Failed to decode PointData", exc_info=True)

    # Dock: MapOrigin is charger cell in this firmware family
    dock = (origin[0], origin[1])
    robot = path[-1] if path else None

    return ParsedMap(
        map_id=str(map_id or obj.get("map_id") or ""),
        width=width,
        height=height,
        resolution=resolution,
        dock=dock,
        robot=robot,
        rooms=rooms,
        cells=cells,
        path=path,
        raw=obj,
        pixel_space=True,
    )


def _parse_rooms_generic(obj: dict[str, Any]) -> list[MapRoom]:
    rooms: list[MapRoom] = []
    candidates = (
        obj.get("room_info")
        or obj.get("rooms")
        or obj.get("roomList")
        or obj.get("zone_list")
        or obj.get("room_zone_info")
        or []
    )
    if isinstance(candidates, dict):
        # id → name map
        for key, val in candidates.items():
            rid = _as_int(key)
            name = val if isinstance(val, str) else str(
                (val or {}).get("room_name") or (val or {}).get("name") or f"Room {rid}"
            )
            rooms.append(MapRoom(room_id=rid, name=name))
        return rooms
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
        verts: list[tuple[float, float]] = []
        xs = item.get("room_point_x")
        ys = item.get("room_point_y")
        if isinstance(xs, list) and isinstance(ys, list):
            for x, y in zip(xs, ys):
                verts.append((_as_float(x), _as_float(y)))
        else:
            for v in item.get("vertexList") or item.get("vertices") or []:
                if isinstance(v, dict):
                    verts.append((_as_float(v.get("x")), _as_float(v.get("y"))))
                elif isinstance(v, (list, tuple)) and len(v) >= 2:
                    verts.append((_as_float(v[0]), _as_float(v[1])))
        rooms.append(MapRoom(room_id=_as_int(rid), name=name, vertices=verts))
    return rooms


def parse_map_data(
    map_data: str | bytes | dict | None,
    *,
    map_id: str = "",
) -> ParsedMap | None:
    """Parse Grit map_data (live WSS zlib blob or HTTP payload) into a grid."""
    obj = _try_load_object(map_data)
    if obj is None:
        return None
    if isinstance(obj, list):
        obj = {"rooms": obj}
    if not isinstance(obj, dict):
        return None

    # YuGong live / multi-map JSON (ProtocolVersion + MapData)
    if (
        obj.get("ProtocolVersion")
        or obj.get("MapData")
        or obj.get("MapWidth")
        or obj.get("MapHigh")
    ):
        return _parse_yugong_live(obj, map_id=map_id)

    for nest in ("map", "map_info", "mapInfo", "data"):
        nested = obj.get(nest)
        if isinstance(nested, dict) and (
            "width" in nested or "MapData" in nested or "rooms" in nested
        ):
            obj = {**obj, **nested}

    if obj.get("MapData") or obj.get("MapWidth"):
        return _parse_yugong_live(obj, map_id=map_id)

    width = _as_int(obj.get("width") or obj.get("map_width"))
    height = _as_int(obj.get("height") or obj.get("map_height"))
    parsed = ParsedMap(
        map_id=str(map_id or obj.get("map_id") or obj.get("mapId") or ""),
        width=width,
        height=height,
        resolution=_as_float(obj.get("resolution"), 0.05),
        x_min=_as_float(obj.get("x_min") or obj.get("xmin")),
        y_min=_as_float(obj.get("y_min") or obj.get("ymin")),
        rooms=_parse_rooms_generic(obj),
        raw=obj,
    )
    raw_cells = obj.get("mapData") or obj.get("map_cells")
    if isinstance(raw_cells, list):
        parsed.cells = [int(x) for x in raw_cells]
    elif isinstance(raw_cells, str) and raw_cells:
        try:
            blob = _b64(raw_cells)
            if width and height and len(blob) >= (width * height + 3) // 4:
                parsed.cells = _unpack_2bit_msb(blob, width, height)
            else:
                parsed.cells = list(blob)
        except Exception:  # noqa: BLE001
            pass

    dock_x = obj.get("dockerPosX", obj.get("dock_x", obj.get("charger_x")))
    dock_y = obj.get("dockerPosY", obj.get("dock_y", obj.get("charger_y")))
    if dock_x is not None and dock_y is not None:
        parsed.dock = (_as_float(dock_x), _as_float(dock_y))

    if not parsed.rooms and not parsed.has_image:
        _LOGGER.debug(
            "map_data parsed but empty rooms/grid keys=%s", list(obj.keys())[:30]
        )
    return parsed


def _to_px(
    parsed: ParsedMap, x: float, y: float, scale: int
) -> tuple[int, int]:
    if parsed.pixel_space:
        return (int(x * scale), int(y * scale))
    res = parsed.resolution or 0.05
    return (
        int((x - parsed.x_min) / res * scale),
        int((y - parsed.y_min) / res * scale),
    )


def render_map_png(parsed: ParsedMap, *, scale: int = 3) -> bytes:
    """Render a top-down PNG of the occupancy grid."""
    try:
        from io import BytesIO

        from PIL import Image, ImageDraw  # type: ignore
    except ImportError:
        return _render_placeholder_png(parsed)

    if not parsed.has_image:
        return _render_placeholder_png(parsed)

    w, h = parsed.width, parsed.height
    img = Image.new("RGB", (w, h), (32, 34, 40))
    pixels = img.load()
    assert parsed.cells is not None
    for i, cell in enumerate(parsed.cells[: w * h]):
        x = i % w
        y = i // w
        c = int(cell)
        if c == CELL_FREE:
            color = (58, 72, 88)
        elif c == CELL_WALL:
            color = (210, 220, 230)
        elif c == CELL_UNKNOWN:
            color = (32, 34, 40)
        elif c == 2:
            color = (70, 110, 150)
        else:
            color = (
                40 + (c * 37) % 140,
                80 + (c * 53) % 120,
                120 + (c * 17) % 80,
            )
        pixels[x, y] = color

    if scale != 1:
        img = img.resize((w * scale, h * scale), Image.NEAREST)
    draw = ImageDraw.Draw(img)

    for room in parsed.rooms:
        if room.draw and len(room.vertices) >= 3:
            pts = [_to_px(parsed, vx, vy, scale) for vx, vy in room.vertices]
            draw.polygon(pts, outline=(255, 196, 72))

    if len(parsed.path) >= 2:
        pts = [_to_px(parsed, px, py, scale) for px, py in parsed.path]
        draw.line(pts, fill=(80, 180, 255), width=max(1, scale))

    if parsed.dock is not None:
        dx, dy = _to_px(parsed, parsed.dock[0], parsed.dock[1], scale)
        r = max(3, 3 * scale)
        draw.ellipse((dx - r, dy - r, dx + r, dy + r), fill=(255, 200, 40))

    if parsed.robot is not None:
        rx, ry = _to_px(parsed, parsed.robot[0], parsed.robot[1], scale)
        r = max(3, 2 * scale)
        draw.ellipse((rx - r, ry - r, rx + r, ry + r), fill=(80, 220, 120))
        draw.ellipse(
            (rx - r // 2, ry - r // 2, rx + r // 2, ry + r // 2), fill=(20, 40, 30)
        )

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _render_placeholder_png(parsed: ParsedMap | None) -> bytes:
    try:
        from io import BytesIO

        from PIL import Image, ImageDraw  # type: ignore

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
                "Waiting for live map via WSS…\n"
                "Robot must be online.",
                fill=(160, 170, 190),
            )
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        return base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
            "/x8AAwMCAO5XBZoAAAAASUVORK5CYII="
        )

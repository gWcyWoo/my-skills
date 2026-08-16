"""Self-contained Lanhu transport and source discovery for ICP extract."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import struct
import urllib.parse
import urllib.request
import zlib
from fractions import Fraction
from pathlib import Path
from typing import Any


class LanhuError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def read_cookie_from_dotenv(path: Path) -> str | None:
    if not path.is_file():
        return None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("LANHU_COOKIE="):
            continue
        value = line.split("=", 1)[1].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if value:
            return value
    return None


def resolve_cookie(cli_cookie: str | None) -> str | None:
    if cli_cookie and cli_cookie.strip():
        return cli_cookie.strip()
    environment_cookie = os.environ.get("LANHU_COOKIE", "").strip()
    if environment_cookie:
        return environment_cookie
    for path in (
        Path.home() / ".agents" / "mcp" / "lanhu-mcp" / ".env",
        Path.home() / ".claude" / "mcp" / "lanhu-mcp" / ".env",
    ):
        value = read_cookie_from_dotenv(path)
        if value:
            return value
    return None


def parse_lanhu_url(url: str) -> dict[str, str]:
    parsed = urllib.parse.urlparse(url)
    fragment = parsed.fragment or ""
    query = fragment.split("?", 1)[1] if "?" in fragment else parsed.query
    params = dict(urllib.parse.parse_qsl(query, keep_blank_values=False))
    image_id = params.get("image_id", "")
    project_id = params.get("pid") or params.get("project_id") or ""
    team_id = params.get("tid") or params.get("team_id") or ""
    if not image_id:
        raise LanhuError("invalid_design_url", "Lanhu URL is missing image_id")
    if not project_id:
        raise LanhuError("invalid_design_url", "Lanhu URL is missing pid/project_id")
    return {
        "image_id": image_id,
        "project_id": project_id,
        "team_id": team_id,
    }


class HttpClient:
    def __init__(self, cookie: str, fixture_manifest: Path | None = None) -> None:
        self.cookie = cookie
        self.fixture_manifest = fixture_manifest
        self.fixture: dict[str, Any] | None = None
        if fixture_manifest is not None:
            try:
                loaded = json.loads(fixture_manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise LanhuError("invalid_http_fixture", str(exc)) from exc
            if not isinstance(loaded, dict) or loaded.get("schema") != "icp.extract.http-fixture.v1":
                raise LanhuError("invalid_http_fixture", "unsupported HTTP fixture schema")
            self.fixture = loaded

    def get(self, url: str, referer: str = "https://lanhuapp.com/", timeout: int = 30) -> bytes:
        if self.fixture is not None:
            raw, content_encoding = self._fixture_get(url)
        else:
            raw, content_encoding = self._network_get(url, referer, timeout)
        if content_encoding.lower() == "gzip" or raw[:2] == b"\x1f\x8b":
            try:
                return gzip.decompress(raw)
            except OSError as exc:
                raise LanhuError("invalid_gzip", f"cannot decompress {url}: {exc}") from exc
        return raw

    def _network_get(self, url: str, referer: str, timeout: int) -> tuple[bytes, str]:
        request = urllib.request.Request(
            url,
            headers={
                "Cookie": self.cookie,
                "Referer": referer,
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Accept-Encoding": "gzip",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read(), response.headers.get("Content-Encoding", "")
        except Exception as exc:
            raise LanhuError("http_error", f"GET {url} failed: {exc}") from exc

    def _fixture_get(self, url: str) -> tuple[bytes, str]:
        assert self.fixture is not None and self.fixture_manifest is not None
        path = urllib.parse.urlparse(url).path
        responses = self.fixture.get("responses")
        entry = responses.get(path) if isinstance(responses, dict) else None
        if not isinstance(entry, dict):
            raise LanhuError("http_error", f"fixture has no response for {path}")
        status = entry.get("status", 200)
        if status != 200:
            raise LanhuError("http_error", f"fixture GET {path} returned {status}")
        if "json" in entry:
            raw = json.dumps(entry["json"]).encode("utf-8")
        else:
            relative = entry.get("file")
            if not isinstance(relative, str) or not relative:
                raise LanhuError("invalid_http_fixture", f"fixture response {path} has no body")
            target = (self.fixture_manifest.parent / relative).resolve()
            try:
                target.relative_to(self.fixture_manifest.parent.resolve())
            except ValueError as exc:
                raise LanhuError("invalid_http_fixture", f"fixture file escapes root: {relative}") from exc
            try:
                raw = target.read_bytes()
            except OSError as exc:
                raise LanhuError("invalid_http_fixture", str(exc)) from exc
        encoding = entry.get("content_encoding", "")
        return raw, encoding if isinstance(encoding, str) else ""


def fetch_design_metadata(
    client: HttpClient,
    identity: dict[str, str],
    api_base: str,
) -> dict[str, str]:
    query = urllib.parse.urlencode(
        {
            "dds_status": "1",
            "image_id": identity["image_id"],
            "team_id": identity["team_id"],
            "project_id": identity["project_id"],
        }
    )
    api_url = f"{api_base.rstrip('/')}/api/project/image?{query}"
    try:
        data = json.loads(client.get(api_url))
    except json.JSONDecodeError as exc:
        raise LanhuError("invalid_metadata", f"Lanhu metadata is not JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("code") != "00000":
        raise LanhuError(
            "metadata_failed",
            f"project/image failed: code={getattr(data, 'get', lambda _key: None)('code')}",
        )
    result = data.get("result")
    if not isinstance(result, dict):
        raise LanhuError("invalid_metadata", "project/image result is missing")
    versions = result.get("versions")
    if not isinstance(versions, list) or not versions or not isinstance(versions[0], dict):
        raise LanhuError("invalid_metadata", "project/image returned no versions")
    latest = versions[0]
    values = {
        "design_id": result.get("id"),
        "design_name": result.get("name") or "untitled",
        "version_id": latest.get("id"),
        "json_url": latest.get("json_url"),
        "cover_url": result.get("url") or latest.get("url"),
        "metadata_url": api_url,
    }
    for key, value in values.items():
        if not isinstance(value, str) or not value:
            raise LanhuError("invalid_metadata", f"project/image is missing {key}")
    return values


def collect_export_assets(figma_json: dict[str, Any]) -> list[dict[str, Any]]:
    artboard = figma_json.get("artboard")
    if not isinstance(artboard, dict):
        raise LanhuError("invalid_figma_json", "Figma JSON has no artboard")
    collected: list[dict[str, Any]] = []

    def walk(node: dict[str, Any], parent_path: str) -> None:
        name = str(node.get("name") or "")
        layer_path = f"{parent_path}/{name}" if parent_path else name
        image = node.get("image")
        if node.get("hasExportImage"):
            if not isinstance(image, dict):
                raise LanhuError(
                    "asset_metadata_missing",
                    f"exportable layer has no image metadata: {layer_path}",
                )
            found_url = False
            for format_name, key in (("png", "imageUrl"), ("svg", "svgUrl")):
                url = image.get(key)
                if isinstance(url, str) and url:
                    found_url = True
                    collected.append(
                        {
                            "url": url,
                            "format": format_name,
                            "source_field": f"image.{key}",
                            "layer_id": node.get("id"),
                            "layer_name": name,
                            "layer_path": layer_path,
                        }
                    )
            if not found_url:
                raise LanhuError(
                    "asset_metadata_missing",
                    f"exportable layer has no downloadable URL: {layer_path}",
                )
        children = node.get("layers") or []
        if not isinstance(children, list):
            raise LanhuError("invalid_figma_json", f"layers is invalid at {layer_path}")
        for child in children:
            if not isinstance(child, dict):
                raise LanhuError("invalid_figma_json", f"non-object layer at {layer_path}")
            walk(child, layer_path)

    walk(artboard, "")
    return collected


def png_size(raw: bytes) -> dict[str, int]:
    if len(raw) < 24 or raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise LanhuError("invalid_reference", "Lanhu cover is not a PNG")
    offset = 8
    width: int | None = None
    height: int | None = None
    chunk_index = 0
    while offset < len(raw):
        if offset + 12 > len(raw):
            raise LanhuError("invalid_reference", "Lanhu cover has a truncated PNG chunk")
        length = struct.unpack(">I", raw[offset : offset + 4])[0]
        chunk_type = raw[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        crc_end = data_end + 4
        if crc_end > len(raw):
            raise LanhuError("invalid_reference", "Lanhu cover has a truncated PNG chunk")
        chunk_data = raw[data_start:data_end]
        expected_crc = struct.unpack(">I", raw[data_end:crc_end])[0]
        actual_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            raise LanhuError("invalid_reference", "Lanhu cover PNG CRC is invalid")
        if chunk_index == 0:
            if chunk_type != b"IHDR" or length != 13:
                raise LanhuError("invalid_reference", "Lanhu cover PNG IHDR is invalid")
            width, height = struct.unpack(">II", chunk_data[:8])
            if width <= 0 or height <= 0:
                raise LanhuError("invalid_reference", "Lanhu cover PNG size is invalid")
        elif chunk_type == b"IHDR":
            raise LanhuError("invalid_reference", "Lanhu cover PNG repeats IHDR")
        offset = crc_end
        chunk_index += 1
        if chunk_type == b"IEND":
            if length != 0 or offset != len(raw):
                raise LanhuError("invalid_reference", "Lanhu cover PNG IEND is invalid")
            assert width is not None and height is not None
            return {"width": width, "height": height}
    raise LanhuError("invalid_reference", "Lanhu cover PNG has no IEND")


def artboard_size(figma_json: dict[str, Any]) -> dict[str, int | float]:
    artboard = figma_json.get("artboard")
    frame = artboard.get("frame") if isinstance(artboard, dict) else None
    if not isinstance(frame, dict):
        raise LanhuError("invalid_figma_json", "artboard frame is missing")
    width = frame.get("width")
    height = frame.get("height")
    if not isinstance(width, (int, float)) or isinstance(width, bool) or width <= 0:
        raise LanhuError("invalid_figma_json", "artboard width is invalid")
    if not isinstance(height, (int, float)) or isinstance(height, bool) or height <= 0:
        raise LanhuError("invalid_figma_json", "artboard height is invalid")
    return {"width": width, "height": height}


def reference_logical_scale(
    reference_size: dict[str, int], artboard: dict[str, int | float]
) -> str:
    width_scale = Fraction(reference_size["width"], 1) / Fraction(
        str(artboard["width"])
    )
    height_scale = Fraction(reference_size["height"], 1) / Fraction(
        str(artboard["height"])
    )
    if width_scale != height_scale:
        raise LanhuError(
            "reference_size_mismatch",
            f"cover={reference_size} artboard={artboard} is not a uniform full-artboard scale",
        )
    return str(width_scale)


def asset_file_name(url: str, used: dict[str, str]) -> str:
    base = Path(urllib.parse.urlparse(url).path).name
    for prefix in ("FigmaSlicePNG", "FigmaSliceSVG"):
        if base.startswith(prefix):
            base = base[len(prefix) :]
    base = base.replace("/", "-").replace("\\", "-").replace(":", "-") or "asset"
    if base in used and used[base] != url:
        path = Path(base)
        base = f"{path.stem}-{sha256_bytes(url.encode('utf-8'))[:12]}{path.suffix}"
    used[base] = url
    return base

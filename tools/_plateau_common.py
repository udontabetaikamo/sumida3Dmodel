"""共通ヘルパー: 名前空間非依存の CityGML パース、座標変換、bbox判定。
build_*_json.py で共有する。"""

import math
from xml.etree import ElementTree as ET


def localname(tag):
    return tag.split('}', 1)[1] if '}' in tag else tag


def iter_local(root, name):
    for el in root.iter():
        if localname(el.tag) == name:
            yield el


def find_local(elem, name):
    for el in elem.iter():
        if localname(el.tag) == name:
            return el
    return None


def lonlat_to_local_meters(lon, lat, ref_lon, ref_lat):
    cos_lat = math.cos(math.radians(ref_lat))
    x = (lon - ref_lon) * 111320.0 * cos_lat
    y = (lat - ref_lat) * 110540.0
    return x, y


def parse_pos_list(text):
    """gml:posList のテキスト → [(lon, lat, [elev?]), ...]
    PLATEAU 2025 は緯度経度の順 (lat, lon, h)。最初の値で自動判定。"""
    vals = text.replace('\n', ' ').replace('\t', ' ').split()
    if len(vals) < 2:
        return []
    try:
        first = float(vals[0])
    except ValueError:
        return []
    lat_first = 30.0 < first < 50.0  # 日本の緯度範囲
    stride = 3 if len(vals) % 3 == 0 else 2
    pts = []
    for i in range(0, len(vals) - stride + 1, stride):
        try:
            a = float(vals[i])
            b = float(vals[i + 1])
            z = float(vals[i + 2]) if stride == 3 else None
        except (ValueError, IndexError):
            continue
        lat, lon = (a, b) if lat_first else (b, a)
        if z is None:
            pts.append((lon, lat))
        else:
            pts.append((lon, lat, z))
    return pts


def bbox_from_buildings_json(bd, margin_m=200.0):
    range_m = bd['range_m']
    half_w = range_m[0] / 2 + margin_m
    half_h = range_m[1] / 2 + margin_m
    return (-half_w, -half_h, half_w, half_h)


def in_bbox(pt_xy, bbox_m):
    return bbox_m[0] <= pt_xy[0] <= bbox_m[2] and bbox_m[1] <= pt_xy[1] <= bbox_m[3]


def collect_polygons(elem):
    """要素配下の Polygon を [(exterior_lonlat, [hole1_lonlat, ...]), ...] で返す。"""
    polys = []
    for poly in elem.iter():
        if localname(poly.tag) != 'Polygon':
            continue
        ext = None
        holes = []
        for sub in poly:
            ln = localname(sub.tag)
            if ln == 'exterior':
                pl = find_local(sub, 'posList')
                if pl is not None and pl.text:
                    ext = parse_pos_list(pl.text)
            elif ln == 'interior':
                pl = find_local(sub, 'posList')
                if pl is not None and pl.text:
                    holes.append(parse_pos_list(pl.text))
        if ext and len(ext) >= 3:
            polys.append((ext, holes))
    return polys


def polygon_centroid_z(poly_pts):
    """Polygon (xyz) の Z 平均値。Z 無ければ None。"""
    zs = [p[2] for p in poly_pts if len(p) >= 3]
    return sum(zs) / len(zs) if zs else None


def polygon_to_xy(poly_pts, ref_lon, ref_lat):
    """[(lon,lat,[z]),...] → [[x_m, y_m], ...]"""
    out = []
    for p in poly_pts:
        x, y = lonlat_to_local_meters(p[0], p[1], ref_lon, ref_lat)
        out.append([round(x, 2), round(y, 2)])
    return out


def parse_xml(path):
    """XML をパース。エラー時は None を返す。"""
    try:
        return ET.parse(path).getroot()
    except ET.ParseError as e:
        print(f"  [WARN] parse error: {path}: {e}")
        return None

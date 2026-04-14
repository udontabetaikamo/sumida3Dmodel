#!/usr/bin/env python3
"""
PLATEAU tran (Transportation) CityGML → roads_<area>.json 変換スクリプト

CityGML 2.0 / 3.0 両対応 (名前空間に依存しないローカル名マッチング)。

使い方:
    python3 tools/build_roads_json.py \
        --tran-dir "/Users/udon/Desktop/創作/0413_墨田区PLATEAU/13107_sumida-ku_pref_2025_citygml_1_op/udx/tran" \
        --buildings-json buildings_634635.json \
        --area 634635 \
        --output roads_634635.json

buildings_<area>.json から ref_lat / ref_lon / scale / range_m を読み込み、
同じ座標系で道路ポリラインを抽出して JSON として保存します。

出力フォーマット:
  {
    "type": "roads",
    "ref_lat": ..., "ref_lon": ..., "scale": ...,
    "range_m": [w, h],
    "roads": [
      {
        "line": [[x_m, y_m], ...],   # 中心線 or 面の境界(buildings_*.json と同じローカル座標, m)
        "a": {
          "width": 6.5,
          "class": "4",
          "function": "1000",
          "emergency": false,
          "traffic_24h": null
        }
      }, ...
    ]
  }
"""

import argparse
import glob
import json
import math
import os
import sys
from xml.etree import ElementTree as ET


def localname(tag):
    """XMLタグから名前空間を取り除く。 '{http://...}Road' → 'Road'"""
    if '}' in tag:
        return tag.split('}', 1)[1]
    return tag


def iter_local(root, name):
    """指定 local name にマッチする要素を再帰的に列挙(名前空間不問)。"""
    for el in root.iter():
        if localname(el.tag) == name:
            yield el


def find_local(elem, name):
    for el in elem.iter():
        if localname(el.tag) == name:
            return el
    return None


def find_local_direct_child(elem, name):
    for child in elem:
        if localname(child.tag) == name:
            return child
    return None


def lonlat_to_local_meters(lon, lat, ref_lon, ref_lat):
    cos_lat = math.cos(math.radians(ref_lat))
    x = (lon - ref_lon) * 111320.0 * cos_lat
    y = (lat - ref_lat) * 110540.0
    return x, y


def parse_pos_list(text):
    """gml:posList のテキストを (lon, lat) タプル列に変換。
    PLATEAU は (lat lon h) と (lon lat h) のどちらも実例がある。
    PLATEAU CityGML 2025 は緯度経度の順 (CRS:JGD2011 緯度経度) なので
    最初の2つで判定する。 35.x は緯度、139.x は経度。"""
    vals = text.replace('\n', ' ').replace('\t', ' ').split()
    if len(vals) < 2:
        return []
    # 最初の値が 35付近 → 緯度始まり、139付近 → 経度始まり
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
        except ValueError:
            continue
        if lat_first:
            lat, lon = a, b
        else:
            lon, lat = a, b
        pts.append((lon, lat))
    return pts


def collect_geometries(road_elem):
    """Road 要素配下のすべての LineString と Polygon を列挙して
    [(kind, [(lon,lat),...]), ...] 形式で返す。kind は 'line' or 'poly'."""
    geoms = []
    seen_ids = set()

    for el in road_elem.iter():
        ln = localname(el.tag)
        if ln == 'LineString':
            # posList または pos の連続
            pl = find_local(el, 'posList')
            if pl is not None and pl.text:
                pts = parse_pos_list(pl.text)
                if len(pts) >= 2:
                    geoms.append(('line', pts))
            else:
                pos_pts = []
                for pos in iter_local(el, 'pos'):
                    if pos.text:
                        p = parse_pos_list(pos.text)
                        if p:
                            pos_pts.extend(p)
                if len(pos_pts) >= 2:
                    geoms.append(('line', pos_pts))
        elif ln == 'LineStringSegment':  # Curve/segments/LineStringSegment (CityGML 3.0)
            pl = find_local(el, 'posList')
            if pl is not None and pl.text:
                pts = parse_pos_list(pl.text)
                if len(pts) >= 2:
                    geoms.append(('line', pts))
        elif ln == 'Polygon':
            ext = None
            for sub in el.iter():
                if localname(sub.tag) == 'exterior':
                    ext = sub
                    break
            if ext is not None:
                pl = find_local(ext, 'posList')
                if pl is not None and pl.text:
                    pts = parse_pos_list(pl.text)
                    if len(pts) >= 3:
                        geoms.append(('poly', pts))

    return geoms


def extract_attributes(road_elem):
    """Road 要素から属性 (function, class, width) を抽出。"""
    function_code = None
    cls_code = None
    width_m = None

    # tran:function / tran:class
    for el in road_elem:
        ln = localname(el.tag)
        if ln == 'function' and el.text:
            function_code = el.text.strip()
        elif ln == 'class' and el.text:
            cls_code = el.text.strip()

    # gen:measureAttribute / stringAttribute / doubleAttribute (PLATEAU属性)
    for el in road_elem.iter():
        ln = localname(el.tag)
        if ln in ('measureAttribute', 'stringAttribute', 'doubleAttribute', 'genericAttribute'):
            name = el.get('name', '')
            if name in ('width', '幅員', 'roadWidth', '幅員区分', 'tran:width'):
                v = find_local(el, 'value')
                if v is not None and v.text:
                    try:
                        width_m = float(v.text.strip())
                    except ValueError:
                        # 区分コード (e.g. "1":3m未満, "2":3-5.5m) かもしれない
                        code = v.text.strip()
                        # 区分コードは値として保持しないが将来用にコメント
                        pass

    return function_code, cls_code, width_m


def polygon_area_lonlat(pts, ref_lat):
    """経緯度ポリゴンの面積を平方メートルで概算。"""
    cos_lat = math.cos(math.radians(ref_lat))
    s = 0.0
    n = len(pts)
    for i in range(n):
        x1 = pts[i][0] * 111320.0 * cos_lat
        y1 = pts[i][1] * 110540.0
        x2 = pts[(i + 1) % n][0] * 111320.0 * cos_lat
        y2 = pts[(i + 1) % n][1] * 110540.0
        s += (x1 * y2 - x2 * y1)
    return abs(s) / 2.0


def polygon_to_centerline_and_width(pts, ref_lat, ref_lon):
    """ポリゴンの長軸を中心線、面積/長軸長 を幅とみなして返す。"""
    if len(pts) < 3:
        return None, None
    sample = pts if len(pts) <= 200 else pts[:: max(1, len(pts) // 200)]
    cos_lat = math.cos(math.radians(ref_lat))
    # local meter coords for distance calc
    metric = [((p[0] - ref_lon) * 111320.0 * cos_lat,
               (p[1] - ref_lat) * 110540.0) for p in sample]
    max_d2 = 0.0
    a_idx, b_idx = 0, 1
    for i in range(len(metric)):
        for j in range(i + 1, len(metric)):
            dx = metric[i][0] - metric[j][0]
            dy = metric[i][1] - metric[j][1]
            d2 = dx * dx + dy * dy
            if d2 > max_d2:
                max_d2 = d2
                a_idx, b_idx = i, j
    long_len = math.sqrt(max_d2)
    if long_len < 0.5:
        return None, None
    area = polygon_area_lonlat(pts, ref_lat)
    width_est = area / long_len
    width_est = max(2.0, min(width_est, 30.0))
    return [sample[a_idx], sample[b_idx]], width_est


def in_bbox(pt_xy, bbox_m):
    return bbox_m[0] <= pt_xy[0] <= bbox_m[2] and bbox_m[1] <= pt_xy[1] <= bbox_m[3]


def extract_roads_from_file(xml_path, ref_lon, ref_lat, bbox_m, stats):
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as e:
        print(f"  [WARN] parse error: {xml_path}: {e}", file=sys.stderr)
        return []

    root = tree.getroot()
    roads = []

    road_elems = list(iter_local(root, 'Road'))
    stats['road_elems'] += len(road_elems)

    for road_elem in road_elems:
        function_code, cls_code, width_m = extract_attributes(road_elem)
        geoms = collect_geometries(road_elem)
        if not geoms:
            stats['no_geom'] += 1
            continue

        # 線優先・無ければ面の長軸近似
        line_geoms = [g for g in geoms if g[0] == 'line']
        poly_geoms = [g for g in geoms if g[0] == 'poly']

        lines_to_emit = []  # list of (line_lonlat, width_override)
        if line_geoms:
            for _, pts in line_geoms:
                lines_to_emit.append((pts, width_m))
        elif poly_geoms:
            # 面の長軸を1本のラインに圧縮(全ポリゴン結合)
            all_pts = [p for _, pts in poly_geoms for p in pts]
            line, est_w = polygon_to_centerline_and_width(all_pts, ref_lat, ref_lon)
            if line:
                w_use = width_m if width_m is not None else est_w
                lines_to_emit.append((line, w_use))

        for line_lonlat, w_use in lines_to_emit:
            line_xy = []
            for lon, lat in line_lonlat:
                x, y = lonlat_to_local_meters(lon, lat, ref_lon, ref_lat)
                line_xy.append([round(x, 2), round(y, 2)])

            if not any(in_bbox(p, bbox_m) for p in line_xy):
                stats['out_of_bbox'] += 1
                continue

            roads.append({
                'line': line_xy,
                'a': {
                    'width': round(w_use if w_use is not None else 4.0, 2),
                    'class': cls_code,
                    'function': function_code,
                    'emergency': False,
                    'traffic_24h': None,
                }
            })

    return roads


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tran-dir', required=True)
    ap.add_argument('--buildings-json', required=True)
    ap.add_argument('--area', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--bbox-margin', type=float, default=200.0)
    ap.add_argument('--all-tiles', action='store_true',
                    help='area コードに関係なく tran ディレクトリ内の全ファイルを処理(既定で有効)')
    args = ap.parse_args()

    with open(args.buildings_json) as f:
        bd = json.load(f)
    ref_lon = bd['ref_lon']
    ref_lat = bd['ref_lat']
    scale = bd['scale']
    range_m = bd['range_m']

    half_w = range_m[0] / 2 + args.bbox_margin
    half_h = range_m[1] / 2 + args.bbox_margin
    bbox_m = (-half_w, -half_h, half_w, half_h)
    print(f"buildings ref: lat={ref_lat}, lon={ref_lon}")
    print(f"bbox (m, local): x[{bbox_m[0]:.0f}, {bbox_m[2]:.0f}] y[{bbox_m[1]:.0f}, {bbox_m[3]:.0f}]")

    # 全ての tran*.gml を対象 (隣接タイルの道路もbboxで自動フィルタ)
    files = sorted(glob.glob(os.path.join(args.tran_dir, '*tran*.gml'))
                   + glob.glob(os.path.join(args.tran_dir, '*tran*.xml')))
    if not files:
        files = sorted(glob.glob(os.path.join(args.tran_dir, '*.gml')))
    if not files:
        print(f"ERROR: no tran files found under {args.tran_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"\nProcessing {len(files)} tran file(s)...")
    all_roads = []
    stats = {'road_elems': 0, 'no_geom': 0, 'out_of_bbox': 0}
    for fp in files:
        before = len(all_roads)
        all_roads.extend(extract_roads_from_file(fp, ref_lon, ref_lat, bbox_m, stats))
        added = len(all_roads) - before
        print(f"  {os.path.basename(fp)}: +{added} segments")

    print(f"\nDiagnostics:")
    print(f"  Road elements found:   {stats['road_elems']}")
    print(f"  Roads with no geom:    {stats['no_geom']}")
    print(f"  Filtered by bbox:      {stats['out_of_bbox']}")
    print(f"  Roads emitted:         {len(all_roads)}")

    out = {
        'type': 'roads',
        'ref_lat': ref_lat,
        'ref_lon': ref_lon,
        'scale': scale,
        'range_m': range_m,
        'roads': all_roads,
    }
    with open(args.output, 'w') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))

    print(f"\nWrote {len(all_roads):,} road segments to {args.output}")
    if len(all_roads) == 0:
        print("\n!!! 0 segments. 1ファイルだけ XML 構造を見せてもらえれば、解析を調整します。")
        print("    head -200 \"" + files[0] + "\"")


if __name__ == '__main__':
    main()

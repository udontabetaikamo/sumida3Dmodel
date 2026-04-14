#!/usr/bin/env python3
"""
PLATEAU tran (Transportation) CityGML → roads_<area>.json 変換スクリプト

使い方:
    python3 tools/build_roads_json.py \
        --tran-dir "/Users/udon/Desktop/創作/0413_墨田区PLATEAU/13107_sumida-ku_pref_2025_citygml_1_op/udx/tran" \
        --buildings-json buildings_634635.json \
        --area 634635 \
        --output roads_634635.json

buildings_<area>.json から ref_lat / ref_lon / scale / range_m を読み込み、
同じ座標系で道路ポリラインを抽出して JSON として保存します。

対応データ:
  - PLATEAU CityGML 3.x / 2.x の tran モジュール
  - LOD1MultiSurface (面) または LOD1Network (中心線) を自動判定
  - 幅員: gen:measureAttribute (name="width" or "幅員") があれば使用、
          無ければ面ジオメトリから推定、それも無ければ既定値 4m

出力フォーマット:
  {
    "type": "roads",
    "ref_lat": ..., "ref_lon": ..., "scale": ...,
    "range_m": [w, h],
    "roads": [
      {
        "line": [[x_m, y_m], ...],   # 中心線(buildings_*.jsonと同じローカル座標, m)
        "a": {
          "width": 6.5,              # 幅員(m)
          "class": "4",              # 1:高速 2:国道 3:都道 4:区道 9:その他
          "function": "1000",        # PLATEAU tran:function コード
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

NS = {
    'core':  'http://www.opengis.net/citygml/2.0',
    'tran':  'http://www.opengis.net/citygml/transportation/2.0',
    'gml':   'http://www.opengis.net/gml',
    'gen':   'http://www.opengis.net/citygml/generics/2.0',
    'xlink': 'http://www.w3.org/1999/xlink',
}

# 平面直角座標系第IX系 (東京) origin: 36N 139.83333E
# PLATEAU CityGML は CRS:84 (経緯度) で配布されるので緯度経度 → ローカルメートルへ変換
def lonlat_to_local_meters(lon, lat, ref_lon, ref_lat):
    cos_lat = math.cos(math.radians(ref_lat))
    x = (lon - ref_lon) * 111320.0 * cos_lat
    y = (lat - ref_lat) * 110540.0
    return x, y


def parse_pos_list(text):
    """gml:posList のテキストから座標タプル列を返す。CityGML は経度 緯度 [標高] の順。"""
    vals = text.replace('\n', ' ').split()
    if not vals:
        return []
    # 3D (lon lat h) か 2D (lon lat) を判定
    # PLATEAUは基本3D
    pts = []
    if len(vals) % 3 == 0:
        for i in range(0, len(vals), 3):
            pts.append((float(vals[i]), float(vals[i + 1])))
    elif len(vals) % 2 == 0:
        for i in range(0, len(vals), 2):
            pts.append((float(vals[i]), float(vals[i + 1])))
    return pts


def extract_roads_from_file(xml_path, ref_lon, ref_lat, bbox_m):
    """1つの tran XML ファイルから道路ジオメトリ・属性を抽出してリストで返す。"""
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as e:
        print(f"  [WARN] parse error: {xml_path}: {e}", file=sys.stderr)
        return []

    root = tree.getroot()
    roads = []

    for road_elem in root.iter('{%s}Road' % NS['tran']):
        # 属性
        function_code = None
        fn = road_elem.find('tran:function', NS)
        if fn is not None and fn.text:
            function_code = fn.text.strip()

        # クラス (tran:class) - 国土数値情報の道路種別と一致しないが格納
        cls_code = None
        cl = road_elem.find('tran:class', NS)
        if cl is not None and cl.text:
            cls_code = cl.text.strip()

        # gen:measureAttribute から幅員
        width_m = None
        for ga in road_elem.iter('{%s}measureAttribute' % NS['gen']):
            name = ga.get('name', '')
            if name in ('width', '幅員', 'roadWidth'):
                v = ga.find('gen:value', NS)
                if v is not None and v.text:
                    try:
                        width_m = float(v.text.strip())
                    except ValueError:
                        pass

        # 中心線ジオメトリ抽出 (LOD1Network → MultiCurve / Curve / LineString)
        lines = []
        for ls in road_elem.iter('{%s}LineString' % NS['gml']):
            pl = ls.find('gml:posList', NS)
            if pl is not None and pl.text:
                pts = parse_pos_list(pl.text)
                if len(pts) >= 2:
                    lines.append(pts)

        # MultiSurface/CompositeSurface しか無い場合 → 面の長軸を中心線として近似
        if not lines:
            polys = []
            for surf in road_elem.iter('{%s}Polygon' % NS['gml']):
                ext = surf.find('.//gml:exterior//gml:posList', NS)
                if ext is not None and ext.text:
                    pts = parse_pos_list(ext.text)
                    if len(pts) >= 3:
                        polys.append(pts)
            if polys:
                line, est_w = polygons_to_centerline(polys)
                if line:
                    lines.append(line)
                    if width_m is None:
                        width_m = est_w

        if not lines:
            continue

        if width_m is None:
            width_m = 4.0  # 既定値

        for line_lonlat in lines:
            line_xy = []
            for lon, lat in line_lonlat:
                x, y = lonlat_to_local_meters(lon, lat, ref_lon, ref_lat)
                line_xy.append([round(x, 2), round(y, 2)])

            # bbox外の道路は除外
            if not any(in_bbox(p, bbox_m) for p in line_xy):
                continue

            roads.append({
                'line': line_xy,
                'a': {
                    'width': round(width_m, 2),
                    'class': cls_code,
                    'function': function_code,
                    'emergency': False,
                    'traffic_24h': None,
                }
            })

    return roads


def polygons_to_centerline(polys):
    """道路ポリゴン群を1本の長軸ライン+幅推定値に圧縮(粗い近似)。"""
    pts = [p for poly in polys for p in poly]
    if len(pts) < 2:
        return None, None
    # 最遠点ペアを長軸とみなす
    max_d = 0
    a, b = pts[0], pts[1]
    # サンプリング (大きい時)
    sample = pts if len(pts) <= 200 else pts[:: len(pts) // 200]
    for i in range(len(sample)):
        for j in range(i + 1, len(sample)):
            d = (sample[i][0] - sample[j][0]) ** 2 + (sample[i][1] - sample[j][1]) ** 2
            if d > max_d:
                max_d = d
                a, b = sample[i], sample[j]
    # 幅は短軸を概算: ポリゴン面積 / 長軸長
    long_len = math.sqrt(max_d) * 111320.0  # 経度1度≒111km(粗い)
    area_total = 0.0
    for poly in polys:
        area_total += abs(polygon_area(poly))
    width_est = (area_total * (111320.0 ** 2)) / max(long_len, 1.0)
    width_est = max(2.0, min(width_est, 25.0))
    return [a, b], width_est


def polygon_area(pts):
    s = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += (x1 * y2 - x2 * y1)
    return s / 2.0


def in_bbox(pt, bbox_m):
    x, y = pt
    return bbox_m[0] <= x <= bbox_m[2] and bbox_m[1] <= y <= bbox_m[3]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tran-dir', required=True, help='PLATEAU udx/tran ディレクトリ')
    ap.add_argument('--buildings-json', required=True,
                    help='対応する buildings_<area>.json (座標基準を引き継ぐ)')
    ap.add_argument('--area', required=True, help='メッシュコード末尾(例: 634635)')
    ap.add_argument('--output', required=True, help='出力ファイル(roads_<area>.json)')
    ap.add_argument('--bbox-margin', type=float, default=200.0,
                    help='建物bboxの外側マージン(m). デフォルト 200m')
    args = ap.parse_args()

    with open(args.buildings_json) as f:
        bd = json.load(f)
    ref_lon = bd['ref_lon']
    ref_lat = bd['ref_lat']
    scale = bd['scale']
    range_m = bd['range_m']

    # bboxは建物データの範囲(buildings の fp は ref を中心にした m 座標)
    half_w = range_m[0] / 2 + args.bbox_margin
    half_h = range_m[1] / 2 + args.bbox_margin
    bbox_m = (-half_w, -half_h, half_w, half_h)

    # tran ディレクトリ内から area コードを含むファイルを優先、無ければ全件処理
    pattern_specific = os.path.join(args.tran_dir, f'*{args.area}*tran*.gml')
    pattern_all = os.path.join(args.tran_dir, '*tran*.gml')
    files = glob.glob(pattern_specific) or glob.glob(pattern_all)
    if not files:
        # フォールバック (拡張子 .xml 等)
        files = (glob.glob(os.path.join(args.tran_dir, f'*{args.area}*'))
                 or glob.glob(os.path.join(args.tran_dir, '*.gml'))
                 or glob.glob(os.path.join(args.tran_dir, '*.xml')))

    if not files:
        print(f"ERROR: no tran files found under {args.tran_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Processing {len(files)} tran file(s)...")
    all_roads = []
    for fp in sorted(files):
        print(f"  - {os.path.basename(fp)}")
        all_roads.extend(extract_roads_from_file(fp, ref_lon, ref_lat, bbox_m))

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
    print(f"  ref_lat={ref_lat}, ref_lon={ref_lon}, scale={scale}")


if __name__ == '__main__':
    main()

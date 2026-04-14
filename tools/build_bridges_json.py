#!/usr/bin/env python3
"""
PLATEAU brid (Bridge) CityGML → bridges_<area>.json 変換スクリプト

使い方:
    python3 tools/build_bridges_json.py \
        --brid-dir "/Users/udon/Desktop/創作/0413_墨田区PLATEAU/13107_sumida-ku_pref_2025_citygml_1_op/udx/brid" \
        --buildings-json buildings_634635.json \
        --area 634635 \
        --output bridges_634635.json

各 Bridge の lod1Solid から「最も低い面」をフットプリントとして抽出します。
出力フォーマット: { type: 'bridges', items: [{ fp: [...], a: { name } }, ...] }
"""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _plateau_common import (
    bbox_from_buildings_json, collect_polygons, in_bbox, iter_local,
    localname, parse_xml, polygon_to_xy,
)


def extract_bridges(root, ref_lon, ref_lat, bbox_m, stats):
    """各 Bridge 要素の中の「水平で十分大きい polygon」を 1 つずつアイテム化。
    1つの Bridge が複数の橋(の床版)を含むケースに対応。"""
    out = []
    bridges = list(iter_local(root, 'Bridge'))
    stats['bridge_elems'] += len(bridges)

    for bi, bridge in enumerate(bridges):
        name = None
        for el in bridge:
            if localname(el.tag) == 'name' and el.text:
                name = el.text.strip()
                break

        polys = collect_polygons(bridge)
        if not polys:
            stats['no_geom'] += 1
            continue

        polys_with_xy = []
        all_xy_pts = []
        for ext, _holes in polys:
            xy = polygon_to_xy(ext, ref_lon, ref_lat)
            polys_with_xy.append((xy, ext))
            all_xy_pts.extend(xy)

        # 全 Bridge の位置を出力
        if all_xy_pts:
            xs = [p[0] for p in all_xy_pts]
            ys = [p[1] for p in all_xy_pts]
            cx = (min(xs) + max(xs)) / 2
            cy = (min(ys) + max(ys)) / 2
            in_box = bbox_m[0] <= cx <= bbox_m[2] and bbox_m[1] <= cy <= bbox_m[3]
            mark = '✓' if in_box else '✗'
            print(f"  {mark} bridge#{bi}: center=({cx:.0f}, {cy:.0f}), polys={len(polys)}, name={name}")

        # 各ポリゴンを個別評価: 水平 (Z分散小) かつ十分大きい (>20m²) ものをアイテム化
        emitted = 0
        for xy, ext in polys_with_xy:
            if len(xy) < 3:
                continue
            area = abs(_polygon_area_xy(xy))
            if area < 20.0:
                continue
            zs = [p[2] for p in ext if len(p) >= 3]
            z_var = (max(zs) - min(zs)) if zs else 0
            if z_var > 1.5:  # 高さ差 > 1.5m → 側面/斜面なのでスキップ
                continue
            cx_p = sum(p[0] for p in xy) / len(xy)
            cy_p = sum(p[1] for p in xy) / len(xy)
            if not (bbox_m[0] <= cx_p <= bbox_m[2] and bbox_m[1] <= cy_p <= bbox_m[3]):
                continue
            out.append({'fp': xy, 'a': {'name': name} if name else {}})
            emitted += 1

        if emitted == 0:
            stats['out_of_bbox'] += 1

    return out


def _polygon_area_xy(pts):
    s = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += (x1 * y2 - x2 * y1)
    return s / 2.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--brid-dir', required=True)
    ap.add_argument('--buildings-json', required=True)
    ap.add_argument('--area', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--bbox-margin', type=float, default=200.0,
                    help='印刷範囲を越えてどれくらいの橋梁を含めるか(m). 隅田川の橋を入れたい場合は 2500 程度を試してください。')
    args = ap.parse_args()

    with open(args.buildings_json) as f:
        bd = json.load(f)
    ref_lat = bd['ref_lat']; ref_lon = bd['ref_lon']
    scale = bd['scale']; range_m = bd['range_m']
    bbox_m = bbox_from_buildings_json(bd, args.bbox_margin)
    print(f"buildings ref: lat={ref_lat}, lon={ref_lon}")
    print(f"bbox (m, local): x[{bbox_m[0]:.0f}, {bbox_m[2]:.0f}] y[{bbox_m[1]:.0f}, {bbox_m[3]:.0f}]")

    files = sorted(glob.glob(os.path.join(args.brid_dir, '*brid*.gml'))
                   + glob.glob(os.path.join(args.brid_dir, '*brid*.xml')))
    if not files:
        files = sorted(glob.glob(os.path.join(args.brid_dir, '*.gml')))
    if not files:
        print(f"ERROR: no brid files found under {args.brid_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"\nProcessing {len(files)} brid file(s)...")
    items = []
    stats = {'bridge_elems': 0, 'no_geom': 0, 'out_of_bbox': 0}
    for fp in files:
        root = parse_xml(fp)
        if root is None:
            continue
        before = len(items)
        items.extend(extract_bridges(root, ref_lon, ref_lat, bbox_m, stats))
        print(f"  {os.path.basename(fp)}: +{len(items) - before}")

    print(f"\nDiagnostics:")
    print(f"  Bridge elements found: {stats['bridge_elems']}")
    print(f"  No geometry:           {stats['no_geom']}")
    print(f"  Filtered by bbox:      {stats['out_of_bbox']}")
    print(f"  Bridges emitted:       {len(items)}")

    out = {
        'type': 'bridges',
        'ref_lat': ref_lat, 'ref_lon': ref_lon, 'scale': scale, 'range_m': range_m,
        'items': items,
    }
    with open(args.output, 'w') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    print(f"\nWrote {len(items):,} bridges to {args.output}")


if __name__ == '__main__':
    main()

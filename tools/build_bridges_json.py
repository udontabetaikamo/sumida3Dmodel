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
    """1ファイルから Bridge を抽出して [{fp, a}, ...] を返す。

    bbox判定は「全ポリゴンの全頂点のうち1つでもbbox内」とゆるくする。
    フットプリントは最大面積の水平面 (Z分散が小) を選ぶ。"""
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

        # 全ポリゴンを local meters に変換し、頂点 1 つでも bbox に入るかチェック
        polys_xy = []
        all_in_bbox = False
        all_xy_pts = []
        for ext, _holes in polys:
            xy = polygon_to_xy(ext, ref_lon, ref_lat)
            polys_xy.append((xy, ext))
            for p in xy:
                all_xy_pts.append(p)
                if in_bbox(p, bbox_m):
                    all_in_bbox = True

        # デバッグ: 最初の数件の bbox を出力
        if stats['printed_debug'] < 3 and all_xy_pts:
            xs = [p[0] for p in all_xy_pts]
            ys = [p[1] for p in all_xy_pts]
            print(f"  [DEBUG bridge#{bi}] vertices_x={min(xs):.0f}..{max(xs):.0f}, "
                  f"vertices_y={min(ys):.0f}..{max(ys):.0f}, polys={len(polys)}, name={name}")
            stats['printed_debug'] += 1

        if not all_in_bbox:
            stats['out_of_bbox'] += 1
            continue

        # フットプリント選択: 各ポリゴンに「面積 / Z分散」スコアを計算し、最大を選ぶ
        # 水平な大きい面 = 橋の上面 or 下面 を優先
        best_score = -1
        best_xy = None
        for xy, ext in polys_xy:
            area = abs(_polygon_area_xy(xy))
            zs = [p[2] for p in ext if len(p) >= 3]
            z_var = (max(zs) - min(zs)) if zs else 0
            score = area / (z_var + 0.5)  # 水平&大きい程高得点
            if score > best_score:
                best_score = score
                best_xy = xy

        if best_xy is None or len(best_xy) < 3:
            continue

        out.append({'fp': best_xy, 'a': {'name': name} if name else {}})

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
    ap.add_argument('--bbox-margin', type=float, default=200.0)
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
    stats = {'bridge_elems': 0, 'no_geom': 0, 'out_of_bbox': 0, 'printed_debug': 0}
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

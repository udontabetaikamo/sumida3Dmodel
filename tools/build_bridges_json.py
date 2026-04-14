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
    localname, parse_xml, polygon_centroid_z, polygon_to_xy,
)


def extract_bridges(root, ref_lon, ref_lat, bbox_m, stats):
    """1ファイルから Bridge を抽出して [{fp, a}, ...] を返す。"""
    out = []
    bridges = list(iter_local(root, 'Bridge'))
    stats['bridge_elems'] += len(bridges)

    for bridge in bridges:
        # 名称(あれば)
        name = None
        for el in bridge:
            if localname(el.tag) == 'name' and el.text:
                name = el.text.strip()
                break

        polys = collect_polygons(bridge)
        if not polys:
            stats['no_geom'] += 1
            continue

        # 最も低い (Z 平均が最小の) 面をフットプリントとみなす
        rated = []
        for ext, _ in polys:
            z = polygon_centroid_z(ext)
            rated.append((z if z is not None else float('inf'), ext))
        rated.sort(key=lambda x: x[0])
        best_ext = rated[0][1]

        fp_xy = polygon_to_xy(best_ext, ref_lon, ref_lat)
        if not any(in_bbox(p, bbox_m) for p in fp_xy):
            stats['out_of_bbox'] += 1
            continue

        out.append({'fp': fp_xy, 'a': {'name': name} if name else {}})

    return out


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

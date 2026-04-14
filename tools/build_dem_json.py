#!/usr/bin/env python3
"""
PLATEAU dem (Terrain) CityGML → dem_<area>.json 変換スクリプト

PLATEAU 墨田区の DEM は TIN (三角形メッシュ) で配布されています。
これを JSON 用に「regular grid (cell_m メートルセル)」へリサンプリングします。

使い方:
    python3 tools/build_dem_json.py \
        --dem-dir "/Users/udon/Desktop/創作/0413_墨田区PLATEAU/13107_sumida-ku_pref_2025_citygml_1_op/udx/dem" \
        --buildings-json buildings_634635.json \
        --area 634635 \
        --output dem_634635.json

オプション:
    --cell-m 10        グリッドセルサイズ(m). デフォルト 10m
    --bbox-margin 100  bbox 余白(m)

出力フォーマット:
  { type: 'dem', grid: [[z,...], ...], origin_x, origin_y,
    cell_m, base_elev, ref_lat, ref_lon, scale, range_m }
"""

import argparse
import glob
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _plateau_common import (
    bbox_from_buildings_json, in_bbox, iter_local, lonlat_to_local_meters,
    parse_pos_list, parse_xml,
)


def collect_dem_vertices(root, ref_lon, ref_lat, bbox_m, stats):
    """TIN/Triangle/LinearRing から頂点 (x_m, y_m, elev) を全部集める。"""
    verts = []
    seen_keys = set()  # 重複削減

    # gml:LinearRing > gml:posList または gml:Triangle 内
    for el in root.iter():
        if not el.tag.endswith('}LinearRing') and not el.tag.endswith('LinearRing'):
            continue
        pl = None
        for sub in el:
            if sub.tag.endswith('posList'):
                pl = sub
                break
        if pl is None or not pl.text:
            continue
        pts = parse_pos_list(pl.text)
        for p in pts:
            if len(p) < 3:
                continue
            lon, lat, z = p[0], p[1], p[2]
            x, y = lonlat_to_local_meters(lon, lat, ref_lon, ref_lat)
            # 重複頂点を排除 (10cm 単位で量子化)
            key = (round(x * 10), round(y * 10))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            stats['vertices_total'] += 1
            if not in_bbox((x, y), bbox_m):
                stats['vertices_out_of_bbox'] += 1
                continue
            verts.append((x, y, z))
    return verts


def rasterize_to_grid(verts, bbox_m, cell_m):
    """頂点群をグリッドにビニング。各セルは平均標高、空セルは近傍平均で補間。"""
    minx, miny, maxx, maxy = bbox_m
    cols = max(1, int(math.ceil((maxx - minx) / cell_m)))
    rows = max(1, int(math.ceil((maxy - miny) / cell_m)))

    # bin
    accum_z = defaultdict(float)
    accum_n = defaultdict(int)
    for x, y, z in verts:
        c = int((x - minx) / cell_m)
        r = int((y - miny) / cell_m)
        if 0 <= c < cols and 0 <= r < rows:
            accum_z[(r, c)] += z
            accum_n[(r, c)] += 1

    grid = [[None] * cols for _ in range(rows)]
    all_z = []
    for (r, c), n in accum_n.items():
        z = accum_z[(r, c)] / n
        grid[r][c] = z
        all_z.append(z)

    if not all_z:
        return grid, rows, cols, 0.0

    base_elev = sorted(all_z)[len(all_z) // 2]  # median を基準に

    # 空セル: 既知セルからの距離重み付き平均で補間 (簡易IDW、半径3セル)
    if any(grid[r][c] is None for r in range(rows) for c in range(cols)):
        known = [(r, c, grid[r][c]) for r in range(rows) for c in range(cols) if grid[r][c] is not None]
        for r in range(rows):
            for c in range(cols):
                if grid[r][c] is not None:
                    continue
                # 3セル範囲の既知点を探す
                w_sum = 0.0
                v_sum = 0.0
                for dr in range(-3, 4):
                    for dc in range(-3, 4):
                        rr, cc = r + dr, c + dc
                        if 0 <= rr < rows and 0 <= cc < cols and grid[rr][cc] is not None:
                            d = math.sqrt(dr * dr + dc * dc)
                            if d == 0:
                                continue
                            w = 1.0 / d
                            w_sum += w
                            v_sum += w * grid[rr][cc]
                if w_sum > 0:
                    grid[r][c] = v_sum / w_sum
                else:
                    grid[r][c] = base_elev

    # 数値の丸めと None 置換
    for r in range(rows):
        for c in range(cols):
            v = grid[r][c]
            grid[r][c] = round(v if v is not None else base_elev, 2)

    return grid, rows, cols, round(base_elev, 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dem-dir', required=True)
    ap.add_argument('--buildings-json', required=True)
    ap.add_argument('--area', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--cell-m', type=float, default=10.0)
    ap.add_argument('--bbox-margin', type=float, default=100.0)
    args = ap.parse_args()

    with open(args.buildings_json) as f:
        bd = json.load(f)
    ref_lat = bd['ref_lat']; ref_lon = bd['ref_lon']
    scale = bd['scale']; range_m = bd['range_m']
    bbox_m = bbox_from_buildings_json(bd, args.bbox_margin)
    print(f"buildings ref: lat={ref_lat}, lon={ref_lon}")
    print(f"bbox (m, local): x[{bbox_m[0]:.0f}, {bbox_m[2]:.0f}] y[{bbox_m[1]:.0f}, {bbox_m[3]:.0f}]")
    print(f"cell size: {args.cell_m}m")

    files = sorted(glob.glob(os.path.join(args.dem_dir, '*dem*.gml'))
                   + glob.glob(os.path.join(args.dem_dir, '*dem*.xml')))
    if not files:
        files = sorted(glob.glob(os.path.join(args.dem_dir, '*.gml')))
    if not files:
        print(f"ERROR: no dem files found under {args.dem_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"\nProcessing {len(files)} dem file(s)...")
    all_verts = []
    stats = {'vertices_total': 0, 'vertices_out_of_bbox': 0}
    for fp in files:
        root = parse_xml(fp)
        if root is None:
            continue
        before = len(all_verts)
        all_verts.extend(collect_dem_vertices(root, ref_lon, ref_lat, bbox_m, stats))
        print(f"  {os.path.basename(fp)}: +{len(all_verts) - before:,} unique vertices")

    print(f"\nVertex stats:")
    print(f"  Vertices found:        {stats['vertices_total']:,}")
    print(f"  Out of bbox:           {stats['vertices_out_of_bbox']:,}")
    print(f"  Used for rasterize:    {len(all_verts):,}")

    if not all_verts:
        print("ERROR: no DEM vertices in bbox", file=sys.stderr)
        sys.exit(1)

    grid, rows, cols, base_elev = rasterize_to_grid(all_verts, bbox_m, args.cell_m)
    print(f"\nGrid: {rows} rows × {cols} cols ({rows*cols:,} cells)")
    print(f"  base_elev (median):    {base_elev}m")
    flat = [v for row in grid for v in row]
    print(f"  elev range:            {min(flat):.2f}m〜{max(flat):.2f}m")

    out = {
        'type': 'dem',
        'ref_lat': ref_lat, 'ref_lon': ref_lon, 'scale': scale, 'range_m': range_m,
        'origin_x': bbox_m[0],
        'origin_y': bbox_m[1],
        'cell_m': args.cell_m,
        'base_elev': base_elev,
        'grid': grid,
    }
    with open(args.output, 'w') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    print(f"\nWrote DEM grid to {args.output}")


if __name__ == '__main__':
    main()

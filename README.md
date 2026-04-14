# PLATEAU 3D Print Viewer - 墨田区

PLATEAUの3D都市モデルを使い、建物のZ軸を様々なデータ属性に置き換えて3Dプリント用STLを生成するWebアプリ。

**[Live Demo](https://udontabetaikamo.github.io/sumida3Dmodel/)**

## 概要

GISによる分析結果を3Dプリントで物理化するプロジェクト。通常は建物の高さで表現されるZ軸を、築年数・耐火構造・浸水深・地価などの属性に置き換え、同じ街の異なる姿を模型として比較できる。

GISコミュニティフォーラム マップギャラリー（ESRIジャパン主催）への出展を目的として制作。

## 機能

- **Z-axis Target**: 高さで表現する対象レイヤーを選択（Buildings / Roads）
- **マルチレイヤー表示**: PLATEAU の全12レイヤー（建物・道路・橋梁・水部・地形・浸水想定など）を**チェックボックスで重ね合わせ表示／非表示**切り替え
- **15種類の建物Z軸モード** + **7種類の道路Z軸モード**
- **高さ倍率**をスライダー・数値入力でリアルタイム調整
- **STLダウンロード** - 現在の設定でそのままBambu Lab等のスライサーに読み込める
- 2エリア対応（錦糸町駅周辺 / 押上駅周辺）

## レイヤー一覧

| ID | Label | データ種別 | 状態 |
|---|---|---|---|
| buildings | 建物 (bldg) | polygon | ✓ 実装済 |
| roads | 道路 (tran) | ribbon | ✓ 実装済 |
| bridges | 橋梁 (brid) | polygon | UI のみ（JSON 生成スクリプト要） |
| water | 水部 (wtr) | polygon | UI のみ |
| dem | 地形 (dem) | mesh | UI のみ |
| fld | 河川浸水想定 | flat-poly | UI のみ |
| htd | 高潮浸水想定 | flat-poly | UI のみ |
| tnm | 津波浸水想定 | flat-poly | UI のみ |
| ifld | 内水氾濫想定 | flat-poly | UI のみ |
| urf | 都市計画決定 | flat-poly | UI のみ |
| luse | 土地利用 | flat-poly | UI のみ |
| veg | 植生 | polygon | UI のみ |

JSON が未生成のレイヤーは自動的にチェックボックスがグレーアウトされ、
`(JSON未生成)` バッジが表示されます。チェック ON のレイヤーが存在すれば
そのレイヤーがコンテキストとして重ね描画され、Target レイヤーは Z軸モードに
従って高さ表現されます。

## Z軸モード一覧

| モード | Z軸の意味 | データソース |
|--------|----------|-------------|
| Building Height | 建物高さ（実測値） | PLATEAU CityGML |
| Building Age | 築年数（古いほど高い） | PLATEAU KVP |
| Structure (Wood) | 構造（木造ほど高い） | PLATEAU KVP |
| Fire Resistance | 耐火構造（非耐火ほど高い） | PLATEAU |
| Aging Risk | 老朽化（木造 x 築古の複合） | PLATEAU |
| River Flood Depth | 河川浸水深 | PLATEAU 災害リスク |
| High Tide Depth | 高潮浸水深 | PLATEAU 災害リスク |
| Flood Combined | 水害総合（河川+高潮） | PLATEAU 災害リスク |
| Roof Area | 屋根面積 | PLATEAU |
| Building Usage | 用途（業務/商業/住宅） | PLATEAU |
| Floor Area Ratio | 容積率 | PLATEAU |
| Number of Floors | 階数 | PLATEAU |
| Shelter Distance | 避難所までの距離 | 墨田区オープンデータ |
| Land Price | 地価公示 | 国土数値情報 L01 (2025) |
| Population Density | 人口密度 | 国土数値情報 500mメッシュ (2020) |

## 道路モード（Target = Roads）

| モード | Z軸の意味 | データソース |
|--------|----------|-------------|
| Road Width | 道路幅員（広いほど高い） | PLATEAU tran |
| Narrow Road Risk | 狭隘度（4m未満ほど高い／消防車進入困難） | PLATEAU tran |
| Road Class | 道路種別（国道/都道/区道） | PLATEAU tran |
| Road Function | 機能区分（車道部/交差部/歩道部） | PLATEAU tran |
| Emergency Transport Road | 緊急輸送道路指定 | 国土数値情報 N10（要マージ） |
| Daily Traffic Volume | 24h交通量 | 道路交通センサス N01（要マージ） |
| Uniform Height | 全道路均一高（ネットワーク俯瞰用） | — |

## レイヤーJSON生成スクリプト

各 PLATEAU udx モジュールから JSON を生成するスクリプトを `tools/` に配置しています。
すべて **buildings_<area>.json から座標基準を引き継ぐ** ため、座標系がずれません。

```bash
# 道路 (tran)
python3 tools/build_roads_json.py \
  --tran-dir "/path/to/.../udx/tran" \
  --buildings-json buildings_634635.json --area 634635 \
  --output roads_634635.json

# 橋梁 (brid)
python3 tools/build_bridges_json.py \
  --brid-dir "/path/to/.../udx/brid" \
  --buildings-json buildings_634635.json --area 634635 \
  --output bridges_634635.json

# 水部 (wtr)
python3 tools/build_water_json.py \
  --wtr-dir "/path/to/.../udx/wtr" \
  --buildings-json buildings_634635.json --area 634635 \
  --output water_634635.json

# 地形 (dem) — TIN を 10m グリッドへリサンプリング
python3 tools/build_dem_json.py \
  --dem-dir "/path/to/.../udx/dem" \
  --buildings-json buildings_634635.json --area 634635 \
  --output dem_634635.json
```

押上エリアも同様に `--area 654655 --buildings-json buildings_654655.json --output <id>_654655.json` で実行してください。

## 使用データ

- [PLATEAU 墨田区 CityGML 2025](https://www.geospatial.jp/ckan/dataset/plateau-13107-sumida-ku-2025)
- [国土数値情報 地価公示データ L01](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-L01-v3_1.html)
- [国土数値情報 500mメッシュ別将来推計人口](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-mesh500h30.html)
- [墨田区 避難所一覧オープンデータ](https://www.city.sumida.lg.jp/kuseijoho/sumida_info/opendata/opendata_ichiran/bosai_data/hinan_data.html)
- [G空間情報センター 指定緊急避難場所](https://www.geospatial.jp/ckan/dataset/hinanbasho)

## 技術構成

- Three.js (3Dレンダリング + STLエクスポート)
- PLATEAU CityGML → Python (lxml + numpy-stl) → JSON
- 単一HTMLファイル、サーバー不要（GitHub Pages対応）

## 印刷仕様

- 対象プリンター: Bambu Lab A1 Mini (180 x 180 x 180 mm)
- 印刷サイズ: 約180mm x 75mm
- XYスケール: 1:13
- 基盤厚: 1mm

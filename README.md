# 駅どうしの自動車の所要時間

Driving times and distances between pairs of railway stations in Japan, computed with OSRM on OpenStreetMap roads.

日本の鉄道駅の組ごとに、自動車で走ったときの所要時間（分）と道のり（km）。

- `car_times.csv.gz`：`from_station, to_station, minutes, km`（向きは問わない・923,013組）
- `stations.csv`：駅の名前と座標

## 作り方

- 道路：OpenStreetMap（Geofabrik の日本の抽出 `japan-261016.osm.pbf`）
- 経路：OSRM v26.10.0・車の設定（`car.lua` そのまま）・MLD
- 駅の座標から最寄りの道路に寄せ、table API で所要と道のりを引いた（渋滞は含まない）
- 作ったスクリプト：`build_car_times.py`（駅の組は、鉄道経営シミュレーションの需要の流れがある組を選んだ）

## 出典

- 道路：© OpenStreetMap contributors
- 駅の座標：「国土数値情報（鉄道データ）」（国土交通省）を加工して作成

## ライセンス

This data is derived from OpenStreetMap and is made available under the
[Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/).
© OpenStreetMap contributors — https://www.openstreetmap.org/copyright

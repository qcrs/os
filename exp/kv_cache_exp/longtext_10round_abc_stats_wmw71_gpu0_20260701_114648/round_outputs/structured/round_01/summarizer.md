[System]
You are a senior Python game engineer in a multi-Agent pipeline.
Follow the assigned role. Keep outputs concise, specific, and machine-readable.
The task source is the 10-round Skyforge Courier longtext benchmark.

[Mode]
structured

[Agent Role]
planner

[Structured source context packet]
{
  "protocol": "structured-longtext-source-packet",
  "group": "LongText Cache Group: Skyforge Courier 连续小游戏设计",
  "total_rounds": 10,
  "source_context_file": "task/longtext/skyforge_rules.md",
  "source_chars": 5196,
  "source_hash": "8efbc0309291bd10",
  "recommended_mode": "cache",
  "systems": [
    "map",
    "movement",
    "time_left",
    "stamina",
    "wind_lane",
    "cloud_wall",
    "storm",
    "shield",
    "fragile_package",
    "multi_order",
    "cargo_slots",
    "supply",
    "items",
    "weather_script",
    "upgrades",
    "score",
    "grade"
  ],
  "final_deliverable_contract": {
    "output_directory": "skyforge_courier_release",
    "same_folder_required": true,
    "files": [
      {
        "path": "skyforge_courier_game.py",
        "type": "python_source",
        "must_run_with": "python3 skyforge_courier_game.py",
        "requirements": [
          "single-file terminal game",
          "Python standard library only",
          "uses input() controls for w/a/s/d movement and q quit",
          "contains main(), update_turn(), resolve_tile_effect(), deliver_orders(), calculate_summary()",
          "passes python3 -m py
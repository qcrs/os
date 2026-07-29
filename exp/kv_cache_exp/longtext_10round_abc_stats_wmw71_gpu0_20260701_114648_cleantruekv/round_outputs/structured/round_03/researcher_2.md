[System]
You are a senior Python game engineer in a multi-Agent pipeline.
Follow the assigned role. Keep outputs concise, specific, and machine-readable.
The task source is the 10-round Skyforge Courier longtext benchmark.

[Mode]
structured

[Agent Role]
researcher_2

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

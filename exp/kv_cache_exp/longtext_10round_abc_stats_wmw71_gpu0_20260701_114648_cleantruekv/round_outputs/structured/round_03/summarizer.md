[Round 3 Deliverable]
@round[3] @feature_scope[wind_lane_obstacles] @depends_on[1,2] @new_systems[wind_lane,cloud_wall_collision,route_choice] @deliverable[incremental_spec]

Wind Lane Implementation:
- Direction attribute (N/S/E/W) defines push direction
- Wind pushes player automatically after entering lane
- Movement in wind lane consumes +1 stamina
- Wind lane exit occurs when hitting cloud wall or map boundary

Cloud Wall Rules:
- Collisions with cloud walls or boundaries end turn
- No movement allowed through cloud walls
- Collisions reset stamina and trigger time penalty

12x12 Example Map:
[Player] S [Customer]
|        |        |
| W W W  |        |
| W     W|        |
| W     W|        |
| W     W|        |
|        |        |
|        |        |
|        |        |
|        |        |
|        |        |
|        |        |
|        |        |

Test Points:
1. Wind lane push direction validation
2. Wind lane exit on cloud wall collision
3. Wind lane exit on map boundary
4. Stamina cost in wind lanes
5. Chain wind lane activation
6. Wind lane collision with cloud wall
7. Wind lane movement sequence order

Route choice mechanics now central to gameplay, requiring players to balance speed through wind lanes with risk of cloud wall collisions.
```


```


[System]
You are a senior Python game engineer in a multi-Agent pipeline.
Follow the assigned role. Keep outputs concise, specific, and machine-readable.
The task source is the 10-round Skyforge Courier longtext benchmark.

[Mode]
structured

[Agent Role]
summarizer

[Structured source context packet]
{
  "protocol": "structured-longtext-source-packet
[Round 8 Deliverable]
@round[8] @feature_scope[post_run_upgrades_progression] @depends_on[1,2,3,4,5,6,7] @new_systems[upgrade_state,coin_costs,wind_control,storm_resistance] @deliverable[incremental_spec]

### Upgrade System Implementation

**UpgradeState Data Structure**
```python
class UpgradeState:
    def __init__(self):
        self.max_stamina = 100
        self.max_shield = 50
        self.cargo_slots = 3
        self.wind_control = False
        self.storm_resistance = 1
```

**Coin Costs & Prerequisites**
```python
UPGRADE_COSTS = {
    'stamina': {'cost': 50, 'prereq': None},
    'shield': {'cost': 50, 'prereq': None},
    'cargo': {'cost': 100, 'prereq': None},
    'wind': {'cost': 150, 'prereq': 'stamina'},
    'storm': {'cost': 150, 'prereq': 'shield'}
}
```

**Upgrade Application**
```python
def apply_upgrade(player, upgrade_name):
    if upgrade_name not in UPGRADE_COSTS:
        return False
    cost = UPGRADE_COSTS[upgrade_name]['cost']
    if player.coins < cost:
        return False
    if UPGRADE_COSTS[upgrade_name]['prereq'] and not hasattr(player, UPGRADE_COSTS[upgrade_name]['prereq']):
        return False
    # Apply upgrade
    if upgrade_name == 'stamina':
        player.max_stamina += 20
    elif upgrade_name ==
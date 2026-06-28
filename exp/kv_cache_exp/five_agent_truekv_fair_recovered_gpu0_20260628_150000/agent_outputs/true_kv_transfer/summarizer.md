```python
# skyforge_courier_game.py
import os
import time
import random

# Game configuration
GAME_WIDTH = 12
GAME_HEIGHT = 12
MAX_STAMINA = 10
MAX_SHIELD = 3
INITIAL_TIME = 180  # seconds
ORDER_PRIORITY = ['core', 'normal', 'bonus']
WEATHER_TYPES = ['clear', 'wind', 'storm', 'fog']

# Game state
player = {
    'x': 1,
    'y': 1,
    'stamina': MAX_STAMINA,
    'shield': MAX_SHIELD,
    'time': INITIAL_TIME,
    'cargo': [],
    'orders': []
}

# Level data
level = {
    'width': GAME_WIDTH,
    'height': GAME_HEIGHT,
    'tiles': [['air' for _ in range(GAME_WIDTH)] for _ in range(GAME_HEIGHT)],
    'workshop': {'x': 1, 'y': 1},
    'customers': [{'id': 'c01', 'x': 8, 'y': 3}],
    'orders': [
        {'order_id': 'o01', 'customer_id': 'c01', 'priority': 'core', 'deadline': 180, 'reward_coins': 50, 'reward_rep': 10}
    ],
    'weather_script': [{'turn': 20, 'weather': 'storm'}]
}

def render_map():
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"Time: {player['time']:.1f}s | Stamina: {player['stamina']} | Shield: {player['shield']}")
    print(f"Orders: {len(player['orders'])} | Cargo: {len(player['cargo'])}")
    for y in range(level['height']):
        row = ''
        for x in range(level['width']):
            if x == player['x'] and y == player['y']:
                row += 'P'
            elif level['tiles'][y][x] == 'workshop':
                row += 'W'
            elif level['tiles'][y][x] == 'customer':
                row += 'C'
            elif level['tiles'][y][x] == 'storm':
                row += 'S'
            else:
                row += '.'
        print(row)
    print("\nControls: W/A/S/D to move, Q to quit")

def update_turn():
    # Check for weather changes
    for event in level['weather_script']:
        if event['turn'] <= player['time']:
            level['weather'] = event['weather']
            level['weather_script'].remove(event)
    
    # Check for order deadlines
    for order in player['orders']:
        if order['deadline'] <= player['time']:
            order['status'] = 'late'
    
    # Check for storm effects
    if level['weather'] == 'storm':
        for y in range(level['height']):
            for x in range(level['width']):
                if level['tiles'][y][x] == 'storm':
                    # Simulate storm effect
                    pass

def resolve_tile_effect(x, y):
    tile = level['tiles'][y][x]
    if tile == 'storm':
        if player['shield'] > 0:
            player['shield'] -= 1
        else:
            player['stamina'] -= 3
        print("You were hit by a storm! Shield: ", player['shield'], " Stamina: ", player['stamina'])

def deliver_orders():
    for order in player['orders']:
        if order['customer_id'] == 'c01' and player['x'] == 8 and player['y'] == 3:
            print(f"Delivered order {order['order_id']} to customer {order['customer_id']}")
            player['orders'].remove(order)
            player['coins'] += order['reward_coins']
            player['reputation'] += order['reward_rep']

def calculate_summary():
    core_orders = sum(1 for order in player['orders'] if order['priority'] == 'core')
    return {
        'core_orders': core_orders,
        'total_orders': len(player['orders']),
        'coins': player['coins'],
        'reputation': player['reputation']
    }

def main():
    while True:
        render_map()
        move = input("Move (W/A/S/D) or Q to quit: ").strip().lower()
        if move == 'q':
            break
        dx, dy = 0, 0
        if move == 'w':
            dy = -1
        elif move == 's':
            dy = 1
        elif move == 'a':
            dx = -1
        elif move == 'd':
            dx = 1
        else:
            continue
        
        new_x = player['x'] + dx
        new_y = player['y'] + dy
        
        if 0 <= new_x < level['width'] and 0 <= new_y < level['height']:
            player['x'] = new_x
            player['y'] = new_y
            player['time'] -= 1
            player['stamina'] -= 1
            resolve_tile_effect(new_x, new_y)
            update_turn()
            deliver_orders()
        else:
            print("Cannot move outside the map!")

if __name__ == "__main__":
    main()
```
```markdown
# Skyforge Courier Gameplay Manual

## Game Overview
Skyforge Courier is a single-player 2D top-down action game where you deliver energy packages between floating islands. Your goal is to complete core orders within time limits while managing stamina, avoiding storms, and using upgrades to improve your delivery efficiency.

## Controls
- W/A/S/D: Move in directions
- Q: Quit game

## Game Flow
1. Start at the workshop (W) at position (1,1)
2. Receive orders with deadlines and delivery requirements
3. Navigate the map using arrow keys
4. Deliver packages to customer points (C)
5. Manage stamina and shield to survive storms
6. Complete core orders to succeed
7. Use rewards to upgrade your courier abilities

## Game Elements
- **Workshop (W)**: Starting point and return location
- **Customer (C)**: Delivery targets for orders
- **Storm (S)**: Dangerous tiles that damage your shield or stamina
- **Air (.)**: Normal navigable tiles
- **Wind Lane**: Special tiles that push you in a direction
- **Supply Stations**: Locations to restore stamina or shield

## Game Mechanics
- **Time**: 180 seconds to complete deliveries
- **Stamina**: 10 points, used for movement
- **Shield**: 3 points, protects from storm damage
- **Orders**: Core orders must be delivered to succeed
- **Weather**: Dynamic weather effects change gameplay

## Scoring
- Core orders: +100 points each
- Normal orders: +50 points each
- Late deliveries: Half reward
- Storm damage: Reduces shield or stamina
- Efficient routes: Bonus for minimal steps

## Tips
- Use the workshop to reset your position
- Avoid storm tiles when possible
- Plan routes that minimize time and stamina use
- Complete core orders first for better rewards
- Use the map display to track your position and objectives
```

```python
# skyforge_courier_game.py
import os
import time
import random

# Game configuration
GAME_WIDTH = 12
GAME_HEIGHT = 12
MAX_STAMINA = 10
MAX_SHIELD = 3
INITIAL_TIME = 180  # seconds
ORDER_PRIORITY = ['core', 'normal', 'bonus']
WEATHER_TYPES = ['clear', 'wind', 'storm', 'fog']

# Game state
player = {
    'x': 1,
    'y': 1,
    'stamina': MAX_STAMINA,
    'shield': MAX_SHIELD,
    'time': INITIAL_TIME,
    'cargo': [],
    'orders': []
}

# Level data
level = {
    'width': GAME_WIDTH,
    'height': GAME_HEIGHT,
    'tiles': [['air' for _ in range(GAME_WIDTH)] for _ in range(GAME_HEIGHT)],
    'workshop': {'x': 1, 'y': 1},
    'customers': [{'id': 'c01', 'x': 8, 'y': 3}],
    'orders': [
        {'order_id': 'o01', 'customer_id': 'c01', 'priority': 'core', 'deadline': 180, 'reward_coins': 50, 'reward_rep': 10}
    ],
    'weather_script': [{'turn': 20, 'weather': 'storm'}]
}

def render_map():
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"Time: {player['time']:.1f}s | Stamina: {player['stamina']} | Shield: {player['shield']}")
    print(f"Orders: {len(player['orders'])} | Cargo: {len(player['cargo'])}")
    for y in range(level['height']):
        row = ''
        for x in range(level['width']):
            if x == player['x'] and y == player['y']:
                row += 'P'
            elif level['tiles'][y][x] == 'workshop':
                row += 'W'
            elif level['tiles'][y][x] == 'customer':
                row += 'C'
            elif level['tiles'][y][x] == 'storm':
                row += 'S'
            else:
                row += '.'
        print(row)
    print("\nControls: W/A/S/D to move, Q to quit")

def update_turn():
    # Check for weather changes
    for event in level['weather_script']:
        if event['turn'] <= player['time']:
            level['weather'] = event['weather']
            level['weather_script'].remove(event)
    
    # Check for order deadlines
    for order in player['orders']:
        if order['deadline'] <= player['time']:
            order['status'] = 'late'
    
    # Check for storm effects
    if level['weather'] == 'storm':
        for y in range(level['height']):
            for x in range(level['width']):
                if level['tiles'][y][x] == 'storm':
                    # Simulate storm effect
                    pass

def resolve_tile_effect(x, y):
    tile = level['tiles'][y][x]
    if tile == 'storm':
        if player['shield'] > 0:
            player['shield'] -= 1
        else:
            player['stamina'] -= 3
        print("You were hit by a storm! Shield: ", player['shield'], " Stamina: ", player['stamina'])

def deliver_orders():
    for order in player['orders']:
        if order['customer_id'] == 'c01' and player['x'] == 8 and player['y'] == 3:
            print(f"Delivered order {order['order_id']} to customer {order['customer_id']}")
            player['orders'].remove(order)
            player['coins'] += order['reward_coins']
            player['reputation'] += order['reward_rep']

def calculate_summary():
    core_orders = sum(1 for order in player['orders'] if order['priority'] == 'core')
    return {
        'core_orders': core_orders,
        'total_orders': len(player['orders']),
        'coins': player['coins'],
        'reputation': player['reputation']
    }

def main():
    while True:
        render_map()
        move = input("Move (W/A/S/D) or Q to quit: ").strip().lower()
        if move == 'q':
            break
        dx, dy = 0, 0
        if move == 'w':
            dy = -1
        elif move == 's':
            dy = 1
        elif move == 'a':
            dx = -1
        elif move == 'd':
            dx = 1
        else:
            continue
        
        new_x = player['x'] + dx
        new_y = player['y'] + dy
        
        if 0 <= new_x < level['width'] and 0 <= new_y < level['height']:
            player['x'] = new_x
            player['y'] = new_y
            player['time'] -= 1
            player['stamina'] -= 1
            resolve_tile_effect(new_x, new_y)
            update_turn()
            deliver_orders()
        else:
            print("Cannot move outside the map!")

if __name__ == "__main__":
    main()
```
```markdown
# Skyforge Courier Gameplay Manual

## Game Overview
Skyforge Courier is a single-player 2D top-down action game where you deliver energy packages between floating islands. Your goal is to complete core orders within time limits while managing stamina, avoiding storms, and using upgrades to improve your delivery efficiency.

## Controls
- W/A/S/D: Move in directions
- Q: Quit game

## Game Flow
1. Start at the workshop (W) at position (1,1)
2. Receive orders with deadlines and delivery requirements
3. Navigate the map using arrow keys
4. Deliver packages to customer points (C)
5. Manage stamina and shield to survive storms
6. Complete core orders to succeed
7. Use rewards to upgrade your courier abilities

## Game Elements
- **Workshop (W)**: Starting point and return location
- **Customer (C)**: Delivery targets for orders
- **Storm (S)**: Dangerous tiles that damage your shield or stamina
- **Air (.)**: Normal navigable tiles
- **Wind Lane**: Special tiles that push you in a direction
- **Supply Stations**: Locations to restore stamina or shield

## Game Mechanics
- **Time**: 180 seconds to complete deliveries
- **Stamina**: 10 points, used for movement
- **Shield**: 3 points, protects from storm damage
- **Orders**: Core orders must be delivered to succeed
- **Weather**: Dynamic weather effects change gameplay

## Scoring
- Core orders: +100 points each
- Normal orders: +50 points each
- Late deliveries: Half reward
- Storm damage: Reduces shield or stamina
- Efficient routes: Bonus for minimal steps

## Tips
- Use the workshop to reset your position
- Avoid storm tiles when possible
- Plan routes that minimize time and stamina use
- Complete core orders first for better rewards
- Use the map display to track your position and objectives
```


```python
# skyforge_courier_game.py
import os
import time
import random

# Game configuration
GAME_WIDTH = 12
GAME_HEIGHT = 12
MAX_STAMINA = 10
MAX_SHIELD = 3
INITIAL
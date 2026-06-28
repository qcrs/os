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
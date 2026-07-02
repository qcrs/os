"""
项目初始化脚本
"""

import os
import sys
from pathlib import Path

def init_project():
    """初始化项目目录结构"""
    
    print("Initializing Multi-Agent Collaboration System...")
    
    # 创建必要的目录
    dirs_to_create = [
        "data/memories",
        "data/vectors",
        "logs",
        "models",
        "config",
    ]
    
    base_path = Path(__file__).parent.parent
    
    for dir_path in dirs_to_create:
        full_path = base_path / dir_path
        full_path.mkdir(parents=True, exist_ok=True)
        print(f"✓ Created directory: {dir_path}")
    
    # 创建初始配置文件
    config_content = """# Default Configuration

system:
  environment: development
  debug: true
  log_level: INFO

agents:
  max_agents: 10
  agent_timeout: 30

communication:
  protocol: structured
  compression: true

embedding:
  model: all-MiniLM-L6-v2
  dimension: 384

memory:
  backend: memory
  max_memory_size: 10000
"""
    
    config_file = base_path / "config" / "default.yaml"
    if not config_file.exists():
        config_file.write_text(config_content)
        print(f"✓ Created config file: config/default.yaml")
    
    print("\n✓ Project initialization completed!")
    print("\nNext steps:")
    print("1. Install dependencies: pip install -r requirements.txt")
    print("2. Run example: python examples/example_task1.py")
    print("3. Run benchmark: python examples/benchmark.py")

if __name__ == "__main__":
    init_project()

#!/usr/bin/env python3
import os, sys
os.environ["CHAT_BACKEND"] = "transformers"
os.environ["LOCAL_MODEL_PATH"] = "/data/models/Qwen3-8B"
os.environ["LOCAL_MODEL_DEVICE"] = "cuda:0"
os.environ["LOCAL_MODEL_DTYPE"] = "bfloat16"
sys.path.insert(0, "/data/mingwei/SynapseX/src")
sys.path.insert(0, "/data/mingwei/SynapseX/langgraph/libs/langgraph")
sys.path.insert(0, "/data/mingwei/SynapseX/langgraph/libs/checkpoint")
from graph import build_graph
print("Graph import OK")
from models import get_model
from langchain_core.messages import HumanMessage
m = get_model(temperature=0.5)
r = m.invoke([HumanMessage(content="Say hello in one word.")])
print(f"Response: {r.content[:80]}")
print("Model OK")

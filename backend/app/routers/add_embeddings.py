# Script to add embeddings to chatbot_knowledge_base.json
import json
import os
from sentence_transformers import SentenceTransformer
import numpy as np

KB_PATH = os.path.join(os.path.dirname(__file__), "chatbot_knowledge_base.json")
MODEL_NAME = "all-MiniLM-L6-v2"

model = SentenceTransformer(MODEL_NAME)

with open(KB_PATH, "r") as f:
    kb = json.load(f)

for entry in kb:
    if "embedding" not in entry:
        # Use question + answer for richer context
        text = entry["question"] + " " + entry["answer"]
        embedding = model.encode(text).tolist()
        entry["embedding"] = embedding

with open(KB_PATH, "w") as f:
    json.dump(kb, f, indent=2)

print("Embeddings added to knowledge base.")

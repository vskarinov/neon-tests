import os


START_BLOCK = os.environ.get("START_BLOCK", 0)
FINISH_BLOCK = os.environ.get("FINISH_BLOCK", 1000)
PROXY_IP = os.environ.get("PROXY_IP", "127.0.0.1")

ENVS = [
    {"name": "neon", "url": f"http://{PROXY_IP}:9090/solana"},
    {"name": "bestarch", "url": f"http://{PROXY_IP}:8018/solana"}
]
LOGS_PATH = "./indexers_diff"

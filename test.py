import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
from openai import OpenAI
import json
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("LLM_API_KEY")
base_url = os.getenv("LLM_BASE_URL")
model = os.getenv("LLM_MODEL", "glm-5.1")
verify_ssl = os.getenv("LLM_VERIFY_SSL", "true").lower() != "false"
disable_proxy = os.getenv("LLM_DISABLE_PROXY", "false").lower() != "false"

kwargs = {"api_key": api_key}
if base_url:
    kwargs["base_url"] = base_url.rstrip("/")
if not verify_ssl or disable_proxy:
    import httpx
    kwargs["http_client"] = httpx.Client(verify=verify_ssl, trust_env=not disable_proxy)

client = OpenAI(**kwargs)
stream = client.chat.completions.create(
    model=model,
    messages=[{'role': 'user', 'content': '1+1等于几？'}],
    max_tokens=256,
    temperature=0.7,
    stream=True
)

for chunk in stream:
    # 打印完整 chunk 的原始数据
    print(json.dumps(chunk.to_dict(), ensure_ascii=False))
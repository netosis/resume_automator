import os
from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek

# Load environment variables
load_dotenv()

# Initialize the DeepSeek model via LangChain
api_key = os.getenv("DEEPSEEK_API_KEY")
api_base = os.getenv("DEEPSEEK_API_BASE") or "https://api.deepseek.com/v1"

print(f"Initializing ChatDeepSeek model='deepseek-chat' at base='{api_base}'...")
model = ChatDeepSeek(
    model="deepseek-chat",
    api_key=api_key,
    api_base=api_base,
    temperature=0.0
)

# Send a basic hello message
try:
    response = model.invoke("Hello")
    # Print the response
    print("\nResponse from DeepSeek API:")
    import sys
    # Safely handle console encoding in Windows to avoid charmap crash
    safe_stdout = sys.stdout.encoding or 'utf-8'
    safe_text = response.content.encode(safe_stdout, errors='replace').decode(safe_stdout, errors='replace')
    print(safe_text)
except Exception as e:
    print(f"\nError invoking DeepSeek model: {e}")

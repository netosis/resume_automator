import asyncio
import os
import argparse
from pathlib import Path
from dotenv import load_dotenv

# Ensure browser-use is installed
try:
    from browser_use import Agent, Browser
except ImportError:
    print("Please install browser-use: pip install browser-use")
    import sys
    sys.exit(1)

from langchain_openai import ChatOpenAI

class CustomChatOpenAI(ChatOpenAI):
    model_config = {"extra": "allow", "arbitrary_types_allowed": True}
    
    @property
    def provider(self):
        return "openai"

# Alternatively, if langchain_deepseek is preferred:
# from langchain_deepseek import ChatDeepSeek

# Load environment variables
load_dotenv()

def get_brave_paths():
    user_profile = os.environ.get("USERPROFILE", "")
    user_data_dir = os.path.join(user_profile, "AppData", "Local", "BraveSoftware", "Brave-Browser", "User Data")
    executable_path = "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe"
    
    # Fallback if brave isn't in Program Files
    if not os.path.exists(executable_path):
        alt_path = "C:\\Program Files (x86)\\BraveSoftware\\Brave-Browser\\Application\\brave.exe"
        if os.path.exists(alt_path):
            executable_path = alt_path
            
    return executable_path, user_data_dir

async def main(job_title: str, location: str):
    executable_path, user_data_dir = get_brave_paths()
    print(f"Using Brave Browser at: {executable_path}")
    print(f"Using User Data Dir: {user_data_dir}")
    
    # Initialize the browser
    try:
        from browser_use.browser.browser import BrowserConfig
        browser = Browser(
            config=BrowserConfig(
                executable_path=executable_path,
                user_data_dir=user_data_dir,
            )
        )
    except ImportError:
        # Fallback to direct kwargs if BrowserConfig doesn't exist
        browser = Browser(
            executable_path=executable_path,
            user_data_dir=user_data_dir,
        )

    # Initialize DeepSeek LLM
    # We use ChatOpenAI connected to DeepSeek's API because browser-use relies on 
    # OpenAI-compatible tool calling schemas which DeepSeek supports via the OpenAI client.
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("Error: DEEPSEEK_API_KEY is not set in .env")
        import sys
        sys.exit(1)

    # Note: DeepSeek officially provides OpenAI compatibility
    llm = CustomChatOpenAI(
        model="deepseek-chat",
        api_key=api_key,
        base_url="https://api.deepseek.com",
        max_tokens=4096
    )

    task_description = (
        f"Go to Naukri. Search for '{job_title}' jobs in '{location}'. "
        f"Find 1 relevant job and attempt to apply for it. "
        f"If the application redirects to a company portal or a Workday form, navigate through "
        f"the forms and fill them out. Use the information from my logged-in profile "
        f"and standard resume details where available. Do not submit the final application, just stop at the review/submit page."
    )

    agent = Agent(
        task=task_description,
        llm=llm,
        browser=browser,
        extend_system_message="IMPORTANT: You must return ONLY valid JSON matching the schema. Do not include any conversational text before or after the JSON. Do not wrap the JSON in markdown code blocks."
    )

    print("Starting the browser agent...")
    await agent.run()
    
    print("Agent execution completed. Closing browser.")
    try:
        if hasattr(browser, 'close'):
            await browser.close()
    except AttributeError:
        pass  # In some versions of browser-use, browser is automatically managed or lacks a close method

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Job Application Agent using browser-use")
    parser.add_argument("--job-title", default="Software Engineer", help="The job title to search for")
    parser.add_argument("--location", default="Remote", help="The location to search in")
    
    args = parser.parse_args()
    
    asyncio.run(main(args.job_title, args.location))

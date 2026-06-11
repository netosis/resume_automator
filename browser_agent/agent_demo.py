import os
import sys
import time
import random
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, ToolMessage, AIMessage

def invoke_model_with_retry(model, messages, max_retries=5, initial_delay=2.0):
    """
    Invokes the model with exponential backoff retry for 429 (Rate Limit) and 503 (Service Unavailable) errors.
    """
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            return model.invoke(messages)
        except Exception as e:
            err_msg = str(e)
            is_rate_limit = "429" in err_msg or "ResourceExhausted" in err_msg or "quota" in err_msg.lower()
            is_service_unavailable = "503" in err_msg or "ServiceUnavailable" in err_msg or "unavailable" in err_msg.lower()
            
            if (is_rate_limit or is_service_unavailable) and attempt < max_retries - 1:
                sleep_time = delay + random.uniform(0, 1.0)
                print(f"\n[API Warning]: Encountered transient error ({type(e).__name__}: {err_msg}). Retrying in {sleep_time:.2f} seconds... (Attempt {attempt + 1}/{max_retries})")
                time.sleep(sleep_time)
                delay *= 2
            else:
                raise e

# Add current directory to path to allow import
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from browser_tools import (
    open_website,
    get_page_text,
    click_on_element,
    input_text_into_element,
    scroll_page,
    close_browser_session
)

# Load environment variables (for GEMINI_API_KEY)
load_dotenv()

def run_browser_agent(prompt: str):
    """
    Runs a simple agent loop using the Gemini model and the browser tools.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY is not set in your environment variables.")
        print("Please create a .env file or export the key, then try again.")
        return

    # Initialize Gemini model via LangChain
    model = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        api_key=api_key,
        temperature=0.0
    )

    # Define tool library
    tools = [
        open_website,
        get_page_text,
        click_on_element,
        input_text_into_element,
        scroll_page,
        close_browser_session
    ]

    # Bind tools to the model
    model_with_tools = model.bind_tools(tools)

    print("\n--- Starting Agent Execution ---")
    print(f"Task Prompt: {prompt}\n")

    messages = [
        HumanMessage(content=(
            f"You are a helpful browser automation agent. Your task is: {prompt}. "
            "Use the browser tools provided to execute the request. "
            "After performing your operations (such as opening websites like naukri.com, "
            "linkedin.com, glassdoor.com, searching, extracting page text), analyze the "
            "retrieved information and present a final response. "
            "Make sure to close the browser session when you are fully done."
        ))
    ]

    max_steps = 15
    for step in range(max_steps):
        print(f"[Agent Step {step + 1}] Invoking Gemini...")
        try:
            response = invoke_model_with_retry(model_with_tools, messages)
        except Exception as e:
            print(f"\n[Agent Error]: API call failed after retries. Error: {e}")
            break
        messages.append(response)

        # Print thoughts if there is any content response
        if response.content:
            print(f"\n[Agent Thoughts]:\n{response.content}\n")

        # If there are no tool calls, agent has finished
        if not response.tool_calls:
            print("[Agent Execution Complete]")
            break

        # Process each tool call suggested by the model
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_id = tool_call["id"]

            # Count input tokens
            input_tokens = model.get_num_tokens(str(tool_args))
            print(f"[Agent Tool Call]: {tool_name} with args {tool_args} | Input Size: {input_tokens} tokens")

            # Find and invoke the matching tool
            matching_tool = next((t for t in tools if t.name == tool_name), None)
            if matching_tool:
                try:
                    result = matching_tool.invoke(tool_args)
                    result_str = str(result)
                    
                    # Count output tokens
                    output_tokens = model.get_num_tokens(result_str)
                    print(f"[Tool Response]: {result}")
                    print(f"[Token Usage]: Tool '{tool_name}' consumed: {input_tokens} (input) + {output_tokens} (output) = {input_tokens + output_tokens} total tokens\n")
                    
                    messages.append(ToolMessage(content=result_str, tool_call_id=tool_id))
                except Exception as e:
                    error_msg = f"Error running tool '{tool_name}': {str(e)}"
                    error_tokens = model.get_num_tokens(error_msg)
                    print(f"[Tool Error]: {error_msg}")
                    print(f"[Token Usage]: Tool '{tool_name}' error output: {error_tokens} tokens\n")
                    messages.append(ToolMessage(content=error_msg, tool_call_id=tool_id))
            else:
                error_msg = f"Tool '{tool_name}' is not registered."
                error_tokens = model.get_num_tokens(error_msg)
                print(f"[Tool Error]: {error_msg}")
                print(f"[Token Usage]: Tool '{tool_name}' error output: {error_tokens} tokens\n")
                messages.append(ToolMessage(content=error_msg, tool_call_id=tool_id))
    else:
        print("[Agent Warning]: Reached maximum steps without formal completion.")

if __name__ == "__main__":
    default_prompt = (
        "Open naukri.com, search for 'Python Developer' in the search bar, "
        "and print the titles of the first 3 job postings you see on the page. "
        "Remember to close the browser session at the end."
    )
    
    print("Welcome to the Browser Automation LLM Agent Demo!")
    print("Press Enter to use the default prompt, or enter a custom prompt below.")
    print(f"Default prompt: \"{default_prompt}\"")
    
    try:
        user_prompt = input("\nEnter prompt: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nExiting.")
        sys.exit(0)

    prompt = user_prompt if user_prompt else default_prompt
    run_browser_agent(prompt)

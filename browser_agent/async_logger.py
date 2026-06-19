import time
import json
import queue
import threading
import sys
import atexit
import traceback
import os
from pathlib import Path
from typing import Optional, Any, List, Dict

_SESSION_ID = time.strftime("%Y%m%d_%H%M%S")
_API_CALL_LOGS: List[Dict[str, Any]] = []
_LOG_QUEUE = queue.Queue()
_LOG_THREAD = None
_LOG_THREAD_STOPPED = threading.Event()
_LOCK = threading.Lock()

def get_session_id() -> str:
    return _SESSION_ID

def _perform_log_write(log_entry: dict):
    global _API_CALL_LOGS
    with _LOCK:
        _API_CALL_LOGS.append(log_entry)
        logs_copy = list(_API_CALL_LOGS)
    
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    session_log_file = log_dir / f"session_api_calls_{_SESSION_ID}.json"
    
    try:
        with open(session_log_file, "w", encoding="utf-8") as f:
            json.dump(logs_copy, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[Async Logger File Error] Failed writing to {session_log_file}: {e}", file=sys.stderr)

def _log_worker():
    while not _LOG_THREAD_STOPPED.is_set() or not _LOG_QUEUE.empty():
        try:
            item = _LOG_QUEUE.get(timeout=0.1)
        except queue.Empty:
            continue
        
        try:
            _perform_log_write(item)
        except Exception as e:
            print(f"[Async Logger Worker Error] Failed to write log: {e}", file=sys.stderr)
        finally:
            _LOG_QUEUE.task_done()

def start_log_thread():
    global _LOG_THREAD
    with _LOCK:
        if _LOG_THREAD is None or not _LOG_THREAD.is_alive():
            _LOG_THREAD_STOPPED.clear()
            _LOG_THREAD = threading.Thread(target=_log_worker, name="AsyncLoggerWorker", daemon=True)
            _LOG_THREAD.start()

def stop_and_flush_log_thread():
    global _LOG_THREAD
    _LOG_THREAD_STOPPED.set()
    if _LOG_THREAD is not None and _LOG_THREAD.is_alive():
        _LOG_THREAD.join(timeout=2.0)

def log_api_call(
    caller_name: str,
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    sent_data: Optional[Any] = None,
    response_data: Optional[Any] = None
):
    """
    Logs an LLM API call or Tool execution details and token usage asynchronously to the active session log file.
    """
    log_entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "caller": caller_name,
        "model": model_name,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens
    }
    
    if sent_data is not None:
        try:
            json.dumps(sent_data)
            log_entry["sent_data"] = sent_data
        except Exception:
            log_entry["sent_data"] = str(sent_data)

    if response_data is not None:
        try:
            json.dumps(response_data)
            log_entry["response_data"] = response_data
        except Exception:
            log_entry["response_data"] = str(response_data)

    start_log_thread()
    _LOG_QUEUE.put(log_entry)
    print(f"[Session Token Logger (Async)] Queued API/tool call from '{caller_name}'")

async def log_api_call_async(
    caller_name: str,
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    sent_data: Optional[Any] = None,
    response_data: Optional[Any] = None
):
    """
    Asynchronously logs an LLM API call using asyncio executors.
    """
    import asyncio
    log_entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "caller": caller_name,
        "model": model_name,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens
    }
    
    if sent_data is not None:
        try:
            json.dumps(sent_data)
            log_entry["sent_data"] = sent_data
        except Exception:
            log_entry["sent_data"] = str(sent_data)

    if response_data is not None:
        try:
            json.dumps(response_data)
            log_entry["response_data"] = response_data
        except Exception:
            log_entry["response_data"] = str(response_data)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _perform_log_write, log_entry)

def save_chat_transcript(platform: str, messages: list, session_id: str):
    """
    Logs the total chat transcript to a text file.
    """
    try:
        log_dir = Path(__file__).parent.parent / "logs"
        log_dir.mkdir(exist_ok=True)
        filename = log_dir / f"{platform}_chat_transcript_{session_id}.txt"
        
        # Match tool call IDs to names
        tool_call_id_to_name = {}
        for msg in messages:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    if isinstance(tc, dict) and "id" in tc and "name" in tc:
                        tool_call_id_to_name[tc["id"]] = tc["name"]
                        
        transcript_lines = []
        transcript_lines.append("=" * 80)
        transcript_lines.append(f"AGENT CHAT TRANSCRIPT - Platform: {platform.upper()}")
        transcript_lines.append(f"Session ID: {session_id}")
        transcript_lines.append(f"Generated on: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        transcript_lines.append("=" * 80)
        transcript_lines.append("\n")
        
        for idx, msg in enumerate(messages):
            msg_type = type(msg).__name__
            transcript_lines.append(f"--- Message {idx + 1} ({msg_type}) ---")
            
            if msg_type == "HumanMessage":
                transcript_lines.append(f"[USER/PROMPT]:\n{msg.content}\n")
            elif msg_type == "SystemMessage":
                transcript_lines.append(f"[SYSTEM MESSAGE]:\n{msg.content}\n")
            elif msg_type == "AIMessage":
                transcript_lines.append(f"[AI THOUGHTS/RESPONSE]:\n{msg.content or '(No text content)'}\n")
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    transcript_lines.append("Proposed Tool Call(s):")
                    for tc in msg.tool_calls:
                        if isinstance(tc, dict):
                            transcript_lines.append(f"  - Tool: {tc.get('name')} | Arguments: {tc.get('args')} | Call ID: {tc.get('id')}")
                    transcript_lines.append("")
            elif msg_type == "ToolMessage":
                tool_name = tool_call_id_to_name.get(msg.tool_call_id, "unknown_tool")
                transcript_lines.append(f"[TOOL RESPONSE: '{tool_name}'] (Call ID: {msg.tool_call_id}):\n{msg.content}\n")
            else:
                transcript_lines.append(f"[UNKNOWN MESSAGE TYPE]:\n{msg.content}\n")
                
            transcript_lines.append("-" * 60 + "\n")
            
        with open(filename, "w", encoding="utf-8") as f:
            f.write("\n".join(transcript_lines))
        print(f"[Transcript Logger] Chat transcript saved/updated at: {filename}")
    except Exception as e:
        print(f"[Transcript Logger Warning] Failed to save chat transcript: {e}")

def custom_excepthook(exctype, value, tb):
    err_msg = "".join(traceback.format_exception(exctype, value, tb))
    print(f"[Exception Hook Caught Crash] Logging exception to session log:\n{err_msg}", file=sys.stderr)
    
    log_entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "caller": "SYSTEM_CRASH",
        "model": "system_error",
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "sent_data": f"Unhandled Exception of type: {exctype.__name__}",
        "response_data": err_msg
    }
    
    start_log_thread()
    _LOG_QUEUE.put(log_entry)
    stop_and_flush_log_thread()
    sys.__excepthook__(exctype, value, tb)

def custom_thread_excepthook(args):
    err_msg = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    print(f"[Thread Exception Caught Crash] Logging thread exception to session log:\n{err_msg}", file=sys.stderr)
    
    log_entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "caller": f"THREAD_CRASH_{args.thread.name if args.thread else 'unknown'}",
        "model": "system_error",
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "sent_data": f"Unhandled Exception in thread: {args.exc_type.__name__}",
        "response_data": err_msg
    }
    start_log_thread()
    _LOG_QUEUE.put(log_entry)

def handle_exit():
    log_entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "caller": "SYSTEM_EXIT",
        "model": "system_event",
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "sent_data": "Script terminated.",
        "response_data": "Execution finished or stopped."
    }
    start_log_thread()
    _LOG_QUEUE.put(log_entry)
    stop_and_flush_log_thread()

# Register system hooks
sys.excepthook = custom_excepthook
threading.excepthook = custom_thread_excepthook
atexit.register(handle_exit)

# Start logging worker immediately
start_log_thread()

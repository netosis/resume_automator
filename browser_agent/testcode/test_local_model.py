import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure parent and current directories are on path to allow imports
sys.path.append(str(Path(__file__).parent.parent.resolve()))
sys.path.append(str(Path(__file__).parent.parent.parent.resolve() / "resume_to_latex"))
sys.path.append(str(Path(__file__).parent.parent.parent.resolve() / "jd_to_latex"))

def run_local_model_verification():
    print("=== Verification: Local Model Initialization & Toggles ===")
    
    # 1. Temporarily set env variables for local model configuration
    os.environ["LLM_PROVIDER"] = "local"
    os.environ["LOCAL_API_BASE"] = "http://localhost:11434/v1"
    os.environ["LOCAL_MODEL"] = "test-local-model"
    os.environ["LOCAL_API_KEY"] = "test-key"

    print("\n1. Testing model imports and environment variables...")
    try:
        from langchain_openai import ChatOpenAI
        print("[OK] langchain_openai import successful.")
    except ImportError as e:
        print(f"[FAIL] Failed to import langchain_openai: {e}")
        return False

    # 2. Test resolve_api_key in txt_resume_to_latex_resume
    print("\n2. Testing resolve_api_key in txt_resume_to_latex_resume...")
    try:
        from txt_resume_to_latex_resume import resolve_api_key
        key = resolve_api_key(None, provider="local")
        print(f"[OK] Resolved key for local provider: '{key}'")
        if key != "test-key":
            print(f"[FAIL] Expected key 'test-key', got '{key}'")
            return False
    except Exception as e:
        print(f"[FAIL] resolve_api_key raised error: {e}")
        return False

    # 3. Test resolve_api_key in resume_tailoring_workflow
    print("\n3. Testing resolve_api_key in resume_tailoring_workflow...")
    try:
        from resume_tailoring_workflow import resolve_api_key as resolve_api_key_tailor
        key = resolve_api_key_tailor(None, provider="local")
        print(f"[OK] Resolved key for local provider in tailoring: '{key}'")
        if key != "test-key":
            print(f"[FAIL] Expected key 'test-key', got '{key}'")
            return False
    except Exception as e:
        print(f"[FAIL] resolve_api_key in tailoring raised error: {e}")
        return False

    # 4. Test Local Model Instantiation in txt_resume_to_latex_resume (Mocked API call)
    print("\n4. Testing Local Model Instantiation in txt_resume_to_latex_resume (Mocked)...")
    try:
        from txt_resume_to_latex_resume import txt_to_resume_latex
        
        # We patch llm.invoke and Path.write_text to avoid hitting a real server and file system
        with patch("langchain_openai.ChatOpenAI.invoke") as mock_invoke, \
             patch("pathlib.Path.read_text", return_value="dummy template content"), \
             patch("pathlib.Path.write_text") as mock_write, \
             patch("txt_resume_to_latex_resume.resolve_txt_path", return_value=Path("dummy.txt")):
            
            # Setup a mock response
            mock_response = MagicMock()
            mock_response.content = "mocked compiled latex resume content"
            mock_response.usage_metadata = {"input_tokens": 120, "output_tokens": 250}
            mock_invoke.return_value = mock_response
            
            # Run conversion function
            result_path = txt_to_resume_latex(
                txt_path="dummy.txt",
                output_dir="test_out",
                output_name="test_latex",
                base_latex_path="base_reference/resume_reference_1.tex",
                model="test-local-model"
            )
            print(f"[OK] Mocked txt_to_resume_latex completed successfully. Output path: {result_path}")
            
            # Verify mock_invoke was called on ChatOpenAI
            mock_invoke.assert_called_once()
            print("[OK] ChatOpenAI invoke was called correctly.")
    except Exception as e:
        print(f"[FAIL] Instantiation/Mock run in txt_to_resume_latex failed: {e}")
        return False

    # 5. Test Local Model Instantiation in ResumeTailoringAgent (Mocked)
    print("\n5. Testing Local Model Instantiation in ResumeTailoringAgent (Mocked)...")
    try:
        from resume_tailoring_workflow import ResumeTailoringAgent
        
        with patch("langchain_openai.ChatOpenAI.invoke") as mock_invoke:
            mock_response = MagicMock()
            mock_response.content = "<DECISION>MODIFY</DECISION><TARGET_SECTIONS>summary</TARGET_SECTIONS><RATIONALE>test</RATIONALE><LEARNABLE_SKILLS>- Python</LEARNABLE_SKILLS>"
            mock_response.usage_metadata = {"input_tokens": 80, "output_tokens": 100}
            mock_invoke.return_value = mock_response
            
            agent = ResumeTailoringAgent(model="test-local-model")
            print("[OK] ResumeTailoringAgent initialized successfully with local provider.")
            
            # Mock details
            resume_mock = MagicMock()
            resume_mock.preview_map.return_value = {
                "summary": "Developer",
                "education": "BS",
                "experience": "Senior",
                "skills": "Python",
                "other_parameters": "none"
            }
            
            plan = agent.plan_sections("Job Description", resume_mock)
            print(f"[OK] Section planning succeeded with mocked local response: {plan}")
            mock_invoke.assert_called_once()
    except Exception as e:
        print(f"[FAIL] ResumeTailoringAgent mock run failed: {e}")
        return False

    print("\n=== All Local Model Toggle & Init Verifications Passed! ===")
    return True

if __name__ == "__main__":
    success = run_local_model_verification()
    sys.exit(0 if success else 1)

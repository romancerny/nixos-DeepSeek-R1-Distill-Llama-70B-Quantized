# Q1:
i wanna use the https://www.coursera.org/learn/dlai-agentic-ai with multiple agents, some researching economicala nd logical topics and some coding, and some testing. can i use eg deepseek-r1:70b and qwen2.5-coder:32b, where deepseek would do the researcha nd designs and persist them in the repo files, and then the coder would code to these designed spacs? could they be loaded just one at the time, and work like this automatically, to the specs and definitions?

# A1:
Yes, you can absolutely do this, and it aligns perfectly with the Multi-Agent and Planning design patterns taught in Andrew Ng’s Agentic AI course.
Because your hardware cannot run both models simultaneously without crashing or severely paging to swap, loading them sequentially (one at a time) is the exact right engineering strategy. By using your local file repository as a shared memory layer, the models don't need to be in RAM at the same time to collaborate effectively.

🗺️ The Architecture: Sequential Multi-Agent Workflow

Instead of a real-time conversational multi-agent framework (which forces all models into memory at once), you will build a State-Passing File-Based Pipeline.
[User Request] 
      │
      ▼
┌────────────────────────────────────────────────────────┐
│ 1. OLLAMA LOADS: deepseek-r1:70b                       │
│    ├─ Task: Multi-step Planning & Business Research    │
│    └─ Output: Writes `architecture_spec.md` to disk    │
└────────────────────────────────────────────────────────┘
      │ (Ollama unloads DeepSeek from VRAM/RAM)
      ▼
┌────────────────────────────────────────────────────────┐
│ 2. OLLAMA LOADS: qwen2.5-coder:32b                     │
│    ├─ Task: Code generation against the spec file      │
│    └─ Output: Writes operational script files to disk  │
└────────────────────────────────────────────────────────┘
      │ (Ollama unloads Qwen)
      ▼
┌────────────────────────────────────────────────────────┐
│ 3. OLLAMA LOADS: qwen2.5-coder:32b (or a fast 8B model)│
│    ├─ Task: Code Execution & Automated Testing         │
│    └─ Output: Generates test execution logs            │
└────────────────────────────────────────────────────────┘

🛠️ How to Make it Work Automatically in Python

Ollama features an internal concurrency and timeout subsystem. If you request a model that isn't currently loaded, Ollama will automatically unload the old model from VRAM/RAM, load the new one, run the task, and then let it sit idle. By setting OLLAMA_NUM_PARALLEL=1 (which you already have in your NixOS config), you guarantee they execute one after the other.
Here is a practical, first-principles Python implementation following the course's structural guidelines:
python
import os
import time
import ollama

# Ensure our local workspace repository exists
WORKSPACE_DIR = "./agent_workspace"
os.makedirs(WORKSPACE_DIR, exist_ok=True)

SPEC_FILE = os.path.join(WORKSPACE_DIR, "architecture_spec.md")
CODE_FILE = os.path.join(WORKSPACE_DIR, "app.py")

def run_research_agent(user_prompt):
    print("🧠 [Agent 1] Loading deepseek-r1:70b for Deep Reasoning & Design...")
    
    system_instruction = (
        "You are an expert economic analyst and software architect. "
        "Analyze the user request, break it down logically, and output a strict "
        "Markdown technical specification sheet. Save nothing else but the markdown."
    )
    
    response = ollama.generate(
        model="deepseek-r1:70b",
        prompt=f"{system_instruction}\n\nUser Request: {user_prompt}"
    )
    
    # Strip the <thought> logs if you only want the raw markdown specs saved
    full_output = response['response']
    clean_spec = full_output.split("</thought>")[-1].strip()
    
    with open(SPEC_FILE, "w") as f:
        f.write(clean_spec)
    print("✅ Design persisted to disk at `architecture_spec.md`.\n")

def run_coding_agent():
    print("💻 [Agent 2] Loading qwen2.5-coder:32b for Fast Native Code Generation...")
    
    with open(SPEC_FILE, "r") as f:
        spec_content = f.read()
        
    prompt = (
        f"Read this design specification carefully and write the functional Python code matching it.\n"
        f"Output ONLY executable Python code within code blocks. Do not explain your work.\n\n"
        f"Specification:\n{spec_content}"
    )
    
    response = ollama.generate(
        model="qwen2.5-coder:32b",
        prompt=prompt
    )
    
    # Simple parsing to isolate the code block text
    raw_code = response['response']
    if "```python" in raw_code:
        code_content = raw_code.split("```python")[1].split("```")[0].strip()
    else:
        code_content = raw_code.strip()
        
    with open(CODE_FILE, "w") as f:
        f.write(code_content)
    print("✅ Implementation code written to `app.py`.\n")

# --- ORCHESTRATION PIPELINE ---
if __name__ == "__main__":
    task = "Build a subscription billing simulator that calculates churn logic given variable tax rates across the EU."
    
    start_time = time.time()
    
    # Step 1: DeepSeek reasons, designs, and writes files
    run_research_agent(task)
    
    # Step 2: Qwen reads the files and writes the code blocks
    run_coding_agent()
    
    print(f"🏁 Multi-Agent Pipeline Completed successfully in {round(time.time() - start_time, 2)} seconds!")
Use code with caution.

⚠️ Pro-Tips for Optimizing this Framework on Your Machine

1. Leverage the Idle Timeout: By default, Ollama keeps a model cached in VRAM for 5 minutes after a request completes. When switching models sequentially, this means the next model has to wait for the old one to time out or force it out, creating a small delay. You can force an instant memory wipe by passing a keep-alive termination signal to Ollama via the API or terminal right before switching:bash
curl http://localhost:11434/api/generate -d '{"model": "deepseek-r1:70b", "keep_alive": 0}'
Use code with caution.
2. Use Markdown Tags as State Boundaries: In Module 5 (Patterns for Highly Autonomous Agents), you will learn that agents cooperate best when file formats are highly predictable. Force your DeepSeek agent to use exact headers (e.g., # Business Logic, # Constraints) so that your Qwen agent can easily parse out the target blocks without reading unstructured conversational filler.
Would you like help extending this script to include a Module 2 Reflection Loop, where a third agent executes the script, catches any errors, and passes the terminal logs back to the models to debug themselves automatically?

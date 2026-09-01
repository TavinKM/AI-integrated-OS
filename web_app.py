import os
import sys
import requests
from pathlib import Path

from flask import Flask, request, jsonify, render_template_string

# Add app root for imports
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from main import Neo4jGraphQuery, CommandGenerator
from shell_session import ShellSession
import command_history

app = Flask(__name__)

# Initialized on first request or at startup (see init_app())
_graph = None
_generator = None
_shell = None


def init_app():
    """initialize required services"""
    global _graph, _generator, _shell
    if _graph is not None:
        return
    workdir = os.getenv("AGENT_WORKDIR")
    _graph = Neo4jGraphQuery()
    _generator = CommandGenerator(_graph, model=os.getenv("LLM_MODEL"))
    _shell = ShellSession(cwd=workdir) if workdir else ShellSession()
    # same as main
    try:
        resp = requests.get(f"{_generator.llm_base}/models", timeout=5)
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            model_ids = [m.get("id", "") for m in data]
            target = _generator.model
            match = next(
                (m for m in model_ids if m == target or (target and (m.endswith("/" + target) or target in m))),
                None,
            )
            if match:
                _generator.model = match
            elif model_ids:
                _generator.model = model_ids[0]
    except requests.exceptions.RequestException:
        pass


@app.route("/")
def index():
    return render_template_string(INDEX_HTML)

#get working directory
@app.route("/api/workspace")
def api_workspace():
    init_app()
    cwd = _shell.get_cwd()
    try:
        names = os.listdir(cwd)
    except OSError as e:
        return jsonify({"cwd": cwd, "entries": [], "error": str(e)}), 200
    entries = []
    for name in sorted(names):
        if name.startswith("."):
            continue
        full = os.path.join(cwd, name)
        entries.append({"name": name, "type": "dir" if os.path.isdir(full) else "file"})
    return jsonify({"cwd": cwd, "entries": entries})


def _redirect_target_and_preview(command: str, cwd: str) -> dict | None:
    """If command writes to a file (>> or >), return {path, content} for a safe preview."""
    import re
    m = re.search(r'(?:>>|>)\s*([^\s&|;]+)', command)
    if not m:
        return None
    raw = m.group(1).strip().strip('"\'')
    if not raw or raw in ("/dev/null", "/dev/stderr", "/dev/stdout"):
        return None
    path = os.path.normpath(os.path.join(cwd, raw))
    if not os.path.abspath(path).startswith(os.path.abspath(cwd)):
        return None
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(8192)
        if len(content) >= 8192:
            content += "\n... (truncated)"
        return {"path": path, "content": content}
    except OSError:
        return None


@app.route("/api/generate", methods=["POST"])
def api_generate():
    init_app()
    data = request.get_json() or {}
    query = (data.get("query") or "").strip()
    run_command = data.get("run", True)
    # In safe mode we always require graph grounding
    use_graph = True
    if not query:
        return jsonify({"error": "query is required"}), 400
    shell_context = _shell.get_context()
    recent = command_history.get_recent(10)
    command = _generator.generate_command(
        query, shell_context=shell_context, recent_history=recent, use_graph=use_graph
    )
    stdout, stderr, exit_code = "", "", 0
    file_preview = None
    if run_command and command and not command.startswith("#"):
        stdout, stderr, exit_code = _shell.run(command)
        file_preview = _redirect_target_and_preview(command, _shell.get_cwd())
        command_history.record(
            query=query,
            command=command,
            cwd=_shell.get_cwd(),
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
        )
    return jsonify({
        "command": command,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "file_preview": file_preview,
    })


def run_server():
    host = os.getenv("GUI_HOST", "0.0.0.0")
    port = int(os.getenv("GUI_PORT", "5000"))
    app.run(host=host, port=port, debug=False, threaded=True)


# Web template, used colours from onedark scheme
INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Desktop Agent</title>
  <style>
    :root { --bg: #abb2bf; --surface: #f2f4f5; --text: #282c34; --muted: #636d83; --accent: #282c34; --green: #9ece6a; --red: #f7768e; }
    * { box-sizing: border-box; }
    body { font-family: ui-monospace, monospace; background: var(--bg); color: var(--text); margin: 0; min-height: 100vh; }
    .container { max-width: 960px; margin: 0 auto; padding: 1rem; display: grid; gap: 1rem; grid-template-rows: auto 1fr auto; height: 100vh; }
    h1 { margin: 0; font-size: 1.25rem; color: var(--accent); }
    .workspace { background: var(--surface); border-radius: 8px; padding: 0.75rem; overflow: auto; }
    .workspace h2 { margin: 0 0 0.5rem; font-size: 0.9rem; color: var(--muted); }
    .workspace .cwd { font-size: 0.8rem; color: var(--muted); margin-bottom: 0.5rem; word-break: break-all; }
    .workspace ul { list-style: none; padding: 0; margin: 0; }
    .workspace li { padding: 0.2rem 0; display: flex; align-items: center; gap: 0.5rem; font-size: 0.9rem; }
    .workspace li.dir::before { content: "📁"; }
    .workspace li.file::before { content: "📄"; }
    .output-panel { background: var(--surface); border-radius: 8px; padding: 0.75rem; overflow: auto; }
    .output-panel h2 { margin: 0 0 0.5rem; font-size: 0.9rem; color: var(--muted); }
    .output-panel pre { margin: 0; white-space: pre-wrap; word-break: break-all; font-size: 0.85rem; }
    .output-panel .command { color: var(--green); }
    .output-panel .stderr { color: var(--red); }
    .input-row { display: flex; gap: 0.5rem; align-items: center; }
    .input-row input { flex: 1; padding: 0.6rem; border: 1px solid var(--muted); border-radius: 6px; background: var(--surface); color: var(--text); font: inherit; }
    .input-row button { padding: 0.6rem 1rem; background: var(--accent); color: var(--bg); border: none; border-radius: 6px; cursor: pointer; font: inherit; }
    .input-row button:disabled { opacity: 0.6; cursor: not-allowed; }
    .loading { color: var(--muted); }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>Desktop Agent</h1>
      <div class="input-row">
        <input type="text" id="query" placeholder="Describe what you want to do (e.g. list files, create a folder)..." autocomplete="off">
        <button id="generate">Generate & run</button>
      </div>
    </header>
    <section class="workspace">
      <h2>Workspace</h2>
      <div class="cwd" id="workspace-cwd"></div>
      <ul id="workspace-list"></ul>
    </section>
    <section class="output-panel">
      <h2>Generated command & output</h2>
      <pre id="output">(generated command and output will appear here)</pre>
    </section>
  </div>
  <script>
    const outputEl = document.getElementById('output');
    const queryEl = document.getElementById('query');
    const btn = document.getElementById('generate');
    const cwdEl = document.getElementById('workspace-cwd');
    const listEl = document.getElementById('workspace-list');

    function setOutput(text, className) {
      outputEl.textContent = text || '(no output)';
      outputEl.className = className || '';
    }

    async function refreshWorkspace() {
      try {
        const r = await fetch('/api/workspace');
        const d = await r.json();
        cwdEl.textContent = d.cwd || '';
        listEl.innerHTML = (d.entries || []).map(e => {
          const li = document.createElement('li');
          li.className = e.type;
          li.textContent = e.name;
          return li;
        }).map(li => li.outerHTML).join('');
      } catch (e) {
        cwdEl.textContent = '';
        listEl.innerHTML = '<li class="loading">Failed to load workspace</li>';
      }
    }

    async function generate() {
      const query = queryEl.value.trim();
      if (!query) return;
      btn.disabled = true;
      setOutput('Generating command...', 'loading');
      try {
        const r = await fetch('/api/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query, run: true })
        });
        const d = await r.json();
        if (!r.ok) {
          setOutput(d.error || 'Request failed');
          return;
        }
        let parts = [];
        parts.push('Command:\\n' + (d.command || '(none)'));
        if (d.stdout) parts.push('\\nResult (command output):\\n' + d.stdout);
        if (d.stderr) parts.push('\\nStderr (from command):\\n' + d.stderr);
        if (d.file_preview) parts.push('\\nPreview of written file (' + d.file_preview.path + '):\\n' + d.file_preview.content);
        if (d.exit_code !== undefined && d.exit_code !== 0) parts.push('\\n(exit code ' + d.exit_code + ')');
        setOutput(parts.join(''), 'command');
        await refreshWorkspace();
      } catch (e) {
        setOutput('Error: ' + e.message);
      } finally {
        btn.disabled = false;
      }
    }

    btn.addEventListener('click', generate);
    queryEl.addEventListener('keydown', e => { if (e.key === 'Enter') generate(); });
    refreshWorkspace();
  </script>
</body>
</html>
"""

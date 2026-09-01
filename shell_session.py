import os
import subprocess
from typing import Optional, Tuple


class ShellSession:
    """
    Persistent shell session: tracks current working directory and runs commands
    in that context. Gives the model a terminal it can query and run commands in.
    """
    def __init__(self, cwd: Optional[str] = None):
        # Default to current process cwd if no explicit workdir is provided
        self.cwd = os.path.abspath(cwd or os.getcwd())
        # Ensure the directory exists so commands and files are persisted there
        os.makedirs(self.cwd, exist_ok=True)

    def get_cwd(self) -> str:
        return self.cwd

    def list_dir(self, path: Optional[str] = None) -> str:
        # default to current directory
        target = path if path is not None else self.cwd
        target = os.path.abspath(target) if not os.path.isabs(target) else target
        result = subprocess.run(
            ["ls", "-la", target],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return result.stderr or f"ls exited {result.returncode}"
        return result.stdout.strip()

    def run(self, cmd: str) -> Tuple[str, str, int]:
        # need special case for cd since its technically a bash command
        cmd = cmd.strip()
        if not cmd:
            return "", "", 0
        if self._is_cd(cmd):
            self._do_cd(cmd)
            return f"(changed directory to {self.cwd})", "", 0
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=self.cwd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.stdout or "", result.stderr or "", result.returncode

    def _is_cd(self, cmd: str) -> bool:
        #check first argument
        parts = cmd.split()
        if not parts or parts[0] != "cd":
            return False
        return True

    def _do_cd(self, cmd: str) -> None:
        # 
        parts = cmd.split(maxsplit=1)
        if len(parts) == 1 or not parts[1].strip():
            self.cwd = os.path.expanduser("~")
        else:
            target = parts[1].strip()
            if target == "-":
                self.cwd = os.environ.get("OLDPWD", self.cwd)
            else:
                resolved = os.path.abspath(os.path.join(self.cwd, target))
                if os.path.isdir(resolved):
                    self.cwd = resolved

    def get_context(self) -> dict:
        """Return cwd and listing for injection into the model prompt."""
        return {
            "cwd": self.get_cwd(),
            "listing": self.list_dir(),
        }

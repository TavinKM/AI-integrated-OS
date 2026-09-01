import os

from shell_session import ShellSession
import command_history


def run_interactive_agent(generator):
    """
    Run the interactive command-generation loop.
    generator: CommandGenerator instance (from main).
    """
    workdir = os.getenv("AGENT_WORKDIR")
    shell = ShellSession(cwd=workdir) if workdir else ShellSession()
    print("Enter your request (or 'quit' to exit). Commands run in a real shell.")
    print(f"Shell cwd: {shell.get_cwd()}")
    while True:
        try:
            user_input = input("\n> ").strip()
            if not user_input:
                continue
            if user_input.lower() in ["quit", "exit", "q"]:
                print("\nGoodbye!")
                break
            shell_context = shell.get_context()
            recent = command_history.get_recent(10)
            # In safe mode we always require graph grounding.
            command = generator.generate_command(
                user_input, shell_context=shell_context, recent_history=recent, use_graph=True
            )
            print(f"\nGenerated Command:")
            print(f"   {command}")
            if command.startswith("#"):
                print()
                continue
            stdout, stderr, code = shell.run(command)
            command_history.record(
                query=user_input,
                command=command,
                cwd=shell.get_cwd(),
                stdout=stdout,
                stderr=stderr,
                exit_code=code,
            )
            if stdout:
                print(f"\nOutput:\n{stdout}")
            if stderr:
                print(f"Stderr:\n{stderr}")
            if code != 0:
                print(f"Exit code: {code}")
            print()
        except (EOFError, KeyboardInterrupt):
            print("\n\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}")

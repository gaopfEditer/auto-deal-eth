import subprocess
import shutil

agent = (
    "openclaw acp --url ws://127.0.0.1:18789 "
    "--token 7d18c652bc2282d424bb4071f6ec3daec4c7b7f2781d8bb5 "
    "--session agent:main:main"
)

# A: list + npx.cmd
npx = shutil.which("npx.cmd")
cmd_a = [npx, "acpx@latest", "--format", "quiet", "--approve-all", "--timeout", "90", "--agent", agent, "exec", "ping"]
r = subprocess.run(cmd_a, capture_output=True, text=True, errors="replace")
print("A list npx.cmd rc=", r.returncode, "out=", (r.stdout or "")[:120])

# B: shell string
cmd_b = f'npx acpx@latest --format quiet --approve-all --timeout 90 --agent "{agent}" exec ping'
r = subprocess.run(cmd_b, capture_output=True, text=True, errors="replace", shell=True)
print("B shell rc=", r.returncode, "out=", (r.stdout or "")[:120])

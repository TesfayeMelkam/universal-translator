"""Poor man's pyflakes: report names that are used but never imported/defined anywhere in the file.
Catches typos and missing imports. (Install pyflakes for the full check: pip install pyflakes)"""
import ast
import builtins
import sys
from pathlib import Path

bad = 0
for path in sys.argv[1:] or [str(p) for p in Path("ai_services").rglob("*.py")]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    bound = set(dir(builtins)) | {"__file__", "__name__"}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(n.name)
            if not isinstance(n, ast.ClassDef):
                a = n.args
                for arg in a.args + a.kwonlyargs + a.posonlyargs + [x for x in (a.vararg, a.kwarg) if x]:
                    bound.add(arg.arg)
        elif isinstance(n, ast.Lambda):
            for arg in n.args.args + n.args.kwonlyargs:
                bound.add(arg.arg)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for al in n.names:
                bound.add((al.asname or al.name).split(".")[0])
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            bound.add(n.id)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            bound.add(n.name)
        elif isinstance(n, ast.arg):
            bound.add(n.arg)
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in bound:
            print(f"{path}:{n.lineno}: undefined name '{n.id}'")
            bad += 1
print("name check:", "FAILED" if bad else "ok")
sys.exit(1 if bad else 0)

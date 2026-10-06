import importlib, sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
mods = sys.argv[1:] or ["s01_inventory"]
for m in mods:
    mod, _, fn = m.partition(":")
    s = getattr(importlib.import_module(mod), fn or "build")()
    print(s.write(), len(s.turns), "turns", len(s.files), "files")

"""
tools/i18n_check.py
-------------------
Ceviri denetimi. Koddaki tum _t("...") metinlerini toplar, locales/*.json ile karsilastirir.

  python tools/i18n_check.py                 -> her dil icin eksik / kullanilmayan / hatali ceviriler
  python tools/i18n_check.py --template de-DE -> locales/de-DE.json sablonu (eksikler bos "")
                                                 (var olan ceviriler korunur)

Kurallar: arayuzdeki her metin _t("Turkce metin") ile yazilir; degisken iceren metin
yer tutuculu: _t("{n} sayfa eklendi", n=5). Ceviride {yer tutucular} ve \\t aynen kalmali.
Bos ("") ceviri = henuz cevrilmedi, Turkcesi gorunur.
"""
import ast
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCALES = os.path.join(ROOT, "locales")
PH = re.compile(r"\{\w+\}")


def code_keys():
    keys = {}
    for f in sorted(os.listdir(ROOT)):
        if not f.endswith(".py"):
            continue
        tree = ast.parse(open(os.path.join(ROOT, f), encoding="utf-8").read())
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_t" and n.args:
                a = n.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    keys.setdefault(a.value, f"{f}:{n.lineno}")
                else:
                    print(f"UYARI {f}:{n.lineno}: _t() sabit olmayan metinle cagrilmis (cevrilemez)")
    return keys


def check():
    keys = code_keys()
    print(f"kodda {len(keys)} cevrilecek metin")
    ok = True
    for fn in sorted(os.listdir(LOCALES)):
        if not fn.endswith(".json"):
            continue
        data = json.load(open(os.path.join(LOCALES, fn), encoding="utf-8"))
        tr = {k: v for k, v in data.items() if not k.startswith("@")}
        missing = [k for k in keys if not tr.get(k)]
        unused = [k for k in tr if k not in keys]
        bad = [k for k, v in tr.items() if v and (sorted(PH.findall(k)) != sorted(PH.findall(v))
                                                 or k.count("\t") != v.count("\t"))]
        print(f"\n{fn}: {len(tr) - len(unused) - sum(1 for k in keys if k in tr and not tr[k])}/{len(keys)} cevrili")
        for title, items in (("EKSIK", missing), ("KULLANILMAYAN", unused), ("YER TUTUCU/SEKME HATASI", bad)):
            if items:
                ok = False
                print(f"  {title} ({len(items)}):")
                for k in items[:40]:
                    print(f"    {keys.get(k, '-'):28s} {k[:80]!r}")
                if len(items) > 40:
                    print(f"    ... ve {len(items) - 40} tane daha")
    return ok


def template(code):
    keys = code_keys()
    path = os.path.join(LOCALES, code + ".json")
    old = json.load(open(path, encoding="utf-8")) if os.path.isfile(path) else {}
    out = {"@dil": old.get("@dil", code), "@not": "Anahtar: Turkce kaynak metin. Bos ceviri Turkce gorunur."}
    out.update({k: old.get(k, "") for k in sorted(keys)})
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{path}: {sum(1 for k in keys if not out[k])} bos ceviri")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) >= 3 and sys.argv[1] == "--template":
        template(sys.argv[2])
    else:
        sys.exit(0 if check() else 1)

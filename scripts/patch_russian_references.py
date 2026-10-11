#!/usr/bin/env python3
"""Apply reviewed additive definitions and a model-name typo to the AI-fixed BIG."""
import argparse
import hashlib
from pathlib import Path
import re

from big_archive import payloads, replace_payloads

BASE_COMMIT = "670b62f10f39ffe9016fa7f4e529816fa08ef460"
SOURCE_SHA256 = "83c6616cbf7a45f0979edebd34d22a157d76751d03359bf62e62ca184d92bb25"
ROOT = Path(__file__).resolve().parents[1]
APPENDS = {
    "data/ini/commandset.ini": ("CommandSet.ini", "CommandSet"),
    "data/ini/specialpower.ini": ("SpecialPower.ini", "SpecialPower"),
    "data/ini/objectcreationlist.ini": ("ObjectCreationList.ini", "ObjectCreationList"),
}
MISHKA = "data/ini/object/russia/vehicles/mishka.ini"
CHANGED_PATHS = {*APPENDS, MISHKA}


def declarations(data, kind):
    pattern = rb"(?mi)^" + kind.encode() + rb"[ \t]+([^\s;=]+)"
    return [m.decode("ascii").lower() for m in re.findall(pattern, data)]


def patch(data):
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError("refusing to patch an unexpected baseline archive")
    old = payloads(data)
    changed = {}
    for target, (filename, kind) in APPENDS.items():
        addition = (ROOT / "repairs" / filename).read_bytes()
        names = declarations(addition, kind)
        existing = [name for path, contents in old.items() if path.endswith(".ini")
                    for name in declarations(contents, kind)]
        if not names or len(set(names)) != len(names) or set(names) & set(existing):
            raise ValueError("missing or duplicate repair definition")
        original = old[target]
        newline = b"\r\n" if b"\r\n" in original else b"\n"
        addition = addition.replace(b"\r\n", b"\n").replace(b"\n", newline)
        changed[target] = original + newline * 2 + addition
    original = old[MISHKA]
    if original.count(b"RVMishka_U_D") != 1:
        raise ValueError("unexpected Mishka damaged-armor reference")
    changed[MISHKA] = original.replace(b"RVMishka_U_D", b"RVMishka_UD")
    result = replace_payloads(data, changed)
    actual = payloads(result)
    if set(old) != set(actual) or {p for p in old if old[p] != actual[p]} != CHANGED_PATHS:
        raise ValueError("unexpected archived-file change")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("input and output paths must differ")
    output = patch(args.input.read_bytes())
    args.output.write_bytes(output)
    print("PASS: four entries repaired; 618 payloads byte-identical to the AI-fixed baseline")
    print("SHA256", hashlib.sha256(output).hexdigest())


if __name__ == "__main__":
    main()

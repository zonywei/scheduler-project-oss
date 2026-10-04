from importlib import metadata


REQUIRED = {
    "ortools": "9.15.6755",
    "pandas": "2.3.2",
    "openpyxl": "3.1.5",
    "PyYAML": "6.0.3",
}


def main() -> None:
    for pkg, expected in REQUIRED.items():
        actual = metadata.version(pkg)
        assert actual == expected, f"{pkg} version mismatch: {actual} != {expected}"
    print("test_requirements_min: PASS")

if __name__ == "__main__":
    raise SystemExit(main())

"""make_dep, shared by several test modules.

Not in conftest.py: without __init__.py every conftest.py imports as bare
"conftest", so `from conftest import X` depends on import order."""


def make_dep(name, version, alias=None, repository="@example", condition=None):
    dep = {"name": name, "version": version, "repository": repository}
    if alias:
        dep["alias"] = alias
    if condition:
        dep["condition"] = condition
    return dep

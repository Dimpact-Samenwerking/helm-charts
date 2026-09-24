"""make_dep, shared by test_matching.py/test_images_manifest.py/
test_image_digests.py — deliberately NOT in conftest.py: pytest gives every
conftest.py the same bare module name "conftest" when a test directory has
no __init__.py, so a plain `from conftest import X` only works by accident
of import order and breaks the moment any other conftest.py in the whole
test tree happens to get imported first under that same name (as adding a
new, unrelated test directory once did). A uniquely-named module has no
such collision."""


def make_dep(name, version, alias=None, repository="@example", condition=None):
    dep = {"name": name, "version": version, "repository": repository}
    if alias:
        dep["alias"] = alias
    if condition:
        dep["condition"] = condition
    return dep

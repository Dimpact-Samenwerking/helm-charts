"""PodiumD: queue Open Archiefbeheer's process_review_response only after the
request's transaction commits (open-archiefbeheer#1103). Remove once upstream
uses transaction.on_commit there."""
import importlib.abc
import sys

_TARGET = "openarchiefbeheer.destruction.api.serializers"


class _DelayOnCommit:
    def __init__(self, task):
        self._task = task

    def delay(self, *args, **kwargs):
        from django.db import transaction

        transaction.on_commit(lambda: self._task.delay(*args, **kwargs))

    def __getattr__(self, name):
        return getattr(self._task, name)


class _Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name != _TARGET:
            return None
        sys.meta_path.remove(self)
        try:
            from importlib.util import find_spec

            spec = find_spec(name)
        finally:
            sys.meta_path.insert(0, self)
        if spec is None or spec.loader is None:
            return spec
        exec_module = spec.loader.exec_module

        def patched(module):
            exec_module(module)
            module.process_review_response = _DelayOnCommit(module.process_review_response)

        spec.loader.exec_module = patched
        return spec


sys.meta_path.insert(0, _Finder())

# PodiumD chart documentation

Operator- and maintainer-facing documentation for the `podiumd` umbrella
chart. For an upgrade, start with [Upgrading](_UPGRADING.md); the folder
layout is described in [Documentation structure](_README.MD).

```{toctree}
:caption: Upgrading
:maxdepth: 1

_UPGRADING
_README
```

```{toctree}
:caption: Upgrade paths
:maxdepth: 1
:glob:
:reversed:

_UPGRADE_PATHS/*
```

```{toctree}
:caption: Applications
:maxdepth: 1
:glob:

apps/_APP-DOCS-PATTERN
apps/**
```

```{toctree}
:caption: Architecture
:maxdepth: 1
:glob:

architecture/README
architecture/*
```

```{toctree}
:caption: Images
:maxdepth: 1

images/acr-mirror-naming
```

```{toctree}
:caption: Miscellaneous
:maxdepth: 1
:glob:

misc/*
```

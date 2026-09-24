"""Image-handling modules for a single podiumd chart: digest/tag
verification and upgrade checks (digests, upgrade_check, upgrade_cache),
value pin updates (version), doc generation for a shared image
basename's own bump (docs), and template/values.yaml image-reference
conventions (references_check, repository_check). Grouped here by
naming convention, not by shared origin — each was always its own
independent module, never split out of one bigger file."""

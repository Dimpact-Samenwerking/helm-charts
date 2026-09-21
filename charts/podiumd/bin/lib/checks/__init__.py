"""verify-podiumd's individual, independent checks: cve, cve_diff,
dead_values, digest_pinning, dry, helm_docs, kubeconform, kube_score,
lockstep, markdown, node_selector, shellcheck, vendored_tgz, yamllint.
Grouped here by naming convention (each was already its own
independent module, sharing a "_check" suffix), not by shared origin —
same treatment as lib/image/, not a split-remnant cleanup like
lib/chart/ or lib/upgradedoc/."""

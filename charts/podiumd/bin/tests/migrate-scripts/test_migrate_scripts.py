"""The other charts/podiumd/scripts/migrate-*.py: one migration each, and a second run changes nothing.

A start for these scripts: each case is the smallest input the script migrates.
"""

from collections.abc import Callable
from types import ModuleType

import pytest

ECK_BEFORE = """\
kiss-eck:
  eck-elasticsearch:
    nodeSets:
      - name: default
        count: 1
"""
ECK_AFTER = (
    ECK_BEFORE
    + """\
        podTemplate:
          spec:
            containers:
              - name: elasticsearch
                resources:
                  requests:
                    cpu: 250m
                    memory: 2Gi
                  limits:
                    cpu: 2000m
                    memory: 2Gi
"""
)

OPENFORMS_AFTER = """\
openformulieren:
  configuration:
    data: |
      objects_api:
        groups:
          - identifier: objecten
            name: Objecten
"""
OPENFORMS_BEFORE = OPENFORMS_AFTER + "            catalogue_domain: ALG\n" + '            catalogue_rsin: "123456789"\n'

OPENINWONER_BEFORE = """\
openinwoner:
  configuration:
    data: |
      oidc_db_config_admin_auth:
        items:
          - identifier: admin-oidc
            enabled: true
            oidc_rp_client_id: openinwoner
            oidc_rp_client_secret: REP_SECRET_REP
            endpoint_config:
              oidc_op_discovery_endpoint: https://keycloak.example.nl/realms/podiumd/
            username_claim:
              - preferred_username
"""
OPENINWONER_AFTER = """\
openinwoner:
  configuration:
    data: |
      oidc_db_config_admin_auth:
        providers:
          - identifier: admin-oidc-provider
            endpoint_config:
              oidc_op_discovery_endpoint: https://keycloak.example.nl/realms/podiumd/
        items:
          - identifier: admin-oidc
            enabled: true
            oidc_rp_client_id: openinwoner
            oidc_rp_client_secret: REP_SECRET_REP
            options:
              user_settings:
                claim_mappings:
                  username:
                    - preferred_username
                  email:
                    - email
                  first_name:
                    - given_name
                  last_name:
                    - family_name
              groups_settings:
                claim_mapping:
                  - roles
                sync: true
                sync_pattern: '*'
                make_users_staff: false
                superuser_group_names: []
                default_groups: []
            oidc_provider_identifier: admin-oidc-provider
"""

GATEWAY_BEFORE = """\
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: zac
spec:
  rules:
    - backendRefs:
        - name: zac
          port: 80
"""
GATEWAY_AFTER = (
    GATEWAY_BEFORE
    + """\
      filters:
        - type: ResponseHeaderModifier
          responseHeaderModifier:
            set:
              - name: Strict-Transport-Security
                value: max-age=31536000
              - name: X-Content-Type-Options
                value: nosniff
"""
)


@pytest.mark.parametrize(
    ("file_name", "before", "after", "notes"),
    [
        (
            "migrate-eck-resources-4.10.0.py",
            ECK_BEFORE,
            ECK_AFTER,
            ["kiss-eck.eck-elasticsearch.nodeSets[default]: elasticsearch resources"],
        ),
        (
            "migrate-openforms-4.0-api-groups.py",
            OPENFORMS_BEFORE,
            OPENFORMS_AFTER,
            [
                "objects_api.groups[0] (objecten): removed catalogue_domain: 'ALG'",
                "objects_api.groups[0] (objecten): removed catalogue_rsin: '123456789'",
            ],
        ),
        (
            "migrate-openinwoner-admin-oidc.py",
            OPENINWONER_BEFORE,
            OPENINWONER_AFTER,
            ["admin-oidc: provider admin-oidc-provider added", "admin-oidc: flat fields moved to options"],
        ),
        ("migrate-gateway-security-headers.py", GATEWAY_BEFORE, GATEWAY_AFTER, ["zac: added"]),
    ],
)
def test_migrates_once(script: Callable[[str], ModuleType], file_name: str, before: str, after: str, notes: list[str]):
    migrate_text = script(file_name).migrate_text
    assert migrate_text(before) == (after, notes)
    assert migrate_text(after)[0] == after


def test_objecten_leaves_a_file_without_objecten_or_objecttypen(script: Callable[[str], ModuleType]):
    text = "zac:\n  enabled: true\n"
    assert script("migrate-objecten-4.1.0.py").migrate_text(text, None) == (text, [])

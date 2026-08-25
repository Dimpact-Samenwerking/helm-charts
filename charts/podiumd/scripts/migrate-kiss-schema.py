#!/usr/bin/env python3
"""
Migrate KISS configuration from KISS 1.x (PodiumD <=4.4.x) schema
to KISS 2.x (PodiumD 4.5+) schema.

Usage:
    # Dry-run (print result, do not write):
    python migrate-kiss-schema.py values.yaml --dry-run

    # Migrate in-place:
    python migrate-kiss-schema.py values.yaml

    # Write to new file:
    python migrate-kiss-schema.py values.yaml -o values-migrated.yaml

Requires: ruamel.yaml (pip install ruamel.yaml)
Falls back to PyYAML if ruamel is not available (comments will be lost).
"""

import sys
import argparse
import io

try:
    from ruamel.yaml import YAML as RuamelYAML
    _USE_RUAMEL = True
except ImportError:
    _USE_RUAMEL = False
    try:
        import yaml as _pyyaml
    except ImportError:
        print("ERROR: Install ruamel.yaml or PyYAML: pip install ruamel.yaml", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get(d, *keys, default=None):
    """Safely traverse a nested dict."""
    for key in keys:
        if isinstance(d, dict) and key in d:
            d = d[key]
        else:
            return default
    return d


def _make_objecttype_url(objecttypen_base_url, uuid):
    """Build a full objecttype URL from base + UUID placeholder."""
    if objecttypen_base_url and uuid:
        base = objecttypen_base_url.rstrip('/')
        return f"{base}/api/v2/objecttypes/{uuid}"
    return ''


# ---------------------------------------------------------------------------
# Migration logic
# ---------------------------------------------------------------------------

def migrate_kiss(old):
    """
    Transform an old kiss dict (1.x) into the new kiss dict (2.x).
    Returns a plain Python dict; callers are responsible for re-serialising.
    """
    new = {}

    # -- configuration (unchanged) --
    if 'configuration' in old:
        new['configuration'] = dict(old['configuration'])

    # -- kiss.frontend.image → kiss.image --
    old_frontend_image = _get(old, 'frontend', 'image')
    if old_frontend_image:
        new['image'] = dict(old_frontend_image)
    elif 'image' in old:
        new['image'] = dict(old['image'])

    # -------------------------------------------------------------------------
    # kiss.settings
    # -------------------------------------------------------------------------
    settings = {}

    # brp → haalCentraal
    if 'brp' in old:
        brp = old['brp']
        settings['haalCentraal'] = {
            'apiKey': brp.get('apiKey', ''),
            'baseUrl': brp.get('baseUrl', ''),
        }

    # kvk  (fix: apikey → apiKey)
    if 'kvk' in old:
        kvk = old['kvk']
        settings['kvk'] = {
            'apiKey': kvk.get('apikey') or kvk.get('apiKey', ''),
            'baseUrl': kvk.get('baseUrl', ''),
        }

    # elastic  (drop image / nodeSelector / persistence; fill default baseUrl)
    if 'elastic' in old:
        e = old['elastic']
        baseurl = e.get('baseUrl') or 'https://kiss-es-http.podiumd.svc.cluster.local:9200'
        settings['elastic'] = {
            'baseUrl': baseurl,
            'password': e.get('password', ''),
            'username': e.get('username', 'elastic'),
        }

    # enterpriseSearch  (fix: privateApikey → privateApiKey; drop image/nodeSelector)
    if 'enterpriseSearch' in old:
        es = old['enterpriseSearch']
        baseurl = es.get('baseUrl') or 'https://kiss-ent-http.podiumd.svc.cluster.local:3002'
        settings['enterpriseSearch'] = {
            'baseUrl': baseurl,
            'privateApiKey': es.get('privateApikey') or es.get('privateApiKey', ''),
            'publicApiKey': es.get('publicApikey') or es.get('publicApiKey', ''),
            'engine': es.get('engine', 'kiss-engine'),
        }

    # database  (user → username; ensure port present)
    if 'database' in old:
        db = old['database']
        settings['database'] = {
            'port': db.get('port', 5432),
            'host': db.get('host', ''),
            'name': db.get('name', ''),
            'username': db.get('username') or db.get('user', ''),
            'password': db.get('password', ''),
        }

    # email → email + feedback
    if 'email' in old:
        em = old['email']
        settings['email'] = {
            'enableSsl': em.get('enableSsl', True),
            'host': em.get('host', ''),
            'port': em.get('port', 587),
        }
        settings['feedback'] = {
            'emailFrom': em.get('feedbackFrom') or em.get('emailFrom', ''),
            'emailTo': em.get('feedbackTo') or em.get('emailTo', ''),
        }

    # objecten + objecttypen → afdelingen / groepen / logboek  (settings side)
    old_objecten = old.get('objecten', {})
    old_objecttypen = old.get('objecttypen', {})
    objecten_baseurl = old_objecten.get('baseUrl', '')
    objecten_token = old_objecten.get('token', '')
    objecttypen_base = old_objecttypen.get('baseUrlIntern', '')

    def mkurl(uuid):
        return _make_objecttype_url(objecttypen_base, uuid)

    if old_objecten or old_objecttypen:
        settings['afdelingen'] = {
            'baseUrl': objecten_baseurl,
            'objectTypeUrl': mkurl(old_objecttypen.get('afdelingUUID', '')),
            'token': objecten_token,
        }
        settings['groepen'] = {
            'baseUrl': objecten_baseurl,
            'objectTypeUrl': mkurl(old_objecttypen.get('groepUUID', '')),
            'token': objecten_token,
        }
        # logboek is NEW in KISS 2.0  (Activiteitenlog, shared UUID with ITA)
        settings['logboek'] = {
            'baseUrl': objecten_baseurl,
            'objectTypeUrl': mkurl('REP_ITA_ACTIVITEITENLOG_UUID_REP'),
            'objectTypeVersion': 1,
            'token': objecten_token,
        }

    # managementApiKey → managementInformatie.apiKey
    if 'managementApiKey' in old:
        settings['managementInformatie'] = {'apiKey': old['managementApiKey']}

    # registers  (assembled from adapter + objecttypen UUIDs + esuite deeplink)
    old_adapter = old.get('adapter', {})
    old_esuite = old.get('esuite', {})
    adapter_baseurl = old_adapter.get('baseUrl', 'http://podiumd-adapter.podiumd.svc.cluster.local')
    adapter_client_id = old_adapter.get('clientId', 'contact_intern')
    adapter_secret = old_adapter.get('secret', '')

    esuite_base = old_esuite.get('baseUrl', '')
    if esuite_base and '/mp/zaak' not in esuite_base:
        deeplink_url = esuite_base.rstrip('/') + '/mp/zaak/'
    else:
        deeplink_url = esuite_base

    settings['registers'] = [{
        'isDefault': True,
        'contactmomenten': {
            'baseUrl': adapter_baseurl,
            'clientId': adapter_client_id,
            'clientSecret': adapter_secret,
        },
        'interneTaak': {
            'baseUrl': adapter_baseurl,
            'clientId': adapter_client_id,
            'clientSecret': adapter_secret,
            'objectTypeUrl': mkurl(old_objecttypen.get('interneTaakUUID', '')),
            'objectTypeVersion': 1,
        },
        'klanten': {
            'baseUrl': f"{adapter_baseurl}/klanten",
            'clientId': adapter_client_id,
            'clientSecret': adapter_secret,
        },
        'zaaksysteem': {
            'catalogiBaseUrl': f"{adapter_baseurl}/catalogi/api/v1",
            'clientId': adapter_client_id,
            'clientSecret': adapter_secret,
            'deeplink': {
                'property': 'identificatie',
                'url': deeplink_url,
            },
            'documentenBaseUrl': f"{adapter_baseurl}/documenten/api/v1",
            'useExperimentalQueries': False,
            'zakenBaseUrl': f"{adapter_baseurl}/zaken/api/v1",
        },
    }]

    # sync → syncJobs
    old_sync = old.get('sync', {})
    old_vac = old.get('vac', {})
    history_limit = old_sync.get('successfulJobsHistoryLimit', 1)

    if old_sync or old_vac:
        sync_jobs = {}

        if 'image' in old_sync:
            sync_jobs['image'] = dict(old_sync['image'])

        # kennisbank
        old_kb = old_sync.get('kennisbank', {})
        sync_jobs['kennisbank'] = {
            'baseUrl': objecten_baseurl,
            'historyLimit': history_limit,
            'objectTypeUrl': mkurl(old_objecttypen.get('kennisartikelUUID', '')),
            'schedule': old_kb.get('schedule', ''),
            'token': objecten_token,
        }

        # smoelenboek → medewerkers
        old_smurf = old_sync.get('smoelenboek', {})
        sync_jobs['medewerkers'] = {
            'baseUrl': adapter_baseurl,
            'historyLimit': history_limit,
            'objectTypeUrl': mkurl(old_objecttypen.get('medewerkerUUID', '')),
            'resources': {},
            'schedule': old_smurf.get('schedule', ''),
            'clientId': adapter_client_id,
            'clientSecret': adapter_secret,
        }

        # vac  (useVacs → manageFromKiss)
        old_vac_sync = old_sync.get('vac', {})
        vac_url = (old_vac.get('objectTypeUrl')
                   or mkurl(old_objecttypen.get('vacUUID', '')))
        sync_jobs['vac'] = {
            'manageFromKiss': bool(old_vac.get('useVacs', False)),
            'baseUrl': old_vac.get('objectenBaseUrl') or objecten_baseurl,
            'historyLimit': history_limit,
            'objectTypeUrl': vac_url,
            'objectTypeVersion': int(old_vac.get('objectTypeVersion', 1)),
            'schedule': old_vac_sync.get('schedule', ''),
            'token': old_vac.get('objectenToken') or objecten_token,
        }

        # domain → website  (only when enabled)
        old_domain = old_sync.get('domain', {})
        if old_domain.get('enabled', False) and old_domain.get('url'):
            sync_jobs['website'] = [{
                'sourceName': 'Website',
                'domain': old_domain['url'],
                'historyLimit': history_limit,
                'schedule': old_domain.get('schedule', ''),
            }]

        settings['syncJobs'] = sync_jobs

    # oidc  (secret → clientSecret; medewerkerIdentificatieClaim → medewerkerIdentificatie.claim)
    if 'oidc' in old:
        oidc = old['oidc']
        settings['oidc'] = {
            'authority': oidc.get('authority', ''),
            'clientId': oidc.get('clientId', ''),
            'clientSecret': oidc.get('secret') or oidc.get('clientSecret', ''),
            'medewerkerIdentificatie': {
                'claim': (oidc.get('medewerkerIdentificatieClaim')
                          or _get(oidc, 'medewerkerIdentificatie', 'claim', default='')),
            },
        }

    # organisatieIds: string → list
    if 'organisatieIds' in old:
        org_ids = old['organisatieIds']
        if isinstance(org_ids, str):
            settings['organisatieIds'] = [org_ids]
        elif isinstance(org_ids, list):
            settings['organisatieIds'] = list(org_ids)
        else:
            settings['organisatieIds'] = [str(org_ids)]

    new['settings'] = settings

    # -- nodeSelector (unchanged) --
    if 'nodeSelector' in old:
        new['nodeSelector'] = dict(old['nodeSelector'])

    # -------------------------------------------------------------------------
    # kiss.adapter  (add objecten / objecttypen / esuite sub-sections)
    # -------------------------------------------------------------------------
    adapter = {}
    for field in ('image', 'baseUrl', 'clientId', 'secret'):
        if field in old_adapter:
            val = old_adapter[field]
            adapter[field] = dict(val) if isinstance(val, dict) else val

    if old_objecten:
        adapter['objecten'] = {
            'baseUrl': old_objecten.get('baseUrl', ''),
            'token': old_objecten.get('token', ''),
        }

    if old_objecttypen:
        adapter['objecttypen'] = {
            'baseUrlIntern': old_objecttypen.get('baseUrlIntern', ''),
            'baseUrlExtern': old_objecttypen.get('baseUrlExtern', ''),
            'token': old_objecttypen.get('token', ''),
            'medewerkerUUID': old_objecttypen.get('medewerkerUUID', ''),
            'afdelingUUID': old_objecttypen.get('afdelingUUID', ''),
            'groepUUID': old_objecttypen.get('groepUUID', ''),
            'interneTaakUUID': old_objecttypen.get('interneTaakUUID', ''),
            'kennisartikelUUID': old_objecttypen.get('kennisartikelUUID', ''),
            'vacUUID': old_objecttypen.get('vacUUID', ''),
        }

    if old_esuite:
        # isDefault is removed — moved to registers
        adapter['esuite'] = {k: v for k, v in old_esuite.items() if k != 'isDefault'}

    new['adapter'] = adapter

    # -- alpine (unchanged) --
    if 'alpine' in old:
        new['alpine'] = dict(old['alpine'])

    return new


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _load(path):
    if _USE_RUAMEL:
        ry = RuamelYAML()
        ry.preserve_quotes = True
        ry.width = 4096
        with open(path, 'r', encoding='utf-8') as f:
            return ry, ry.load(f)
    else:
        with open(path, 'r', encoding='utf-8') as f:
            return None, _pyyaml.safe_load(f)


def _dump(ry, data, path=None):
    if _USE_RUAMEL:
        buf = io.StringIO()
        ry.dump(data, buf)
        text = buf.getvalue()
    else:
        text = _pyyaml.dump(data, default_flow_style=False, allow_unicode=True)

    if path:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
    else:
        sys.stdout.write(text)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Migrate KISS values from schema 1.x to 2.x (PodiumD 4.5+)'
    )
    parser.add_argument('input', help='Input values YAML file')
    parser.add_argument('-o', '--output', metavar='FILE',
                        help='Write output to FILE instead of overwriting input')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print the migrated YAML to stdout without writing any file')
    args = parser.parse_args()

    ry, data = _load(args.input)

    if 'kiss' not in data:
        print("No 'kiss' key found – nothing to migrate.", file=sys.stderr)
        sys.exit(1)

    # Detect whether already migrated (settings key is present)
    if 'settings' in data.get('kiss', {}):
        print("WARNING: kiss.settings already exists – the file may already be migrated.", file=sys.stderr)

    data['kiss'] = migrate_kiss(data['kiss'])

    if args.dry_run:
        _dump(ry, data, path=None)
    else:
        output_path = args.output or args.input
        _dump(ry, data, path=output_path)
        print(f"Migration complete → {output_path}")
        if not _USE_RUAMEL:
            print("Tip: install ruamel.yaml to preserve comments: pip install ruamel.yaml")


if __name__ == '__main__':
    main()

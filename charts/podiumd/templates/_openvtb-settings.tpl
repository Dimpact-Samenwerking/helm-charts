{{- /*
Django settings modules for Open VTB (IN-3500). Open VTB 0.2.0 has no switch
per API, so podiumd provides two settings modules on top of Open VTB's own
openvtb.conf.docker; openvtb.settings.djangoSettingsModule picks one:

- openvtb.conf.podiumd_berichten: only Berichten. /verzoeken/ and /taken/
  answer 404 before any authentication, and the beat's send-taken-events is
  disabled. The URLs themselves stay: Open VTB reverses their names at
  startup, so removing them would break every request.
- openvtb.conf.podiumd_all: every API, and send-taken-events enabled again.
  The beat keeps a task's enabled flag in its database, so going back to
  openvtb.conf.docker would leave it disabled.

The files are mounted into the openvtb.conf package: the framework derives
ROOT_URLCONF, the session cookie and the logging from the settings module's
package. Remove this file once Open VTB can switch its APIs off itself.
*/ -}}
{{- define "podiumd.openvtb.settingsFiles" -}}
podiumd_berichten.py: |
  # Rendered by podiumd (templates/_openvtb-settings.tpl).
  from django.http import HttpResponseNotFound

  from openvtb.conf.docker import *  # noqa: F403

  BLOCKED_PREFIXES = ("/verzoeken/", "/taken/")


  class BlockedPathsMiddleware:
      def __init__(self, get_response):
          self.get_response = get_response

      def __call__(self, request):
          if request.path_info.startswith(BLOCKED_PREFIXES):
              return HttpResponseNotFound()
          return self.get_response(request)


  MIDDLEWARE = ["openvtb.conf.podiumd_berichten.BlockedPathsMiddleware", *MIDDLEWARE]  # noqa: F405

  CELERY_BEAT_SCHEDULE = {  # noqa: F405
      **CELERY_BEAT_SCHEDULE,  # noqa: F405
      "send-taken-events": {**CELERY_BEAT_SCHEDULE["send-taken-events"], "enabled": False},  # noqa: F405
  }
podiumd_all.py: |
  # Rendered by podiumd (templates/_openvtb-settings.tpl).
  from openvtb.conf.docker import *  # noqa: F403

  CELERY_BEAT_SCHEDULE = {  # noqa: F405
      **CELERY_BEAT_SCHEDULE,  # noqa: F405
      "send-taken-events": {**CELERY_BEAT_SCHEDULE["send-taken-events"], "enabled": True},  # noqa: F405
  }
{{- end }}

{{- /* The volume's name carries a hash of the files, so the web, config, worker
     and beat pods roll when the code changes; the openvtb chart's own checksum
     only covers its ConfigMap and Secret. Named templates are global, so the
     openvtb chart's tpl of openvtb.extraVolumes can use it. */ -}}
{{- define "podiumd.openvtb.settingsVolume" -}}
podiumd-settings-{{ include "podiumd.openvtb.settingsFiles" . | sha256sum | trunc 10 }}
{{- end }}

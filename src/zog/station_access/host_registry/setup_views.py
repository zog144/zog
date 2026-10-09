from django.core.exceptions import ObjectDoesNotExist, RequestDataTooBig
from django.views.decorators.http import require_http_methods
from .views import administrator, body
from .identity_views import response
from .models import ProviderCredential, DnsProviderSelection
from . import setup_configuration as setup


def error_response(error):
    if isinstance(error,setup.Conflict):return response({'detail':str(error)},409)
    if isinstance(error,(ValueError,RequestDataTooBig)):return response({'detail':str(error) if isinstance(error,ValueError) else 'Request too large'},400)
    if isinstance(error,ObjectDoesNotExist):return response({'detail':'Configuration not found'},404)
    return response({'detail':'Configuration unavailable; check the protected vault and controller setup'},503)


@require_http_methods(['GET','POST'])
@administrator
def registries(request):
    try:
        if request.method=='POST':
            actor=f'{request.user.pk}:{request.user.get_username()}';data=body(request)
            if data.pop('action',None)=='select-dns':setup.select_dns(actor,data)
            else:setup.save_provider(actor,data)
        selection=DnsProviderSelection.objects.filter(pk=1).first()
        try:setup.vault.keyring();ready=True
        except Exception:ready=False
        return response({'registries':[setup.provider_metadata(r) for r in ProviderCredential.objects.order_by('label')],
                         'vault_ready':ready,'dns_selection':{'credential_id':str(selection.credential_id) if selection and selection.credential_id else '', 'revision':selection.revision if selection else 0}})
    except Exception as error:return error_response(error)


@require_http_methods(['GET','POST'])
@administrator
def deployments(request):
    try:
        if request.method=='POST':setup.save_destination(f'{request.user.pk}:{request.user.get_username()}',body(request))
        result=response(setup.export_destinations())
        if request.GET.get('download')=='1':result['Content-Disposition']='attachment; filename="beacon-destinations.json"'
        return result
    except Exception as error:return error_response(error)


@require_http_methods(['POST'])
@administrator
def provider_check(request, credential_id):
    from . import provider_checks
    try:
        data = body(request)
        if set(data) != {'revision'}:raise ValueError('Supply the displayed credential revision')
        result = provider_checks.run(f'{request.user.pk}:{request.user.get_username()}', credential_id, data['revision'])
        return response({'access_check': result})
    except provider_checks.CheckBusy as error:
        result = response({'detail': str(error)}, 429)
        result['Retry-After'] = '60'
        return result
    except Exception as error:return error_response(error)


@require_http_methods(['GET'])
@administrator
def readiness(request):
    from .readiness import snapshot
    try:return response(snapshot())
    except Exception:return response({'detail': 'Setup observations unavailable; retry or check the local database'}, 503)


@require_http_methods(['GET','POST'])
@administrator
def clouds(request):
    from . import cloud_configuration as cloud
    from .models import CloudCredential
    try:
        if request.method == 'POST':
            cloud.save(f'{request.user.pk}:{request.user.get_username()}', body(request))
        try: setup.vault.keyring(); ready=True
        except Exception: ready=False
        return response({'accounts':[cloud.metadata(row) for row in CloudCredential.objects.order_by('label')], 'vault_ready':ready})
    except Exception as error: return error_response(error)


@require_http_methods(['POST'])
@administrator
def cloud_check(request, credential_id):
    from . import cloud_configuration as cloud
    from .provider_checks import CheckBusy
    try:
        data=body(request)
        if set(data) != {'revision'}: raise ValueError('Supply the displayed credential revision')
        return response(cloud.check(f'{request.user.pk}:{request.user.get_username()}', credential_id, data['revision']))
    except CheckBusy as error:
        result=response({'detail':str(error)},429); result['Retry-After']='60'; return result
    except Exception as error: return error_response(error)

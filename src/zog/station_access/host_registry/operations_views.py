from django.views.decorators.http import require_POST
from django.core.exceptions import ObjectDoesNotExist, RequestDataTooBig
from .views import administrator,body
from .identity_views import response
from .identity import locked,audit
from .models import Host,StationCredential
from . import vault,mirror_roles

@require_POST
@administrator
def reveal(request,host_id):
    try:
        data=body(request)
        if set(data)!={'revision'} or type(data['revision']) is not int:raise ValueError()
        with locked():
            row=StationCredential.objects.get(host_id=host_id)
            if row.revision!=data['revision']:return response({'detail':'Credential changed; refresh host'},409)
            _,keys=vault.keyring();value=vault.decrypt(row,keys)
            audit(str(request.user.pk)+':'+request.user.get_username(),'reveal-station-login',host=row.host,revision=row.revision)
            result=response({'username':value['username'],'password':value['password'],'revision':row.revision})
            result['Pragma']='no-cache';result['X-Content-Type-Options']='nosniff';return result
    except ObjectDoesNotExist:return response({'detail':'Credential unavailable'},404)
    except (ValueError,RequestDataTooBig):return response({'detail':'Credential unavailable'},400)
    except Exception:return response({'detail':'Credential vault unavailable'},503)

@require_POST
@administrator
def mirror_role(request,host_id):
    try:
        data=body(request)
        if set(data)!={'selected','endpoint','revision'}:raise ValueError()
        row=mirror_roles.assign(str(request.user.pk)+':'+request.user.get_username(),host_id,data['selected'],data['endpoint'],data['revision'])
        return response({'mirror_role':mirror_roles.serialize(row.host)})
    except ObjectDoesNotExist:return response({'detail':'Host unavailable'},404)
    except (ValueError,TypeError,RequestDataTooBig):return response({'detail':'Role change rejected; approve the identity, check the HTTPS endpoint, and refresh before retrying'},400)
    except Exception:return response({'detail':'Role controller unavailable'},503)

from django.views.decorators.http import require_GET
from django.db import OperationalError
from . import retirement

@require_GET
@administrator
def removal_preview(request,host_id):
    try:
        with locked():return response(retirement.preview(Host.objects.get(pk=host_id)))
    except ObjectDoesNotExist:return response({'detail':'Host unavailable'},404)
    except OperationalError:return response({'detail':'Retry later'},503)

@require_POST
@administrator
def removal(request,host_id):
    try:
        data=body(request)
        if set(data)!={'action','revision','confirmed_host_id'} or data['confirmed_host_id']!=str(host_id):
            raise ValueError('Confirm the exact registry UUID')
        actor=str(request.user.pk)+':'+request.user.get_username()
        if data['action']=='archive':retirement.archive_host(actor,host_id,data['revision'])
        elif data['action']=='restore':retirement.restore_host(actor,host_id,data['revision'])
        else:raise ValueError('Choose archive or restore')
        return response({'saved':True})
    except retirement.RemovalConflict as error:return response({'detail':str(error)},409)
    except ObjectDoesNotExist:return response({'detail':'Host unavailable'},404)
    except (ValueError,TypeError,RequestDataTooBig):return response({'detail':'Invalid archival confirmation'},400)
    except OperationalError:return response({'detail':'Retry later'},503)

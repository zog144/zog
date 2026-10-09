from django.http import JsonResponse
from django.views.decorators.http import require_GET,require_POST
from django.core.exceptions import ObjectDoesNotExist,RequestDataTooBig
from django.db import IntegrityError
from zog.network_register.contracts import NetworkError
from .views import administrator,body
from .dns_reconcile import configuration
from .dns_destinations import configure
from .models import DnsDestination,ProviderCredential

@require_GET
@administrator
def destinations(request):
    rows=[]
    for d in DnsDestination.objects.filter(enabled=True):
        if d.selection['owner_user_id']!=request.user.pk:continue
        p=ProviderCredential.objects.filter(pk=d.selection['credential_id']).values_list('provider',flat=True).first()
        rows.append(dict(id=d.pk,prefix=d.selection['prefix'],provider=p))
    return JsonResponse({'destinations':rows})

@require_POST
@administrator
def assignment(request,host_id,binding_id):
    try:
        data=body(request)
        if set(data)-{'action','label','revision'}:raise ValueError('Invalid DNS change')
        if not isinstance(data.get('action'),str):raise ValueError('Supply an action')
        if data.get('action')!='reserve' and type(data.get('revision')) is not int:raise ValueError('Supply the current assignment revision')
        config=configuration()
        if not config:return JsonResponse({'detail':'DNS controller is not configured'},status=503)
        result=configure(config,binding_id,host_id,data['action'],actor_id=request.user.pk,label=data.get('label'),expected_revision=data.get('revision'))
        return JsonResponse({'dns':result})
    except ObjectDoesNotExist:return JsonResponse({'detail':'DNS assignment or destination not found'},status=404)
    except (NetworkError,IntegrityError,BlockingIOError) as error:
        return JsonResponse({'detail':'DNS change stopped: '+(error.code if isinstance(error,NetworkError) else 'conflict')},status=409)
    except (ValueError,UnicodeError,RequestDataTooBig):return JsonResponse({'detail':'Invalid DNS change'},status=400)
    except (OSError,KeyError):return JsonResponse({'detail':'DNS state unavailable'},status=503)

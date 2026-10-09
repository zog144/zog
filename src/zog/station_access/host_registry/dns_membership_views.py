from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.core.exceptions import RequestDataTooBig
from zog.network_register.contracts import NetworkError
from .views import administrator, body
from .dns_reconcile import configuration
from . import dns_membership

@require_POST
@administrator
def membership(request,host_id):
    try:
        value=body(request);config=configuration()
        if not config:return JsonResponse({'detail':'DNS controller is not configured'},status=503)
        if set(value)=={'review_id'}:
            result=dns_membership.commit(config,value['review_id'],actor_id=request.user.pk,resource_id=host_id)
        elif set(value)<= {'action','label'} and value.get('action') in ('reserve','release'):
            result=dns_membership.review(config,host_id,value['action'],value.get('label'),actor_id=request.user.pk)
        else:raise NetworkError('validation')
        return JsonResponse(result)
    except NetworkError as error:
        return JsonResponse({'detail':'DNS membership change stopped: '+error.code+'. Retain the review ID to resume.', 'code':error.code},status=403 if error.code=='permission' else 409)
    except BlockingIOError:
        return JsonResponse({'detail':'DNS controller is busy; retry shortly'},status=409)
    except (ValueError,TypeError,RequestDataTooBig):
        return JsonResponse({'detail':'Invalid DNS membership request'},status=400)
    except Exception:
        return JsonResponse({'detail':'DNS membership state unavailable. Preserve the review ID and inspect controller status.'},status=503)

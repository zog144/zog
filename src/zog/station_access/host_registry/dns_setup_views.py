from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.core.exceptions import ObjectDoesNotExist,RequestDataTooBig
from zog.network_register.contracts import NetworkError
from .views import administrator,body
from .dns_reconcile import configuration
from . import dns_setup as setup

@require_POST
@administrator
def change(request):
 try:
  data=body(request);action=data.get('action');owner=request.user.pk
  fields={'zones':{'action','credential_id','revision','cursor'},'review':{'action','credential_id','revision','zone_id','label'},'commit':{'action','review_id'},'inspect':{'action','binding_id'}}
  if action not in fields or set(data)-fields[action]:raise ValueError()
  if action=='zones':result=setup.zones(owner,data['credential_id'],data['revision'],data.get('cursor'))
  elif action=='review':result=setup.review(configuration(),owner,data['credential_id'],data['revision'],data['zone_id'],data['label'])
  elif action=='commit':result=setup.commit(configuration(),owner,data['review_id'])
  else:result=setup.inspect(configuration(),owner,data['binding_id'])
  return JsonResponse(result)
 except setup.Blocked as e:return JsonResponse(dict(detail=e.report()['message'],diagnostic=e.report()),status=409)
 except ObjectDoesNotExist:return JsonResponse(dict(detail='Saved credentials or destination no longer exist.',diagnostic=dict(stage='credentials',code='not-found',ready=False)),status=404)
 except NetworkError as e:return JsonResponse(dict(detail='DNS setup stopped. Refresh the review and check controller state.',diagnostic=dict(stage='controller',code=e.code,ready=False)),status=409)
 except (ValueError,TypeError,KeyError,UnicodeError,RequestDataTooBig):return JsonResponse(dict(detail='Invalid DNS setup request.'),status=400)
 except (OSError,BlockingIOError):return JsonResponse(dict(detail='DNS controller is busy or its durable state is unavailable. Retry or ask an operator to inspect it.'),status=503)

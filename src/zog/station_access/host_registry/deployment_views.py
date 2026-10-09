from django.core.exceptions import ObjectDoesNotExist, RequestDataTooBig, ValidationError
from django.db.models import Q
from django.views.decorators.http import require_http_methods
from .views import administrator, body
from .identity_views import response
from .models import DeploymentJob, Host
from . import deployment_jobs as jobs


@require_http_methods(['GET','POST'])
@administrator
def collection(request):
    try:
        if request.method=='POST':
            data=body(request);actor=f'{request.user.pk}:{request.user.get_username()}'
            if data.get('action')=='inspect' and set(data)=={'action','host_id','action_id'}:
                job=jobs.create_inspection(actor,data['host_id'],data['action_id'])
            elif data.get('action')=='review' and set(data)=={'action','host_id','inspection_id'}:
                job=jobs.preview(actor,data['host_id'],data['inspection_id'])
            else:raise ValueError('Choose inspect or review with the displayed host and inspection.')
            return response({'job':jobs.serialize(job)},201)
        hosts=[]
        for host in Host.objects.filter(archived_at__isnull=True).order_by('label')[:200]:
            try: jobs.target(host);eligible=True
            except ValueError:eligible=False
            hosts.append(dict(id=str(host.pk),label=host.label,eligible=eligible))
        return response({'enabled':jobs.enabled(),'hosts':hosts,'jobs':[jobs.serialize(j) for j in DeploymentJob.objects.select_related('host').filter(Q(state__in=jobs.BUSY)|Q(pk__in=DeploymentJob.objects.order_by('-created_at').values('pk')[:25])).order_by('-created_at')]})
    except ObjectDoesNotExist:return response({'detail':'Host or job not found.'},404)
    except (ValueError,TypeError,KeyError,AttributeError,RequestDataTooBig,ValidationError):return response({'detail':'Request could not be accepted. Refresh the host inspection and review; check that this host is enrolled, idle, and the primary registry remains enabled.'},409)


@require_http_methods(['POST'])
@administrator
def action(request,job_id):
    try:
        data=body(request)
        if set(data)!={'action','confirmed_job_id'} or data['confirmed_job_id']!=str(job_id):raise ValueError('Confirm the displayed job.')
        actor=f'{request.user.pk}:{request.user.get_username()}'
        if data['action']=='apply':job=jobs.confirm(actor,job_id)
        elif data['action']=='check-outcome':job=jobs.recover(actor,job_id)
        else:raise ValueError('Unsupported job action.')
        return response({'job':jobs.serialize(job)})
    except ObjectDoesNotExist:return response({'detail':'Job not found.'},404)
    except (ValueError,TypeError,KeyError,AttributeError,RequestDataTooBig,ValidationError):return response({'detail':'Review expired, configuration changed, or another host job is unresolved. Refresh and inspect before proceeding.'},409)

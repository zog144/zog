"""Administrator-only account management; no controller or runtime mutations."""
import json
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError, RequestDataTooBig
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.utils.crypto import salted_hmac, constant_time_compare
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods
from zog.station_access.models import ApplicationOwnership, VncWorkspace, VncAccessGrant
from .identity import locked, audit
from .identity_views import response
from .views import administrator, body

FIELDS = {'username', 'email', 'first_name', 'last_name', 'is_active', 'is_superuser'}


def revision(user):
    value={key:getattr(user,key) for key in sorted(FIELDS|{'id','password','is_staff'})}
    return salted_hmac('station-user-revision',json.dumps(value,sort_keys=True)).hexdigest()


def serialize(user):
    return dict({key:getattr(user,key) for key in sorted(FIELDS)},id=user.pk,revision=revision(user),
        date_joined=user.date_joined.isoformat(),last_login=user.last_login.isoformat() if user.last_login else None,
        workspace_count=user.vnc_workspaces.count(),application_count=user.owned_zog_applications.count())


def actor_now(request):
    actor=get_user_model().objects.get(pk=request.user.pk)
    if not actor.is_active or not actor.is_superuser:raise PermissionError()
    return actor


def revoke(user, current_session=None):
    # Inactive accounts must not regain old sessions if reactivated later.
    for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
        if session.session_key!=current_session and str(session.get_decoded().get('_auth_user_id'))==str(user.pk):session.delete()
    VncAccessGrant.objects.filter(user=user,revoked_at__isnull=True).update(revoked_at=timezone.now())


@sensitive_variables('data','password')
def save(request, data, user_id=None):
    with locked():
        actor=actor_now(request)
        if set(data)!=FIELDS|{'password'}|({'revision'} if user_id else set()):raise ValueError('Provide the displayed account fields only.')
        user=get_user_model().objects.get(pk=user_id) if user_id else get_user_model()()
        if user_id and not constant_time_compare(str(data['revision']),revision(user)):raise ValueError('Account changed. Refresh before saving.')
        was_active,was_admin=user.is_active,user.is_superuser
        for field in FIELDS:
            value=data[field]
            if field in ('is_active','is_superuser'):
                if type(value) is not bool:raise ValueError('Account status and role must be boolean.')
            elif not isinstance(value,str):raise ValueError('Account text fields must be strings.')
            else:value=value.strip()
            setattr(user,field,value)
        user.is_staff=user.is_superuser
        if user_id==actor.pk and (not user.is_active or not user.is_superuser):raise ValueError('You cannot disable or demote your own account.')
        if user_id and was_active and was_admin and not (user.is_active and user.is_superuser):
            if not get_user_model().objects.filter(is_active=True,is_superuser=True).exclude(pk=user.pk).exists():raise ValueError('Keep at least one active administrator.')
        password=data['password']
        if not isinstance(password,str) or len(password)>1024:raise ValueError('Password must be text of at most 1024 characters.')
        if not user_id and not password:raise ValueError('A password is required for a new account.')
        user.full_clean(exclude=['password','last_login','date_joined'])
        if password:validate_password(password,user);user.set_password(password)
        user.save()
        if user_id and (password or was_active!=user.is_active or was_admin!=user.is_superuser):
            revoke(user,request.session.session_key if user_id==actor.pk else None)
        audit(f'{actor.pk}:{actor.username}','user-updated' if user_id else 'user-created',user_id=user.pk,username=user.username,is_active=user.is_active,is_superuser=user.is_superuser,password_changed=bool(password))
        result=serialize(user)
    if user_id==request.user.pk:
        if password:update_session_auth_hash(request,user)
        request.user=user
    return result


def remove(request, data, user_id):
    with locked():
        actor=actor_now(request);user=get_user_model().objects.get(pk=user_id)
        if set(data)!={'revision','confirm_username'} or data['confirm_username']!=user.username or not constant_time_compare(str(data['revision']),revision(user)):raise ValueError('Account changed or confirmation does not match. Refresh before deleting.')
        if user.pk==actor.pk:raise ValueError('You cannot delete your own account.')
        if user.is_active and user.is_superuser and not get_user_model().objects.filter(is_active=True,is_superuser=True).exclude(pk=user.pk).exists():raise ValueError('Keep at least one active administrator.')
        if VncWorkspace.objects.filter(owner=user).exists() or ApplicationOwnership.objects.filter(owner=user).exists():raise ValueError('This user owns workspaces or applications. Disable the account, or resolve ownership before deletion.')
        revoke(user)
        audit(f'{actor.pk}:{actor.username}','user-deleted',user_id=user.pk,username=user.username)
        user.delete()


@sensitive_post_parameters('password')
@require_http_methods(['GET','POST','PATCH','DELETE'])
@administrator
def users(request,user_id=None):
    try:
        if request.method=='GET':
            if user_id:return response({'user':serialize(get_user_model().objects.get(pk=user_id))})
            query=request.GET.get('q','').strip()[:150]
            rows=get_user_model().objects.filter(Q(username__icontains=query)|Q(email__icontains=query)|Q(first_name__icontains=query)|Q(last_name__icontains=query)).order_by('username','pk')
            page=Paginator(rows,50).get_page(request.GET.get('page',1))
            return response({'users':[serialize(user) for user in page], 'page':page.number,'pages':page.paginator.num_pages,'total':page.paginator.count})
        data=body(request)
        if request.method=='POST' and user_id is None:return response({'user':save(request,data)},201)
        if request.method=='PATCH' and user_id is not None:return response({'user':save(request,data,user_id)})
        if request.method=='DELETE' and user_id is not None:remove(request,data,user_id);return response({'deleted':True})
        return response({'detail':'Unsupported account operation.'},405)
    except get_user_model().DoesNotExist:return response({'detail':'User not found.'},404)
    except PermissionError:return response({'detail':'Administrator access required.'},403)
    except ValidationError as error:return response({'detail':' '.join(error.messages)},400)
    except (IntegrityError,ProtectedError):return response({'detail':'Username already exists or account ownership prevents this operation. Refresh and review.'},409)
    except (ValueError,TypeError,KeyError,RequestDataTooBig) as error:return response({'detail':str(error) if isinstance(error,ValueError) else 'Invalid account request.'},409)

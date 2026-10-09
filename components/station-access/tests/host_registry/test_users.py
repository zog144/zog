import json
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.test import TestCase, Client
from django.utils import timezone
from datetime import timedelta
from zog.station_access.models import ApplicationOwnership, VncWorkspace, VncAccessGrant
from zog.station_access.host_registry.models import SecurityAudit
from zog.station_access.host_registry.user_views import serialize, save

class UserManagementTests(TestCase):
    def setUp(self):
        self.admin=get_user_model().objects.create_superuser('administrator',password='fixture-administrator-password')
        self.member=get_user_model().objects.create_user('member',password='fixture-member-password')
        self.client.force_login(self.admin)
    def fields(self,user=None,**changes):
        value=dict(username='new-user',email='',first_name='',last_name='',is_active=True,is_superuser=False,password='Unique-fixture-password-92!')
        if user:
            row=serialize(user);value.update({k:row[k] for k in value if k!='password'});value.update(password='',revision=row['revision'])
        return value|changes
    def send(self,method,user=None,data=None):return getattr(self.client,method)('/api/users/'+(str(user.pk)+'/' if user else ''),json.dumps(data or {}),content_type='application/json')
    def test_administrator_and_csrf_required_for_every_mutation(self):
        self.client.logout();self.assertEqual(self.client.get('/api/users/').status_code,401)
        self.client.force_login(self.member)
        for method in ('post','patch','delete'):self.assertEqual(self.send(method,self.admin).status_code,403)
        client=Client(enforce_csrf_checks=True);client.force_login(self.admin)
        for method in ('post','patch','delete'):self.assertEqual(getattr(client,method)('/api/users/',json.dumps(self.fields()),content_type='application/json').status_code,403)
    def test_create_list_update_and_delete_without_exposing_hashes(self):
        created=self.send('post',data=self.fields());self.assertEqual(created.status_code,201,created.content)
        user=get_user_model().objects.get(pk=created.json()['user']['id']);self.assertTrue(user.check_password('Unique-fixture-password-92!'))
        self.assertNotIn('password',created.content.decode());self.assertNotIn(user.password,self.client.get('/api/users/').content.decode())
        response=self.send('patch',user,self.fields(user,email='person@example.test',is_superuser=True));self.assertEqual(response.status_code,200,response.content)
        user.refresh_from_db();self.assertTrue(user.is_staff and user.is_superuser)
        response=self.send('delete',user,dict(revision=serialize(user)['revision'],confirm_username=user.username));self.assertEqual(response.status_code,200)
        self.assertFalse(get_user_model().objects.filter(pk=user.pk).exists());self.assertEqual(SecurityAudit.objects.filter(action__startswith='user-').count(),3)
        self.assertNotIn('Unique-fixture-password',str(list(SecurityAudit.objects.values())))
    def test_validation_stale_edit_and_mass_assignment(self):
        for changes in ({'password':'short'},{'password':'123456789012'},{'username':'invalid name'},{'email':'bad'},{'is_active':'false'}):
            self.assertIn(self.send('post',data=self.fields(**changes)).status_code,(400,409))
        self.assertEqual(self.send('post',data=self.fields(username=self.member.username)).status_code,400)
        self.assertEqual(self.send('post',data=self.fields()|{'is_staff':True}).status_code,409)
        old=self.fields(self.member);self.member.first_name='Concurrent';self.member.save()
        self.assertEqual(self.send('patch',self.member,old).status_code,409)
    def test_self_lockout_is_blocked(self):
        for change in ({'is_active':False},{'is_superuser':False}):self.assertEqual(self.send('patch',self.admin,self.fields(self.admin,**change)).status_code,409)
        self.assertEqual(self.send('delete',self.admin,dict(revision=serialize(self.admin)['revision'],confirm_username=self.admin.username)).status_code,409)
        self.assertTrue(get_user_model().objects.filter(is_superuser=True,is_active=True).exists())
    def test_actor_permissions_rechecked_after_decorator(self):
        from django.test import RequestFactory
        request=RequestFactory().post('/api/users/');request.user=self.admin
        get_user_model().objects.filter(pk=self.admin.pk).update(is_superuser=False)
        with self.assertRaises(PermissionError):save(request,self.fields())
    def test_delete_does_not_cascade_owned_resources(self):
        app=ApplicationOwnership.objects.create(application_name='owned',owner=self.member)
        data=dict(revision=serialize(self.member)['revision'],confirm_username=self.member.username)
        self.assertEqual(self.send('delete',self.member,data).status_code,409);self.assertTrue(ApplicationOwnership.objects.filter(pk=app.pk).exists())
        app.delete();workspace=VncWorkspace.objects.create(name='Retained',number=100,owner=self.member,application_name='desktop')
        self.assertEqual(self.send('delete',self.member,data).status_code,409);self.assertTrue(VncWorkspace.objects.filter(pk=workspace.pk).exists())
    def test_disable_reactivate_does_not_restore_old_sessions_and_revokes_grants(self):
        other=Client();other.force_login(self.member);session=other.session.session_key
        workspace=VncWorkspace.objects.create(name='Retained',number=101,owner=self.member,application_name='desktop')
        grant=VncAccessGrant.objects.create(user=self.member,workspace=workspace,token_digest='x'*64,runtime_id='fixture',endpoint_revision=0,target_host='127.0.0.1',target_port=5901,expires_at=timezone.now()+timedelta(minutes=1))
        self.assertEqual(self.send('patch',self.member,self.fields(self.member,is_active=False)).status_code,200)
        self.assertFalse(Session.objects.filter(session_key=session).exists());grant.refresh_from_db();self.assertIsNotNone(grant.revoked_at)
        self.member.refresh_from_db();self.assertEqual(self.send('patch',self.member,self.fields(self.member,is_active=True)).status_code,200)
        self.assertFalse(other.get('/api/session/').json()['authenticated'])
    def test_password_reset_invalidates_other_sessions_preserves_current_self_session(self):
        other=Client();other.force_login(self.admin)
        self.assertEqual(self.send('patch',self.admin,self.fields(self.admin,password='Replacement-fixture-pass-928!')).status_code,200)
        self.assertTrue(self.client.get('/api/session/').json()['authenticated']);self.assertFalse(other.get('/api/session/').json()['authenticated'])
    def test_wrong_delete_confirmation_and_missing_user(self):
        self.assertEqual(self.send('delete',self.member,dict(revision=serialize(self.member)['revision'],confirm_username='wrong')).status_code,409)
        self.assertEqual(self.client.get('/api/users/99999/').status_code,404)
    def test_search_pagination_and_removed_admin(self):
        self.assertEqual(self.client.get('/api/users/?q=member').json()['total'],1)
        self.assertEqual(self.client.get('/api/users/?q=absent').json()['users'],[])
        for path in ('/admin','/admin/','/admin/login/','/admin/auth/user/'):
            self.assertEqual(self.client.get(path).status_code,404)
        self.assertEqual(self.client.get('/users').status_code,200)

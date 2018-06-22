from django.db import connection
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect
from django.utils.translation import ugettext as _

from .exceptions import Forbidden
from .signals import session_tenant_changed
from .utils import activate_tenant

TENANT_CHANGED = _('Tenant changed to %(active_tenant)s')
TENANT_CLEARED = _('Tenant deselected')
UNABLE_TO_CHANGE_TENANT = _('You may not select that tenant')


def clear_tenant(session):
    session.pop('active_tenant')
    session.pop('active_tenant_name')


def set_tenant(session, tenant):
    session.update({
        'active_tenant': tenant.pk,
        'active_tenant_name': tenant.name
    })


def select_tenant(request, tenant):
    """
    Ensure that the request/user is allowed to select this tenant,
    and then set that in the session.

    Does not actually activate the tenant.
    """
    session, user = request.session, request.user

    # Clear the tenant (deselect)
    if not tenant:
        clear_tenant(session)
        return

    # Clear the tenant if we have a non-authenticated user.
    if not user.is_authenticated:
        clear_tenant(session)
        return

    # We need to query the db, so we need the primary key.
    if getattr(tenant, 'pk', None):
        tenant = tenant.pk

    # If no change, don't hit the database.
    if tenant == session.get('active_tenant'):
        return

    # Can this user view this tenant?
    try:
        tenant = user.visible_tenants.get(pk=tenant)
    except user.visible_tenants.DoesNotExist:
        raise Forbidden()
    else:
        set_tenant(session, tenant)
        session_tenant_changed.send(sender=request, tenant=tenant, user=user, session=session)


def SelectTenant(get_response):
    def middleware(request):
        try:
            if request.path.startswith('/__change_tenant__/'):
                select_tenant(request, request.path.split('/')[2])
                if request.session.get('active_tenant'):
                    return HttpResponse(TENANT_CHANGED % request.session)
                return HttpResponse(TENANT_CLEARED)
            elif request.GET.get('__tenant') is not None:
                select_tenant(request, request.GET['__tenant'])
                data = request.GET.copy()
                data.pop('__tenant')
                if request.method == 'GET':
                    if data:
                        return redirect(request.path + '?' + data.urlencode())
                    return redirect(request.path)
                request.GET = data
            elif 'HTTP_X_CHANGE_TENANT' in request.META:
                select_tenant(request, request.META['HTTP_X_CHANGE_TENANT'])
        except Forbidden:
            return HttpResponseForbidden(UNABLE_TO_CHANGE_TENANT)

        return get_response(request)

    return middleware


def ActivateTenant(get_response):
    def middleware(request):
        if request.user.pk:
            connection.cursor().execute('SET occupation.user_id = %s', [request.user.pk])
        activate_tenant(request.session.get('active_tenant', ''))
        return get_response(request)

    return middleware
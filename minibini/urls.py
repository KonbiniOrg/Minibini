"""
URL configuration for minibini project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView
from apps.core.views import settings_view, tax_config_edit

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', TemplateView.as_view(template_name='home.html'), name='home'),
    path('settings/', settings_view, name='settings'),
    path('settings/tax/', tax_config_edit, name='tax_config_edit'),
    path('jobs/', include('apps.jobs.urls')),
    path('contacts/', include('apps.contacts.urls')),
    path('core/', include('apps.core.urls')),
    path('purchasing/', include('apps.purchasing.urls')),
    path('invoicing/', include('apps.invoicing.urls')),
    path('search/', include('apps.search.urls')),
    path('inventory/', include('apps.inventory.urls')),
]

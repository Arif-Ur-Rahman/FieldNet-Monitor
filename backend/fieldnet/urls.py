from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from core.views import healthz
from gateways import gw_views
from gateways import views as gw
from sensors import views as sn

api_v1 = [
    path("gateways", gw.GatewayListView.as_view()),
    path("gateways/<str:gateway_id>", gw.GatewayDetailView.as_view()),
    path("gateways/<str:gateway_id>/timeline", gw.GatewayTimelineView.as_view()),
    path("sensors", sn.SensorListView.as_view()),
    path("sensors/<str:sensor_id>", sn.SensorDetailView.as_view()),
    path("sensors/<str:sensor_id>/coverage", sn.SensorCoverageView.as_view()),
    path("sensors/<str:sensor_id>/actions", sn.SensorActionsView.as_view()),
    path("sensors/<str:sensor_id>/timeline", sn.SensorTimelineView.as_view()),
]

gw_v1 = [
    path("heartbeat", gw_views.HeartbeatView.as_view()),
    path("cycles", gw_views.CycleView.as_view()),
]

urlpatterns = [
    path("healthz", healthz),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path("api/v1/", include(api_v1)),
    path("gw/v1/", include(gw_v1)),
]

handler404 = "core.errors.handler404"
handler500 = "core.errors.handler500"

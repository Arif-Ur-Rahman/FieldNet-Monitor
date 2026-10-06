from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from batches import views as batch_views
from core.views import ConfigView, DashboardView, healthz
from gateways import gw_views
from gateways import views as gw
from sensors import views as sn
from testing import views as test_views

api_v1 = [
    path("dashboard", DashboardView.as_view()),
    path("config", ConfigView.as_view()),
    path("gateways", gw.GatewayListView.as_view()),
    path("gateways/<str:gateway_id>", gw.GatewayDetailView.as_view()),
    path("gateways/<str:gateway_id>/timeline", gw.GatewayTimelineView.as_view()),
    path("gateways/<str:gateway_id>/actions", gw.GatewayActionsView.as_view()),
    path("sensors", sn.SensorListView.as_view()),
    path("sensors/<str:sensor_id>", sn.SensorDetailView.as_view()),
    path("sensors/<str:sensor_id>/coverage", sn.SensorCoverageView.as_view()),
    path("sensors/<str:sensor_id>/actions", sn.SensorActionsView.as_view()),
    path("sensors/<str:sensor_id>/timeline", sn.SensorTimelineView.as_view()),
    path("batches/<str:batch_id>", batch_views.BatchDetailView.as_view()),
]

gw_v1 = [
    path("heartbeat", gw_views.HeartbeatView.as_view()),
    path("cycles", gw_views.CycleView.as_view()),
    path("commands", gw_views.CommandsView.as_view()),
    path("commands/<str:command_id>/ack", gw_views.CommandAckView.as_view()),
    path("batches/<str:batch_id>", batch_views.GatewayBatchView.as_view()),
]

test_routes = [
    path("reset", test_views.ResetView.as_view()),
    path("clock", test_views.ClockView.as_view()),
    path("drain", test_views.DrainView.as_view()),
    path("faults", test_views.FaultsView.as_view()),
]

urlpatterns = [
    path("healthz", healthz),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path("api/v1/", include(api_v1)),
    path("gw/v1/", include(gw_v1)),
    path("test/", include(test_routes)),
]

handler404 = "core.errors.handler404"
handler500 = "core.errors.handler500"

from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from accounts.admin import backoffice_site
from accounts.forms import BackofficePasswordResetForm
from config.health import health
from learner.views import (
    AccessLinkView,
    LearnerCourseDetailView,
    LearnerCourseListView,
    LearnerCsrfView,
    LearnerLogoutView,
    LearnerMediaContentView,
    LearnerOfflineLicenseView,
    LearnerOfflineManifestView,
    LearnerOfflineMediaContentView,
    LearnerProgressView,
    LearnerSessionView,
    LearnerStreamURLView,
    PwaSessionTransferConsumeView,
    PwaSessionTransferView,
)
from media_assets.views import (
    MediaStatusView,
    MediaTransferConfigView,
    ProxyUploadView,
    StreamURLView,
    UploadCompleteView,
    UploadCreateView,
    VendorMediaContentView,
)
from vendor_api.views import (
    VendorAccessGrantView,
    VendorAccessListView,
    VendorAccessReissueView,
    VendorAccessRevokeView,
    VendorAuthView,
    VendorCourseArchiveView,
    VendorCourseDetailView,
    VendorCourseListView,
    VendorCoursePreviewView,
    VendorCoursePublishView,
    VendorCourseRestoreView,
    VendorCourseStructureView,
    VendorCsrfView,
    VendorLogoutView,
    VendorMediaListView,
    VendorMemberDetailView,
    VendorMemberListView,
    VendorMeView,
    VendorPasswordResetConfirmView,
    VendorPasswordResetRequestView,
)

urlpatterns = [
    path("health/", health, name="health"),
    path("api/v1/backoffice/media/uploads", UploadCreateView.as_view(), name="media-upload-create"),
    path(
        "api/v1/backoffice/media/<uuid:asset_id>/complete",
        UploadCompleteView.as_view(),
        name="media-upload-complete",
    ),
    path(
        "api/v1/backoffice/media/<uuid:asset_id>",
        MediaStatusView.as_view(),
        name="media-status",
    ),
    path(
        "api/v1/media/<uuid:asset_id>/stream-url",
        StreamURLView.as_view(),
        name="media-stream-url",
    ),
    path("api/v1/vendor/csrf", VendorCsrfView.as_view(), name="vendor-csrf"),
    path(
        "api/v1/vendor/media/config", MediaTransferConfigView.as_view(), name="vendor-media-config"
    ),
    path(
        "api/v1/vendor/media/upload-file",
        ProxyUploadView.as_view(),
        name="vendor-media-upload-file",
    ),
    path("api/v1/vendor/auth/login", VendorAuthView.as_view(), name="vendor-login"),
    path("api/v1/vendor/auth/logout", VendorLogoutView.as_view(), name="vendor-logout"),
    path(
        "api/v1/vendor/auth/password-reset",
        VendorPasswordResetRequestView.as_view(),
        name="vendor-password-reset",
    ),
    path(
        "api/v1/vendor/auth/password-reset/<uidb64>/<token>",
        VendorPasswordResetConfirmView.as_view(),
        name="vendor-password-reset-confirm",
    ),
    path("api/v1/vendor/me", VendorMeView.as_view(), name="vendor-me"),
    path("api/v1/vendor/courses", VendorCourseListView.as_view(), name="vendor-courses"),
    path(
        "api/v1/vendor/courses/<uuid:course_id>",
        VendorCourseDetailView.as_view(),
        name="vendor-course",
    ),
    path(
        "api/v1/vendor/courses/<uuid:course_id>/publish",
        VendorCoursePublishView.as_view(),
        name="vendor-course-publish",
    ),
    path(
        "api/v1/vendor/courses/<uuid:course_id>/archive",
        VendorCourseArchiveView.as_view(),
        name="vendor-course-archive",
    ),
    path(
        "api/v1/vendor/courses/<uuid:course_id>/restore",
        VendorCourseRestoreView.as_view(),
        name="vendor-course-restore",
    ),
    path(
        "api/v1/vendor/courses/<uuid:course_id>/preview",
        VendorCoursePreviewView.as_view(),
        name="vendor-course-preview",
    ),
    path(
        "api/v1/vendor/courses/<uuid:course_id>/structure",
        VendorCourseStructureView.as_view(),
        name="vendor-course-structure",
    ),
    path("api/v1/vendor/access", VendorAccessListView.as_view(), name="vendor-access-list"),
    path(
        "api/v1/vendor/access/grant",
        VendorAccessGrantView.as_view(),
        name="vendor-access-grant",
    ),
    path(
        "api/v1/vendor/access/<uuid:enrollment_id>/revoke",
        VendorAccessRevokeView.as_view(),
        name="vendor-access-revoke",
    ),
    path(
        "api/v1/vendor/access/<uuid:enrollment_id>/reissue",
        VendorAccessReissueView.as_view(),
        name="vendor-access-reissue",
    ),
    path("api/v1/vendor/members", VendorMemberListView.as_view(), name="vendor-members"),
    path("api/v1/vendor/media", VendorMediaListView.as_view(), name="vendor-media-list"),
    path(
        "api/v1/vendor/members/<uuid:member_id>",
        VendorMemberDetailView.as_view(),
        name="vendor-member",
    ),
    path(
        "api/v1/vendor/media/uploads",
        UploadCreateView.as_view(),
        name="vendor-media-upload-create",
    ),
    path(
        "api/v1/vendor/media/<uuid:asset_id>/complete",
        UploadCompleteView.as_view(),
        name="vendor-media-upload-complete",
    ),
    path(
        "api/v1/vendor/media/<uuid:asset_id>",
        MediaStatusView.as_view(),
        name="vendor-media-status",
    ),
    path(
        "api/v1/vendor/media/<uuid:asset_id>/content",
        VendorMediaContentView.as_view(),
        name="vendor-media-content",
    ),
    path("api/v1/learner/access/<str:token>", AccessLinkView.as_view(), name="learner-access"),
    path("api/v1/learner/csrf", LearnerCsrfView.as_view(), name="learner-csrf"),
    path("api/v1/learner/session", LearnerSessionView.as_view(), name="learner-session"),
    path(
        "api/v1/learner/pwa-transfer",
        PwaSessionTransferView.as_view(),
        name="learner-pwa-transfer",
    ),
    path(
        "api/v1/learner/pwa-transfer/consume",
        PwaSessionTransferConsumeView.as_view(),
        name="learner-pwa-transfer-consume",
    ),
    path("api/v1/learner/logout", LearnerLogoutView.as_view(), name="learner-logout"),
    path("api/v1/learner/courses", LearnerCourseListView.as_view(), name="learner-courses"),
    path(
        "api/v1/learner/courses/<uuid:course_id>",
        LearnerCourseDetailView.as_view(),
        name="learner-course",
    ),
    path(
        "api/v1/learner/courses/<uuid:course_id>/offline-manifest",
        LearnerOfflineManifestView.as_view(),
        name="learner-offline-manifest",
    ),
    path(
        "api/v1/learner/courses/<uuid:course_id>/offline-license",
        LearnerOfflineLicenseView.as_view(),
        name="learner-offline-license",
    ),
    path(
        "api/v1/learner/courses/<uuid:course_id>/offline-media/<uuid:revision_id>/<uuid:asset_id>",
        LearnerOfflineMediaContentView.as_view(),
        name="learner-offline-media-content",
    ),
    path(
        "api/v1/learner/courses/<uuid:course_id>/progress",
        LearnerProgressView.as_view(),
        name="learner-progress-list",
    ),
    path(
        "api/v1/learner/courses/<uuid:course_id>/progress/<uuid:lesson_id>",
        LearnerProgressView.as_view(),
        name="learner-progress",
    ),
    path(
        "api/v1/learner/courses/<uuid:course_id>/media/<uuid:asset_id>/stream-url",
        LearnerStreamURLView.as_view(),
        name="learner-stream-url",
    ),
    path(
        "api/v1/learner/courses/<uuid:course_id>/media/<uuid:asset_id>/content",
        LearnerMediaContentView.as_view(),
        name="learner-media-content",
    ),
    path(
        "backoffice/password_reset/",
        auth_views.PasswordResetView.as_view(
            form_class=BackofficePasswordResetForm,
            email_template_name="registration/password_reset_email.txt",
            subject_template_name="registration/password_reset_subject.txt",
            success_url=reverse_lazy("password_reset_done"),
        ),
        name="admin_password_reset",
    ),
    path(
        "backoffice/password_reset/done/",
        auth_views.PasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "backoffice/password_reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            success_url=reverse_lazy("password_reset_complete")
        ),
        name="password_reset_confirm",
    ),
    path(
        "backoffice/password_reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
    path("backoffice/", backoffice_site.urls),
]

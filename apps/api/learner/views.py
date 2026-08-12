from django.http import Http404
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from learner.models import AccessLink, hash_access_token


class AccessLinkView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request, token: str) -> Response:  # type: ignore[no-untyped-def]
        link = (
            AccessLink.objects.filter(token_hash=hash_access_token(token), revoked_at__isnull=True)
            .select_related("enrollment__course")
            .first()
        )
        if link is None or link.enrollment.status != "active":
            raise Http404
        return Response(
            {
                "email": link.enrollment.learner.email,
                "course_title": link.enrollment.course.title,
            }
        )


class LearnerSessionView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request) -> Response:  # type: ignore[no-untyped-def]
        return Response({"code": "LEARNER_SESSION_NOT_READY"}, status=501)

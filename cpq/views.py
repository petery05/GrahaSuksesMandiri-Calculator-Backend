from django.contrib.auth import authenticate
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from . import services
from .models import Finish, GlassType, Partner, Product, Quote
from .serializers import (
    ComputeInputSerializer,
    FinishSerializer,
    GlassSerializer,
    PartnerSerializer,
    ProductSerializer,
    QuoteReadSerializer,
    QuoteWriteSerializer,
)


@api_view(['GET'])
@permission_classes([AllowAny])
def health(request):
    return Response({'status': 'ok', 'app': 'gsm-cpq'})


# ---------- auth ----------
def _user_data(user):
    return {
        'authenticated': True,
        'user': {'id': user.id, 'username': user.username, 'is_staff': user.is_staff},
    }


@api_view(['GET'])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def me(request):
    if request.user.is_authenticated:
        return Response(_user_data(request.user))
    return Response({'authenticated': False})


@api_view(['POST'])
@permission_classes([AllowAny])
def login_view(request):
    user = authenticate(
        request,
        username=request.data.get('username'),
        password=request.data.get('password'),
    )
    if user is None:
        return Response({'detail': 'Invalid username or password.'}, status=status.HTTP_400_BAD_REQUEST)
    django_login(request, user)
    return Response(_user_data(user))


@api_view(['POST'])
@permission_classes([AllowAny])
def logout_view(request):
    django_logout(request)
    return Response({'authenticated': False})


# ---------- catalog ----------
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def catalog(request):
    return Response({
        'partners': PartnerSerializer(Partner.objects.all(), many=True).data,
        'products': ProductSerializer(
            Product.objects.prefetch_related('kit_links__component'), many=True).data,
        'glass': GlassSerializer(GlassType.objects.all(), many=True).data,
        'finishes': FinishSerializer(Finish.objects.all(), many=True).data,
    })


# ---------- pricing ----------
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def compute(request):
    serializer = ComputeInputSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    partner = Partner.objects.get(code=data['partner'])
    try:
        result = services.compute_for_partner(
            partner, data['lines'], data['margin_pct'], data['lang'])
    except ValueError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


# ---------- quotes ----------
class QuoteViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    # Editing existing quotes (PUT/PATCH) is wired up in Phase 3; for now a quote
    # is created, listed, read, or deleted — its price snapshot stays immutable.
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_queryset(self):
        return Quote.objects.filter(owner=self.request.user).prefetch_related('lines')

    def get_serializer_class(self):
        return QuoteWriteSerializer if self.action == 'create' else QuoteReadSerializer

    def create(self, request, *args, **kwargs):
        serializer = QuoteWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            quote = services.persist_quote(request.user, serializer.validated_data)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(QuoteReadSerializer(quote).data, status=status.HTTP_201_CREATED)

import datetime
import logging
import warnings
from json import JSONEncoder

import jwt
from pyramid.renderers import JSON
from zope.interface import implementer
from pyramid.authentication import CallbackAuthenticationPolicy
from pyramid.interfaces import IAuthenticationPolicy, IRendererFactory

log = logging.getLogger("pyramid_jwt")
marker = []


class PyramidJSONEncoderFactory(JSON):
    def __init__(self, pyramid_registry=None, **kw):
        super().__init__(**kw)
        self.registry = pyramid_registry

    def __call__(self, *args, **kwargs):
        json_renderer = None
        if self.registry is not None:
            json_renderer = self.registry.queryUtility(
                IRendererFactory, "json", default=JSONEncoder
            )

        request = kwargs.get("request")
        if not kwargs.get("default") and isinstance(json_renderer, JSON):
            self.components = json_renderer.components
            kwargs["default"] = self._make_default(request)
        return JSONEncoder(*args, **kwargs)


json_encoder_factory = PyramidJSONEncoderFactory(None)


@implementer(IAuthenticationPolicy)
class JWTAuthenticationPolicy(CallbackAuthenticationPolicy):
    def __init__(
        self,
        private_key,
        public_key=None,
        algorithm="HS512",
        leeway=0,
        expiration=None,
        default_claims=None,
        http_header="Authorization",
        auth_type="JWT",
        callback=None,
        json_encoder=None,
        audience=None,
    ):
        self.private_key = private_key
        self.public_key = public_key if public_key is not None else private_key
        self.algorithm = algorithm
        self.leeway = leeway
        self.default_claims = default_claims if default_claims else {}
        self.http_header = http_header
        self.auth_type = auth_type
        if expiration:
            if not isinstance(expiration, datetime.timedelta):
                expiration = datetime.timedelta(seconds=expiration)
            self.expiration = expiration
        else:
            self.expiration = None
        if audience:
            self.audience = audience
        else:
            self.audience = None
        self.callback = callback
        if json_encoder is None:
            json_encoder = json_encoder_factory
        self.json_encoder = json_encoder

    def create_token(self, principal, expiration=None, audience=None, **claims):
        payload = self.default_claims.copy()
        payload.update(claims)
        payload["sub"] = principal
        payload["iat"] = iat = datetime.datetime.utcnow()
        expiration = expiration or self.expiration
        audience = audience or self.audience
        if expiration:
            if not isinstance(expiration, datetime.timedelta):
                expiration = datetime.timedelta(seconds=expiration)
            payload["exp"] = iat + expiration
        if audience:
            payload["aud"] = audience
        token = jwt.encode(
            payload,
            self.private_key,
            algorithm=self.algorithm,
            json_encoder=self.json_encoder,
        )
        if not isinstance(token, str):  # Python3 unicode madness
            token = token.decode("ascii")
        return token

    def get_claims(self, request):
        if self.http_header == "Authorization":
            try:
                if request.authorization is None:
                    return {}
            except ValueError:  # Invalid Authorization header
                return {}
            (auth_type, token) = request.authorization
            if auth_type != self.auth_type:
                return {}
        else:
            token = request.headers.get(self.http_header)
        if not token:
            return {}
        try:
            claims = jwt.decode(
                token,
                self.public_key,
                algorithms=[self.algorithm],
                leeway=self.leeway,
                audience=self.audience,
            )
            return claims
        except jwt.InvalidTokenError as e:
            log.warning("Invalid JWT token from %s: %s", request.remote_addr, e)
            return {}

    def unauthenticated_userid(self, request):
        return request.jwt_claims.get("sub")

    def remember(self, request, principal, **kw):
        warnings.warn(
            "JWT tokens need to be returned by an API. Using remember() "
            "has no effect.",
            stacklevel=3,
        )
        return []

    def forget(self, request):
        warnings.warn(
            "JWT tokens are managed by API (users) manually. Using forget() "
            "has no effect.",
            stacklevel=3,
        )
        return []
